"""Barrido diario del panel de copia (dashboard/copy.html, HIPOTESIS_v7.md).

Función pura `build_docs`: a partir de los análisis de wallets (deepwallet.analyze) y del estado anterior del panel, produce
los documentos que hay que dejar en la base de datos del artefacto:
  wallets/{dirección}  {addr, pos: [[hora_entrada, tenencia_s, múltiplo, coste_sol], ...], m: {...}, joined_ts, last_ts, status}
  meta/sweep           {ts, sol_usd, analyzed, active, changes: [{ts, type, wallet, why}]}

Reglas:
  - Entra en `wallets` toda wallet con al menos `keep_min_closed` operaciones cerradas y alguna operación de +1000 % o una rentabilidad > 5 %: el panel
    aplica sus filtros en vivo, así que conviene guardar también las que hoy no cumplen los filtros por defecto.
  - `status` = "active" si cumple los filtros por defecto (deepwallet.passes), "candidate" si no.
  - `joined_ts` = primera vez que cumplió los filtros. Es el inicio del tramo «desde que entró»: lo único que no está
    contaminado por haberlas elegido mirando su pasado. Nunca se rehace al volver a entrar.
  - `changes` registra quién entra y quién sale con el motivo; las salidas se guardan como status "dropped" (no se borran,
    para conservar su tramo hacia adelante).
"""
import time

KEEP_MIN_CLOSED = 5


def _pos_rows(positions):
    rows = []
    for p in positions:
        if not p.get("closed") or p.get("mult") is None:
            continue
        rows.append([int(p["entry_ts"]), None if p.get("hold") is None else round(float(p["hold"]), 1),
                     round(float(p["mult"]), 4), round(float(p["cost"]), 4)])
    rows.sort(key=lambda r: r[0])
    return rows


def _m_doc(m):
    keys = ("n_closed", "n_open", "cost_sol", "pnl_sol", "pnl_ex_top2", "roi", "win_rate", "median_hold_s", "short_hold_share",
            "best_mult", "hits10", "ops_per_day", "bot", "span_days", "last_ts", "closed_recent", "copy_r", "copy_total_ex2")
    d = {k: m.get(k) for k in keys}
    d["complete"] = bool((m.get("coverage") or {}).get("reached_start", True))
    d["source"] = (m.get("coverage") or {}).get("source", "helius")
    return d


def build_docs(results, prev, cfg, now=None, sol_usd=None, passes=None):
    """results: lista de {"metrics", "positions"}; prev: {addr: {"joined_ts", "status"}} del barrido anterior (o {}).
    Devuelve (wallet_docs {addr: doc}, meta_doc)."""
    if passes is None:
        from .deepwallet import passes as passes_fn
        passes = passes_fn
    now = int(now or time.time())
    docs, changes = {}, []
    seen = set()
    for r in results:
        m = r["metrics"]
        w = m["wallet"]
        seen.add(w)
        ok, why = passes(m, cfg)
        was = prev.get(w) or {}
        prev_status = was.get("status")
        joined = was.get("joined_ts")
        keep = m["n_closed"] >= KEEP_MIN_CLOSED and (m["hits10"] >= 1 or (m["roi"] or 0) > 0.05)
        if not keep and not was:
            continue
        if ok:
            status = "active"
            if joined is None:
                joined = now
            if prev_status != "active":
                changes.append({"ts": now, "type": "add", "wallet": w,
                                "why": "cumple los filtros: %d op. cerradas, %d de +1000 %%" % (m["n_closed"], m["hits10"])})
        else:
            status = "dropped" if prev_status == "active" else ("candidate" if prev_status in (None, "candidate") else prev_status)
            if prev_status == "active":
                changes.append({"ts": now, "type": "drop", "wallet": w, "why": "; ".join(why)})
        docs[w] = {"addr": w, "pos": _pos_rows(r["positions"]), "m": _m_doc(m), "joined_ts": joined, "last_ts": now, "status": status}
    # wallets que estaban activas y no se pudieron analizar hoy: se conservan tal cual, sin inventar cambios
    meta = {"ts": now, "sol_usd": sol_usd, "analyzed": len(seen),
            "active": sum(1 for d in docs.values() if d["status"] == "active"),
            "changes": changes, "missing": sorted(w for w, v in prev.items() if w not in seen and v.get("status") == "active")}
    return docs, meta
