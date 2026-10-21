"""Barrido diario (HIPOTESIS_v7.md): añade wallets nuevas, refresca las seguidas, vigila movimientos de capital y saca las que fallan.

Lo ejecuta una rutina (sesión nueva cada día): lee del panel el estado anterior (carpeta de JSON de `wallets/`), corre esto con la
clave de GMGN del entorno, y escribe el resultado (`wallets/{addr}` y `meta/sweep`) en la base de datos del panel.
Presupuesto de tiempo y de llamadas a GMGN acotado: el plan gratuito se vacía a ~1 unidad por segundo.
"""
import hashlib
import json
import os
import time

from . import audit, deepwallet, discover, flows, gmgnwallet, pumps, sweep

DAY = 86400
# campos de un documento de wallet que el barrido conserva del anterior (clusters, descartes manuales, origen y token que la hizo descubrir)
PRESERVE = ("cluster", "excluded", "source_tag", "trigger_mints")


def load_prev(folder):
    """Documentos del panel exportados con ArtifactData (out_dir). Devuelve {addr: doc}."""
    out = {}
    base = os.path.join(folder, "wallets")
    if not os.path.isdir(base):
        return out
    for f in os.listdir(base):
        if f.endswith(".json"):
            try:
                d = json.load(open(os.path.join(base, f), encoding="utf-8"))
            except Exception:
                continue
            out[f[:-5]] = d.get("data", d) if isinstance(d, dict) else d
    return out


def cfg_snapshot(cfg):
    """Configuración con la que se evalúa (filtros por defecto + constantes de la auditoría) y su huella: así cada barrido dice con qué reglas se hizo."""
    snap = {"copy": cfg["copy"], "history": cfg.get("history"),
            "audit": {"stale_days": audit.STALE_DAYS, "fee": audit.FEE, "entry_pen": audit.ENTRY_PEN, "exit_pen": audit.EXIT_PEN,
                      "delta_e": audit.DELTA_E, "delta_s": audit.DELTA_S, "grad_sol": audit.GRAD_SOL}}
    snap["ver"] = hashlib.sha1(json.dumps(snap, sort_keys=True, default=str).encode()).hexdigest()[:10]
    return snap


def snapshot_doc(docs, now):
    """Instantánea inmutable del barrido: métricas clave de TODAS las wallets evaluadas hoy (no solo las que cumplen). Sirve para medir después,
    con datos que no se reescriben, si lo que pasaba los filtros seguía funcionando."""
    rows = {}
    for w, d in docs.items():
        m = d.get("m") or {}
        a = d.get("aud") or {}
        rows[w] = {"st": d.get("status"), "n": m.get("n_closed"), "roi": m.get("roi"), "hold": m.get("median_hold_s"), "cr": m.get("copy_r"),
                   "ex2": m.get("copy_total_ex2"), "complete": m.get("complete"), "span": m.get("span_days"),
                   "aud_r": a.get("r"), "aud_p5": a.get("p5"), "aud_n": a.get("n"), "bags": d.get("bags_known")}
    return {"ts": now, "wallets": rows}


def preserve(docs, prev):
    """Copia a los documentos nuevos los campos de PRESERVE del documento anterior (si el nuevo no los trae)."""
    for w, doc in docs.items():
        for k in PRESERVE:
            if prev.get(w) and prev[w].get(k) is not None and not doc.get(k):
                doc[k] = prev[w][k]
    return docs


def pick_refresh(prev, n=8):
    """Wallets seguidas a refrescar hoy: las activas primero y, dentro de cada grupo, las menos recientes."""
    cand = [(a, d) for a, d in prev.items() if d.get("status") in ("active", "candidate", "dropped")
            and ((d.get("m") or {}).get("roi") or 0) > 0.2 and ((d.get("m") or {}).get("n_closed") or 0) >= 15]
    cand.sort(key=lambda x: (0 if x[1].get("status") == "active" else 1, x[1].get("last_ts") or 0))
    return [a for a, _ in cand[:n]]


def run(cfg, g, prev, out_path, sol_usd, new_tokens=20, new_wallets=120, verify_n=8, refresh_n=8, budget_s=3 * 3600, pump_tokens=40,
        log=print, now=None):
    t0 = time.time()
    now = int(now or t0)
    over = lambda: time.time() - t0 > budget_s
    known = set(prev)
    # 1) wallets nuevas desde GMGN (se saltan las ya conocidas)
    cands, trig = [], {}
    if not over():
        cands = discover.gmgn_candidates(g, intervals=("24h", "6h"), order_by=("volume", "smart_degen_count"),
                                         tokens_per_interval=new_tokens, max_wallets=new_wallets, skip=known, log=log)
    # 1b) wallets que entraron ANTES de pumps recientes (tokens que suben de golpe); sin estado entre días: cada rutina empieza de cero
    if not over() and pump_tokens:
        try:
            have = {w for w, _ in cands}
            more = pumps.discover_wallets(g, {"tokens": {}, "stats": {}}, now, discover, max_tokens=pump_tokens, max_wallets=150,
                                          skip=known | have, log=log)
            trig.update({w: s.get("trigger_mints") for w, s in more})
            log(f"wallets nuevas desde tokens que pumpean: {len(more)}")
            cands += more
        except Exception as e:
            log(f"  pumps: {str(e)[:80]}")
    cands.sort(key=lambda x: -((x[1]["pnl"] or 0) * min(1.0, (x[1]["buys"] or 0) / 100.0 + 0.5)))
    todo = [w for w, _ in cands[:verify_n]] + pick_refresh(prev, refresh_n)
    log(f"a verificar: {len(todo)} ({min(len(cands), verify_n)} nuevas + refresco)")
    # 2) historial completo (GMGN) y saldo
    results, bal = [], {}
    for i, w in enumerate(todo, 1):
        if over():
            log("presupuesto de tiempo agotado; se deja el resto para mañana")
            break
        try:
            m, pos = gmgnwallet.analyze(g, w, cfg, sol_usd, days=cfg["copy"]["days"], max_pages=120, now=now)
            st = discover._patient(lambda: g.wallet_stats([w], "30d").get(w), log=lambda m_: None) or {}
        except Exception as e:
            log(f"  {w[:8]}… error {str(e)[:70]}")
            continue
        bal[w] = st.get("sol_balance")
        results.append({"metrics": m, "positions": pos, "trigger_mints": trig.get(w) or (prev.get(w) or {}).get("trigger_mints") or None})
        log(f"[{i}/{len(todo)}] {w[:8]}… cerradas {m['n_closed']} · retorno {('—' if m['roi'] is None else '%+.0f%%' % (m['roi'] * 100))}")
    prev_state = {a: {"status": d.get("status"), "joined_ts": d.get("joined_ts")} for a, d in prev.items()}
    docs, meta = sweep.build_docs(results, prev_state, cfg, now=now, sol_usd=sol_usd)
    # campos puestos a mano o por análisis aparte: el barrido escribe cada documento con `set` y NO debe borrarlos
    preserve(docs, prev)
    # 3) movimientos de capital de las activas, candidatas buenas y las verificadas hoy
    tracked = [a for a, d in {**prev, **docs}.items() if d.get("status") in ("active",)] + [w for w in docs]
    tracked = list(dict.fromkeys(tracked))[:25]
    per = {}
    for w in tracked:
        if over():
            break
        try:
            rows = flows.fetch_transfers(g, w, days=cfg["copy"]["days"], max_pages=6, now=now)
        except Exception as e:
            log(f"  flujos {w[:8]}…: {str(e)[:60]}")
            continue
        per[w] = flows.summarize(w, rows, tracked=tracked, now=now)
    shared = flows.shared_destinations(per)
    for w, f in per.items():
        doc = docs.get(w) or dict(prev.get(w) or {})
        hist = list((doc.get("balhist") or []))
        drop = flows.balance_drop(hist, bal.get(w)) if bal.get(w) is not None else None
        if bal.get(w) is not None:
            hist.append([now, round(bal[w], 2)])
        doc["balhist"] = hist[-40:]
        doc["flows"] = dict(f, balance_drop=drop, shared=[a for a, ws in shared.items() if w in ws])
        doc.setdefault("addr", w)
        docs[w] = doc
        why = f["flag"] or drop
        if why:
            meta["changes"].append({"ts": now, "type": "flow", "wallet": w, "why": why})
        if f["links"]:
            meta["changes"].append({"ts": now, "type": "link", "wallet": w, "why": "enlazada con " + ", ".join(a[:6] + "…" for a in f["links"])})
    meta["cfg"] = cfg_snapshot(cfg)
    meta["analyzed"] = len(known | set(docs))
    meta["shared_destinations"] = shared
    meta["active"] = sum(1 for a, d in {**prev, **docs}.items() if d.get("status") == "active")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"wallets": docs, "meta": meta, "snapshot": snapshot_doc(docs, now)}, f)
    log(f"{len(docs)} documentos a escribir · {meta['active']} activas · {len(meta['changes'])} cambios → {out_path}")
    return docs, meta


def make_batches(out_path, versions, folder, per_batch=40, meta_version=None):
    """Parte el resultado en un archivo JSON por documento y lista de lotes de escritura para ArtifactData (action batch).
    versions: {addr: version} de los documentos que ya existen en el panel (los de `list`); los nuevos van sin if_version."""
    with open(out_path, encoding="utf-8") as f:
        d = json.load(f)
    os.makedirs(folder, exist_ok=True)
    writes = []
    for addr, doc in d["wallets"].items():
        fp = os.path.join(folder, addr + ".json")
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(doc, f)
        w = {"op": "set", "collection": "wallets", "doc_id": addr, "file_path": fp}
        if addr in versions:
            w["if_version"] = versions[addr]
        writes.append(w)
    fp = os.path.join(folder, "meta_sweep.json")
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(d["meta"], f)
    meta_w = {"op": "set", "collection": "meta", "doc_id": "sweep", "file_path": fp}
    if meta_version:
        meta_w["if_version"] = meta_version
    writes.append(meta_w)
    if d.get("snapshot"):   # documento nuevo cada vez (nunca se sobrescribe): snap-AAAAMMDD-HHMM
        fp = os.path.join(folder, "snapshot.json")
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(d["snapshot"], f)
        writes.append({"op": "set", "collection": "meta", "doc_id": time.strftime("snap-%Y%m%d-%H%M", time.gmtime(d["snapshot"]["ts"])), "file_path": fp})
    batches = [writes[i:i + per_batch] for i in range(0, len(writes), per_batch)]
    with open(os.path.join(folder, "batches.json"), "w", encoding="utf-8") as f:
        json.dump(batches, f)
    return batches
