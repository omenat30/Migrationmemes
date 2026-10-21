"""Historial de una wallet desde GMGN (wallet_activity), como alternativa a Helius cuando se agota su cuota (HIPOTESIS_v7.md).

Mismo formato de salida que deepwallet (posiciones por token y las mismas métricas), para que los filtros sean idénticos.
Diferencias que hay que tener presentes:
  - GMGN da importes en USD (`cost_usd`), no en SOL: el coste se convierte a SOL con el precio actual del SOL; solo afecta al
    tamaño típico que muestra el panel, no a los múltiplos ni a la rentabilidad.
  - Los campos se leyeron de la documentación oficial del CLI, no de llamadas reales: se verifican con la clave de API.
  - Se ignoran las filas de transferencia (airdrops y movimientos internos), como indica la documentación.
"""
import time
from collections import defaultdict

from . import deepwallet
from .discover import _patient

DAY = 86400


def fetch_activity(g, wallet, days=60, max_pages=60, now=None, page_size=100, log=None, early_stop=None):
    """Páginas de actividad hacia atrás hasta `days` días. Devuelve (filas, meta)."""
    now = now or time.time()
    limit_ts = now - days * DAY
    rows, cursor, pages, reached = [], None, 0, False
    capped_early = False
    while pages < max_pages:
        page, cursor = _patient(lambda: g.activity_page(wallet, cursor=cursor, limit=page_size), log=lambda m: None)
        pages += 1
        rows.extend(page)
        if early_stop and len(rows) >= 200 and early_stop(rows):
            capped_early = True
            break
        if not page or not cursor:
            reached = True
            break
        if min((r.get("timestamp") or now) for r in page) <= limit_ts:
            reached = True
            break
    capped = reached and len(rows) >= 900 and min((r.get("timestamp") or now) for r in rows) > limit_ts
    rows = [r for r in rows if (r.get("timestamp") or 0) >= limit_ts]
    # GMGN solo devuelve ~1.000 filas de historial por wallet: si se agotan sin llegar al inicio de la ventana, la cobertura es parcial
    return rows, {"pages": pages, "reached_start": reached and not capped and not capped_early, "txs": len(rows), "early_stop": capped_early}


def positions_from_activity(rows, sol_usd):
    """Posiciones por token a partir de filas buy/sell. Devuelve (posiciones, n_operaciones, n_ignoradas)."""
    by = defaultdict(lambda: {"buys": [], "sells": []})
    n, ignored = 0, 0
    for r in sorted(rows, key=lambda r: r.get("timestamp") or 0):
        ev = r.get("event_type") or r.get("type")
        if ev not in ("buy", "sell"):
            if ev in ("transferIn", "transferOut"):
                ignored += 1
            continue
        mint = (r.get("token") or {}).get("address")
        try:
            usd = float(r.get("cost_usd") or 0)
            amt = float(r.get("token_amount") or 0)
        except (TypeError, ValueError):
            ignored += 1
            continue
        if not mint or usd <= 0 or amt <= 0:
            ignored += 1
            continue
        by[mint]["buys" if ev == "buy" else "sells"].append((r["timestamp"], usd, amt))
        n += 1
    out = []
    for mint, d in by.items():
        if not d["buys"]:
            continue
        cost = sum(u for _, u, _ in d["buys"])
        bought = sum(a for _, _, a in d["buys"])
        proceeds = sum(u for _, u, _ in d["sells"])
        sold = sum(a for _, _, a in d["sells"])
        closed = bought > 0 and sold >= 0.9 * bought
        if d["sells"] and proceeds > 0:
            t_in = sum(ts * u for ts, u, _ in d["buys"]) / cost
            t_out = sum(ts * u for ts, u, _ in d["sells"]) / proceeds
            hold = max(0.0, t_out - t_in)
        else:
            hold = None
        out.append({"mint": mint, "closed": closed, "cost": cost / sol_usd, "proceeds": proceeds / sol_usd,
                    "bought": bought, "sold": sold, "entry_ts": min(ts for ts, _, _ in d["buys"]),
                    "exit_ts": max((ts for ts, _, _ in d["sells"]), default=None), "hold": hold,
                    "mult": (proceeds / cost) if (closed and cost > 0) else None})
    return out, n, ignored


def sniper_like(rows, sol_usd=100.0, min_closed=15, max_median_hold_s=30.0, min_short_share=0.9, short_s=120.0):
    """¿Es evidente, con las filas vistas hasta ahora, que sale en segundos? Si sí, no merece seguir descargando (cada página son ~1 s de cuota)."""
    pos, _, _ = positions_from_activity(rows, sol_usd)
    holds = [p["hold"] for p in pos if p["closed"] and p.get("hold") is not None]
    if len(holds) < min_closed:
        return False
    holds.sort()
    return holds[len(holds) // 2] < max_median_hold_s and sum(1 for h in holds if h < short_s) / len(holds) >= min_short_share


def analyze(g, wallet, cfg, sol_usd, days=60, max_pages=60, now=None, early=True):
    now = now or time.time()
    rows, meta = fetch_activity(g, wallet, days, max_pages, now, early_stop=(lambda r: sniper_like(r, sol_usd)) if early else None)
    pos, n_ops, ign = positions_from_activity(rows, sol_usd)
    ts = [r.get("timestamp") for r in rows if r.get("timestamp")]
    span = ((now - min(ts)) / DAY if meta["reached_start"] else (max(ts) - min(ts)) / DAY) if ts else 0.0
    m = deepwallet.metrics(wallet, pos, n_ops, ign, min(span, days) if span else 0.0, cfg)
    m["coverage"] = dict(meta, source="gmgn")
    return m, pos
