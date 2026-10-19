"""Historial de 60 días de una wallet desde la cadena, por posiciones, para el panel de copia (HIPOTESIS_v7.md).

Posición = todas las compras y ventas de una wallet en un mismo token. Se cuenta como CERRADA si vendió al menos el 90 %
de lo que compró; las abiertas o parciales NO entran en la ganancia (se cuentan aparte: un «bag» perdedor sin vender no
resta, y eso infla el resultado de quien no vende sus pérdidas).

Tenencia ponderada = hora media de las ventas (ponderada por lo cobrado) - hora media de las compras (ponderada por lo
gastado). Mide cuánto aguanta de verdad, y no se engaña con una venta pequeña al principio.

Formato SIN VERIFICAR a gran escala: la deducción de compras y ventas viene de wallet_history.derive_trade, probada con datos
reales de Helius; rutas complejas (varios tokens en una transacción) se ignoran y se cuentan.
"""
import time
from collections import defaultdict

from . import wallet_history
from .util import http_json, median

DAY = 86400


def fetch_history(h, wallet, days=60, max_pages=40, now=None, log=None):
    """Páginas de transacciones enriquecidas hacia atrás hasta `days` días. Devuelve (txs, meta)."""
    now = now or time.time()
    limit_ts = now - days * DAY
    txs, before, pages, reached = [], None, 0, False
    while pages < max_pages:
        url = f"{h.api}/v0/addresses/{wallet}/transactions?api-key={h.key}&limit=100" + (f"&before={before}" if before else "")
        h._count("wallet_calls")
        page = http_json(url, limiter=h.limiter, retries=3)
        pages += 1
        if not page:
            reached = True
            break
        txs.extend(page)
        before = page[-1].get("signature")
        if (page[-1].get("timestamp") or 0) <= limit_ts or len(page) < 100:
            reached = True
            break
    txs = [t for t in txs if (t.get("timestamp") or 0) >= limit_ts]
    return txs, {"pages": pages, "reached_start": reached, "txs": len(txs)}


def positions_from_txs(wallet, txs):
    """Posiciones por token con sus compras y ventas. Devuelve (posiciones, n_operaciones, n_ignoradas)."""
    by = defaultdict(lambda: {"buys": [], "sells": []})
    n, ignored = 0, 0
    for t in sorted(txs, key=lambda t: t.get("timestamp") or 0):
        tr = wallet_history.derive_trade(wallet, t)
        if tr is None:
            if t.get("type") in ("SWAP", "UNKNOWN") and (t.get("tokenTransfers") or []) and not t.get("transactionError"):
                ignored += 1
            continue
        side, mint, sol, tokens = tr
        by[mint]["buys" if side == "buy" else "sells"].append((t["timestamp"], sol, tokens))
        n += 1
    out = []
    for mint, d in by.items():
        if not d["buys"]:
            continue
        cost = sum(s for _, s, _ in d["buys"])
        bought = sum(k for _, _, k in d["buys"])
        proceeds = sum(s for _, s, _ in d["sells"])
        sold = sum(k for _, _, k in d["sells"])
        closed = bought > 0 and sold >= 0.9 * bought
        if d["sells"] and proceeds > 0:
            t_in = sum(ts * s for ts, s, _ in d["buys"]) / cost
            t_out = sum(ts * s for ts, s, _ in d["sells"]) / proceeds
            hold = max(0.0, t_out - t_in)
        else:
            hold = None
        out.append({"mint": mint, "closed": closed, "cost": cost, "proceeds": proceeds, "bought": bought, "sold": sold,
                    "entry_ts": min(ts for ts, _, _ in d["buys"]), "exit_ts": max((ts for ts, _, _ in d["sells"]), default=None),
                    "hold": hold, "mult": (proceeds / cost) if (closed and cost > 0) else None})
    return out, n, ignored


def metrics(wallet, positions, n_ops, ignored, span_days, cfg):
    closed = [p for p in positions if p["closed"] and p["mult"] is not None]
    cost = sum(p["cost"] for p in closed)
    pnl = sum(p["proceeds"] - p["cost"] for p in closed)
    per = sorted((p["proceeds"] - p["cost"] for p in closed), reverse=True)
    holds = [p["hold"] for p in closed if p["hold"] is not None]
    mults = sorted((p["mult"] for p in closed), reverse=True)
    f = cfg["copy"]
    return {
        "wallet": wallet, "n_closed": len(closed), "n_open": sum(1 for p in positions if not p["closed"]),
        "cost_sol": round(cost, 3), "pnl_sol": round(pnl, 3), "roi": (pnl / cost) if cost > 0 else None,
        "pnl_ex_top2": round(sum(per[2:]), 3) if len(per) > 2 else None,
        "win_rate": (sum(1 for p in closed if p["proceeds"] > p["cost"]) / len(closed)) if closed else None,
        "median_hold_s": median(holds), "short_hold_share": (sum(1 for x in holds if x < f["short_hold_s"]) / len(holds)) if holds else None,
        "best_mult": mults[0] if mults else None, "median_mult": median(mults) if mults else None,
        "hits10": sum(1 for x in mults if x >= f["hit_mult"]),  # operaciones de +1000 % o más
        # última actividad real de la wallet, incluidas las posiciones aún abiertas (una compra sin vender también cuenta)
        "last_ts": max([p["entry_ts"] for p in positions] + [p["exit_ts"] for p in positions if p.get("exit_ts")], default=None),
        # operaciones cerradas en los últimos `recent_days` días (historial reciente): exige que la racha siga viva
        "closed_recent": sum(1 for p in closed if (p.get("exit_ts") or p["entry_ts"]) >= time.time() - f["recent_days"] * DAY),
        "ops_per_day": n_ops / max(span_days, 1e-9), "ignored_txs": ignored, "span_days": round(span_days, 1),
        "bot": (n_ops / max(span_days, 0.05)) > cfg["history"]["bot_trades_per_day"],
    }


def passes(m, cfg, flt=None):
    """Filtros del usuario (editables en el panel). Devuelve (cumple, motivos_que_fallan).
    «Retornos brutales» = operaciones sueltas de +1000 % o más (x11). El retorno global sobre lo invertido de las mejores
    wallets reales es de decenas de %, así que no puede exigirse +1000 % al total."""
    f = dict(cfg["copy"])
    f.update(flt or {})
    why = []
    if m["bot"]:
        why.append("bot (demasiadas operaciones por día)")
    if m["span_days"] < f.get("min_span_days", 0) - 0.5:
        why.append("historial de solo %.0f días (< %d)" % (m["span_days"], f["min_span_days"]))
    if m.get("last_ts") and f.get("max_idle_days") and (time.time() - m["last_ts"]) / DAY > f["max_idle_days"]:
        why.append("sin operar desde hace %.0f días (> %d)" % ((time.time() - m["last_ts"]) / DAY, f["max_idle_days"]))
    if m.get("closed_recent") is not None and m["closed_recent"] < f.get("min_recent_closed", 0):
        why.append("solo %d operaciones cerradas en los últimos %d días (< %d)" % (m["closed_recent"], f["recent_days"], f["min_recent_closed"]))
    if m["n_closed"] < f["min_closed"]:
        why.append("pocas operaciones cerradas (%d < %d)" % (m["n_closed"], f["min_closed"]))
    if m["hits10"] < f["min_hits10"]:
        why.append("operaciones de +1000 %%: %d < %d" % (m["hits10"], f["min_hits10"]))
    if m["median_hold_s"] is None or m["median_hold_s"] < f["min_hold_s"]:
        why.append("tenencia mediana %s < %d min" % ("—" if m["median_hold_s"] is None else "%.0f min" % (m["median_hold_s"] / 60), f["min_hold_s"] // 60))
    if m["short_hold_share"] is not None and m["short_hold_share"] > f["max_short_share"]:
        why.append("%.0f%% de salidas en menos de %d min" % (m["short_hold_share"] * 100, f["short_hold_s"] // 60))
    if m["roi"] is not None and m["roi"] > 0 and m["roi"] < f.get("min_roi", 0):
        why.append("rentabilidad %.0f %% < %.0f %%" % (m["roi"] * 100, f["min_roi"] * 100))
    if m["roi"] is None or m["roi"] <= 0 or m["pnl_ex_top2"] is None or m["pnl_ex_top2"] <= 0:
        why.append("no es rentable si se quitan sus 2 mejores operaciones (vive de suerte)")
    return (not why), why


def analyze(h, wallet, cfg, days=60, max_pages=40, now=None):
    now = now or time.time()
    txs, meta = fetch_history(h, wallet, days, max_pages, now)
    pos, n_ops, ign = positions_from_txs(wallet, txs)
    span = (now - min((t.get("timestamp") or now) for t in txs)) / DAY if txs else 0.0
    if not meta["reached_start"]:
        span = (max(t["timestamp"] for t in txs) - min(t["timestamp"] for t in txs)) / DAY if txs else 0.0  # solo se vio un tramo
    m = metrics(wallet, pos, n_ops, ign, min(span, days) if span else 0.0, cfg)
    m["coverage"] = meta
    return m, pos
