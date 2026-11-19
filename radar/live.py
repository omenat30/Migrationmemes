"""Seguimiento en vivo sin dinero de las wallets que el usuario copia (pedido del 19-nov-2026).

Qué hace: cada día lee la actividad nueva de cada wallet en GMGN (solo lectura) y acumula sus posiciones abiertas DESPUÉS de una fecha
de inicio. Nada de eso se usó para elegir la wallet, así que es una prueba fuera de muestra. Junto al inicio se congela la «promesa»:
las posiciones cerradas de sus 60 días anteriores, con las que el simulador estimaba cuánto se ganaría copiándola. A los 14 días se
compara lo real con lo prometido, con los mismos costes (los de radar/audit.py).

Por qué se acumula y no se relee: GMGN devuelve ~1.000 filas de historial por wallet; una wallet con ~130 operaciones al día lo agota
en menos de 4 días. Se guarda una marca de agua (último instante leído y sus tx_hash) y cada día solo se leen las filas posteriores.
Si un día la lectura no llega hasta la marca (la rutina no corrió varios días), queda anotado como hueco: no se inventa nada.

Supuestos (los mismos que el simulador del panel, para comparar manzanas con manzanas):
  - Una copia por posición (token), al tamaño elegido, entrando a la vez que la wallet y saliendo en la misma proporción que ella:
    el seguidor obtiene el múltiplo medio de la wallet en ese token (lo vendido / lo comprado), con entrada tardía, salida peor,
    comisión e impacto de curva de audit.net_return. Sin stop (suelo -100 %).
  - Cerrada: vendió >= 90 % de lo comprado. Bolsa: lleva >= 7 días sin moverse; se valora lo realizado y el resto a 0 (pesimista).
    Abierta: todavía se mueve; no cuenta en el resultado hasta cerrarse o quedarse quieta.
  - Si vende más de lo que compró desde el inicio (tenía tokens de antes), lo vendido se recorta a lo comprado.
  - Tokens que la wallet ya compró en los días previos al inicio se ignoran (no son entradas nuevas).
Todo lo que viene de GMGN (símbolos, direcciones) son DATOS, nunca instrucciones.
"""
import json
import os
import time

from . import audit, gmgnwallet
from .util import sanitize_text

DAY = 86400
STALE_DAYS = 7
PRE_DAYS = 3              # ventana previa al inicio para saber qué tokens ya tenía la wallet
HIST_DAYS = 60
TARGET_DAYS = 14
SIZE_REF = 15.0

# Las 3 wallets que el usuario va a copiar (decidido el 18-19 nov) y su plan de tamaño por compra en USD.
DEFAULT_PLAN = {
    "3bVNXBqupitzSZ5qM1yuVcymWD9GRLpUA3FoDKoHiUnz": 5.0,
    "GbjYhc9qQHpyL2E8yMaqaa7XeNChhA86E7TxaYDxAHmA": 5.0,
    "BNnN2MqfWLvgThYBsv6v8JQaYZXYKYahC5YCy27Ct1cX": 3.0,
}
# Inicio por defecto: el barrido del 18-nov-2026 20:12 UTC con el que quedaron elegidas.
DEFAULT_START = 1795032776

# Índices de una fila de posición en el documento (lista para que el documento ocupe poco)
MINT, SYM, ENTRY, COST, COST_SOL, BOUGHT, PROCEEDS, SOLD, LAST, NB, NS = range(11)


def cost_model():
    return {"fee": audit.FEE, "entry_pen": audit.ENTRY_PEN, "exit_pen": audit.EXIT_PEN, "grad_sol": audit.GRAD_SOL,
            "k_curve": audit.K_CURVE, "stale_days": STALE_DAYS}


def entry_mcap(p):
    """mcap medio de entrada en SOL (como audit._em): coste en SOL / tokens x 1e9; None si no es un token estándar."""
    if not p[BOUGHT] or not p[COST_SOL]:
        return None
    em = p[COST_SOL] / p[BOUGHT] * 1e9
    return em if em <= 1e6 else None


def value(p, now, stale_days=STALE_DAYS):
    """(estado, múltiplo) de una posición: 'closed' | 'stale' | 'open'. El múltiplo de una abierta es lo realizado hasta ahora."""
    if not p[COST] or p[COST] <= 0 or not p[BOUGHT] or p[BOUGHT] <= 0:
        return None, None
    f = min(1.0, p[BOUGHT] / p[SOLD]) if p[SOLD] > 0 else 1.0
    mult = (p[PROCEEDS] * f) / p[COST]
    if p[SOLD] >= 0.9 * p[BOUGHT]:
        return "closed", mult
    if now - p[LAST] >= stale_days * DAY:
        return "stale", mult
    return "open", mult


def net(mult, em, size_usd, sol_usd, extra=0.0):
    """Neto de la copia con los costes de audit.net_return, menos un coste extra por vuelta (p. ej. 0,05 = 5 %). Suelo -100 %."""
    return max(audit.net_return(mult, em, size_usd, sol_usd) - extra, -1.0)


# ---------- acumulación ----------

def _row_fields(r):
    ev = r.get("event_type") or r.get("type")
    if ev not in ("buy", "sell"):
        return None
    mint = (r.get("token") or {}).get("address")
    try:
        usd = float(r.get("cost_usd") or 0)
        amt = float(r.get("token_amount") or 0)
    except (TypeError, ValueError):
        return None
    if not mint or usd <= 0 or amt <= 0 or not r.get("timestamp"):
        return None
    return ev, mint, int(r["timestamp"]), usd, amt, sanitize_text((r.get("token") or {}).get("symbol"), 24), r.get("tx_hash") or ""


def new_doc(addr, start_ts):
    return {"addr": addr, "start_ts": int(start_ts), "wm_ts": int(start_ts - PRE_DAYS * DAY), "wm_tx": [], "pre": [], "pos": [], "gaps": []}


def merge(doc, rows, sol_usd, now):
    """Añade al documento las filas de actividad posteriores a su marca de agua. Devuelve (documento, nº filas nuevas usadas)."""
    start, wm, seen = doc["start_ts"], doc["wm_ts"], set(doc.get("wm_tx") or [])
    pre = set(doc.get("pre") or [])
    pos = {p[MINT]: p for p in doc.get("pos") or []}
    parsed = []
    for r in rows:
        f = _row_fields(r)
        if not f:
            continue
        ev, mint, ts, usd, amt, sym, tx = f
        if ts < wm or (ts == wm and tx and tx in seen):
            continue
        parsed.append(f)
    parsed.sort(key=lambda x: (x[2], x[6]))
    used = 0
    for ev, mint, ts, usd, amt, sym, tx in parsed:
        if ts < start:                       # ventana previa: solo sirve para saber qué tenía ya
            if ev == "buy":
                pre.add(mint)
            continue
        if mint in pre:
            continue
        p = pos.get(mint)
        if p is None:
            if ev != "buy":                  # venta de un token comprado antes de la ventana: no es una entrada nueva
                continue
            p = [mint, sym, ts, 0.0, 0.0, 0.0, 0.0, 0.0, ts, 0, 0]
            pos[mint] = p
        if ev == "buy":
            p[COST] += usd
            p[COST_SOL] += usd / sol_usd
            p[BOUGHT] += amt
            p[NB] += 1
        else:
            p[PROCEEDS] += usd
            p[SOLD] += amt
            p[NS] += 1
        p[LAST] = max(p[LAST], ts)
        used += 1
    if parsed:
        mx = max(x[2] for x in parsed)
        if mx > wm:
            doc["wm_ts"], doc["wm_tx"] = mx, sorted({x[6] for x in parsed if x[2] == mx and x[6]})
        else:
            doc["wm_tx"] = sorted(seen | {x[6] for x in parsed if x[2] == wm and x[6]})
    doc["pre"] = sorted(pre)
    doc["pos"] = sorted(pos.values(), key=lambda p: p[ENTRY])
    for p in doc["pos"]:
        p[COST], p[COST_SOL], p[BOUGHT], p[PROCEEDS], p[SOLD] = (round(p[COST], 4), round(p[COST_SOL], 6), round(p[BOUGHT], 3),
                                                                 round(p[PROCEEDS], 4), round(p[SOLD], 3))
    doc["updated_ts"] = int(now)
    return doc, used


def update_wallet(g, doc, sol_usd, now, max_pages=25):
    """Lee de GMGN la actividad desde la marca de agua del documento y la acumula. Anota un hueco si GMGN no llega hasta la marca."""
    since = doc["wm_ts"]
    days = max((now - since) / DAY, 0.0) + 1e-6
    rows, meta = gmgnwallet.fetch_activity(g, doc["addr"], days=days, max_pages=max_pages, now=now)
    ts = [r.get("timestamp") for r in rows if r.get("timestamp")]
    if rows and not meta.get("reached_start") and min(ts) > since:
        if min(ts) > doc["start_ts"] and since < min(ts):
            # faltan filas DESPUÉS del inicio: pueden faltar posiciones o movimientos. Se anota; no se inventa nada.
            doc.setdefault("gaps", []).append([int(max(since, doc["start_ts"])), int(min(ts))])
        else:
            # solo falta parte de la ventana previa: afecta a saber qué tokens ya tenía antes (el recorte de ventas lo mitiga)
            doc["pre_from"] = int(min(ts))
    doc, used = merge(doc, rows, sol_usd, now)
    doc["fetch"] = {"rows": len(rows), "used": used, "pages": meta.get("pages"), "reached": bool(meta.get("reached_start"))}
    return doc


# ---------- promesa congelada ----------

def promise_from_wallet_doc(wdoc, start_ts, hist_days=HIST_DAYS):
    """Posiciones cerradas de la wallet en los `hist_days` días anteriores al inicio, como las usa el simulador: [[ts, múltiplo, mcap_sol]]."""
    rows = [[int(p[0]), round(float(p[2]), 4), (None if len(p) < 5 or p[4] is None else round(float(p[4]), 1))]
            for p in (wdoc or {}).get("pos") or [] if p and p[2] is not None and start_ts - hist_days * DAY <= p[0] < start_ts]
    rows.sort(key=lambda r: r[0])
    m = (wdoc or {}).get("m") or {}
    return {"start_ts": int(start_ts), "hist": rows, "hist_days": hist_days,
            "hist_span": round(min(hist_days, float(m.get("span_days") or hist_days)), 1),
            "per_day14": round(sum(1 for r in rows if r[0] >= start_ts - 14 * DAY) / 14.0, 2),
            "complete": m.get("complete")}


# ---------- resumen (misma lógica que el bloque LIVE del panel; prueba de paridad en tests/test_live.py) ----------

def _stats(nets):
    n = len(nets)
    return {"n": n, "mean": (sum(nets) / n) if n else None, "win": (sum(1 for x in nets if x > 0) / n) if n else None}


def summarize(meta, docs, now, sizes, extra=0.0):
    """Resumen por wallet: real (cerradas; cerradas + bolsas) frente a lo prometido, en USD al tamaño de `sizes[addr]`."""
    sol = meta.get("sol_usd") or audit.SOL_USD
    out = {}
    for addr, w in (meta.get("wallets") or {}).items():
        size = sizes.get(addr, SIZE_REF)
        doc = docs.get(addr) or {}
        closed, both, n_open, open_cost = [], [], 0, 0.0
        for p in doc.get("pos") or []:
            st, mult = value(p, now, meta.get("stale_days", STALE_DAYS))
            if st is None:
                continue
            if st == "open":
                n_open += 1
                open_cost += size
                continue
            x = net(mult, entry_mcap(p), size, sol, extra)
            both.append(x)
            if st == "closed":
                closed.append(x)
        prom = [net(r[1], r[2], size, sol, extra) for r in w.get("hist") or []]
        pc, pb, pp = _stats(closed), _stats(both), _stats(prom)
        days = max(0.0, (now - w["start_ts"]) / DAY)
        out[addr] = {"days": days, "opened": len(doc.get("pos") or []), "open": n_open, "open_usd": open_cost,
                     "closed": pc, "with_bags": pb, "promise": pp,
                     "real_usd": sum(both) * size, "promise_usd": (pp["mean"] * pb["n"] * size) if pp["mean"] is not None else None,
                     "per_day": (len(doc.get("pos") or []) / days) if days > 0 else None, "promise_per_day": w.get("per_day14"),
                     "gaps": len(doc.get("gaps") or [])}
    return out


# ---------- orquestación ----------

def load_dir(folder):
    """Documentos exportados con ArtifactData (out_dir): {'live': {addr: doc}, 'meta': doc|None, 'wallets': {addr: doc}}."""
    def read(fp):
        d = json.load(open(fp, encoding="utf-8"))
        # ArtifactData guarda el documento tal cual; se acepta también un envoltorio {id, data, version}
        return d["data"] if isinstance(d, dict) and "data" in d and set(d) <= {"id", "data", "version", "path"} else d
    out = {"live": {}, "meta": None, "wallets": {}}
    for sub in ("live", "wallets"):
        base = os.path.join(folder, sub)
        if os.path.isdir(base):
            for f in os.listdir(base):
                if f.endswith(".json"):
                    try:
                        out[sub][f[:-5]] = read(os.path.join(base, f))
                    except Exception:
                        continue
    fp = os.path.join(folder, "meta", "live.json")
    if os.path.exists(fp):
        out["meta"] = read(fp)
    return out


def run(g, prev, sol_usd, now=None, plan=None, start_ts=None, log=print):
    """Actualiza los documentos `live/<addr>` y `meta/live`. prev: salida de load_dir (estado actual del panel + wallets)."""
    now = now or time.time()
    meta = dict(prev.get("meta") or {})
    wallets = dict(meta.get("wallets") or {})
    plan = dict(plan or meta.get("plan") or DEFAULT_PLAN)
    docs = {}
    for addr in plan:
        if addr not in wallets:     # wallet nueva en el seguimiento: su promesa se congela ahora y no se toca nunca más
            st = int(start_ts if start_ts is not None else now)
            wallets[addr] = dict(promise_from_wallet_doc(prev["wallets"].get(addr), st), label=addr[:8])
            if not wallets[addr]["hist"]:
                log(f"{addr[:8]}… sin historial en el panel: no hay promesa con la que comparar")
        doc = prev["live"].get(addr) or new_doc(addr, wallets[addr]["start_ts"])
        try:
            doc = update_wallet(g, doc, sol_usd, now)
        except Exception as e:      # se conserva el documento anterior; el error se cuenta, no se oculta
            log(f"{addr[:8]}… error al leer GMGN: {str(e)[:80]}")
            doc.setdefault("errors", []).append([int(now), str(e)[:120]])
            doc["errors"] = doc["errors"][-5:]
        docs[addr] = doc
        f = doc.get("fetch") or {}
        log(f"{addr[:8]}… filas leídas {f.get('rows')} · nuevas usadas {f.get('used')} · posiciones desde el inicio {len(doc['pos'])}"
            + (f" · ⚠ {len(doc['gaps'])} hueco(s) sin datos" if doc.get("gaps") else ""))
    meta.update({"ts": int(now), "sol_usd": sol_usd, "plan": plan, "wallets": wallets, "size_ref": SIZE_REF, "target_days": TARGET_DAYS,
                 "stale_days": STALE_DAYS, "cost": cost_model()})
    return meta, docs


def write_batches(meta, docs, versions, folder):
    """Un archivo JSON por documento y batches.json para ArtifactData (action batch). versions: {'live/<addr>': v, 'meta/live': v}."""
    os.makedirs(folder, exist_ok=True)
    writes = []
    for addr, doc in docs.items():
        fp = os.path.join(folder, f"live_{addr}.json")
        json.dump(doc, open(fp, "w", encoding="utf-8"))
        w = {"op": "set", "collection": "live", "doc_id": addr, "file_path": fp}
        if versions.get(f"live/{addr}"):
            w["if_version"] = versions[f"live/{addr}"]
        writes.append(w)
    fp = os.path.join(folder, "meta_live.json")
    json.dump(meta, open(fp, "w", encoding="utf-8"))
    w = {"op": "set", "collection": "meta", "doc_id": "live", "file_path": fp}
    if versions.get("meta/live"):
        w["if_version"] = versions["meta/live"]
    writes.append(w)
    json.dump([writes], open(os.path.join(folder, "batches.json"), "w", encoding="utf-8"))
    return writes


# ---------- tamaño y riesgo del plan (misma lógica que liveRisk del panel; paridad en tests/test_live.py) ----------

def risk(wallet_rows, sizes, sol_usd, ref, capital=300.0, max_open=0, extra=0.0, days=60):
    """Simula copiar las posiciones cerradas de los últimos `days` días de cada wallet con su tamaño, un capital y un máximo de
    posiciones abiertas a la vez (0 = sin límite). Si no queda dinero libre o se llega al máximo, la entrada se salta.
    wallet_rows: {addr: [[entrada, tenencia_s, múltiplo, coste_sol, mcap_sol], ...]} (filas `pos` de los documentos de wallet).
    Es una cota OPTIMISTA: son los mismos datos con los que se eligieron y solo hay posiciones cerradas (sin bolsas)."""
    per, ev = {}, []
    for addr in sorted(wallet_rows):
        size = sizes[addr]
        rs = sorted([r for r in wallet_rows[addr] if r and r[2] is not None and ref - days * DAY <= r[0] <= ref], key=lambda r: (r[0], r[2]))
        nets = [net(r[2], r[4] if len(r) > 4 else None, size, sol_usd, extra) for r in rs]
        usd = [x * size for x in nets]
        span = max(1.0, (ref - rs[0][0]) / DAY) if rs else None
        gains = sorted((u for u in usd if u > 0), reverse=True)
        streak = cur = 0
        for x in nets:
            cur = cur + 1 if x < 0 else 0
            streak = max(streak, cur)
        srt = sorted(usd, reverse=True)
        n = len(rs)
        per[addr] = {"n": n, "span": span, "per_month": (n / span * 30) if span else None,
                     "turnover_month": (n / span * 30 * size) if span else None, "pnl": sum(usd),
                     "pnl_month": (sum(usd) / span * 30) if span else None, "pnl_ex3": sum(srt[3:]) if n > 3 else None,
                     "top3_share": (sum(gains[:3]) / sum(gains)) if gains else None, "streak": streak}
        for r, x in zip(rs, nets):
            ev.append((r[0], r[0] + (r[1] or 0), x, addr))
    ev.sort(key=lambda e: (e[0], e[1], e[3], e[2]))
    cash, opened, realized = float(capital), [], []
    taken = skipped = max_conc = 0
    locked = max_locked = 0.0
    conc = []

    def release(upto):
        nonlocal cash, locked
        keep = []
        for o in opened:
            if o[0] <= upto:
                cash += o[1] * (1 + o[2])
                locked -= o[1]
                realized.append((o[0], o[3], o[4], o[1] * o[2]))
            else:
                keep.append(o)
        opened[:] = keep

    for ts, te, x, addr in ev:
        release(ts)
        size = sizes[addr]
        if cash < size - 1e-9 or (max_open and len(opened) >= max_open):
            skipped += 1
            continue
        cash -= size
        locked += size
        opened.append((te, size, x, ts, addr))
        taken += 1
        max_conc = max(max_conc, len(opened))
        max_locked = max(max_locked, locked)
        conc.append(len(opened))
    release(float("inf"))
    realized.sort()
    eq = peak = min_eq = float(capital)
    dd = 0.0
    for _, _, _, pnl in realized:
        eq += pnl
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
        min_eq = min(min_eq, eq)
    conc.sort()
    spans = [p["span"] for p in per.values() if p["span"]]
    return {"per": per, "taken": taken, "skipped": skipped, "pnl": eq - capital, "max_dd": dd, "min_eq": min_eq,
            "max_conc": max_conc, "med_conc": (conc[len(conc) // 2] if conc else None), "max_locked": max_locked,
            "days": max(spans) if spans else None,
            "turnover_month": sum(p["turnover_month"] or 0 for p in per.values()),
            "pnl_month": sum(p["pnl_month"] or 0 for p in per.values())}
