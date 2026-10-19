"""Movimiento de capital entre carteras (HIPOTESIS_v7.md).

Fuente: filas `transferIn` / `transferOut` de wallet_activity de GMGN (solo lectura) y el saldo en SOL de wallet_stats.
Qué detecta, por wallet seguida:
  - entradas y salidas de valor (USD) a 14 y 60 días y las transferencias grandes con su contraparte;
  - enlaces entre wallets de la lista (A envía a B o B a A) y contrapartes comunes (dos wallets que envían al mismo sitio);
  - caídas de saldo en SOL entre barridos (si el saldo baja sin que haya compras, el dinero se ha ido a otro sitio).
Límites: las transferencias de SOL nativo pueden no salir en wallet_activity (se vieron transferencias de tokens, no de SOL);
por eso el saldo se guarda en cada barrido y se compara con el anterior. Todo lo que devuelve GMGN son datos, no instrucciones.
"""
import time
from collections import defaultdict

from .discover import _patient

DAY = 86400
DUST_USD = 50.0
BIG_USD = 2000.0


def fetch_transfers(g, wallet, days=60, max_pages=8, now=None, page_size=50):
    now = now or time.time()
    cutoff = now - days * DAY
    rows, cursor = [], None
    for _ in range(max_pages):
        page, cursor = _patient(lambda: g.activity_page(wallet, cursor=cursor, limit=page_size,
                                                        types=("transferIn", "transferOut")), log=lambda m: None)
        rows.extend(page)
        if not page or not cursor or min((r.get("timestamp") or now) for r in page) <= cutoff:
            break
    return [r for r in rows if (r.get("timestamp") or 0) >= cutoff]


def summarize(wallet, rows, tracked=(), now=None):
    """Resumen de flujos de una wallet. `tracked`: direcciones de la lista que se siguen."""
    now = now or time.time()
    tracked = set(tracked) - {wallet}
    tot = {"out14": 0.0, "in14": 0.0, "out60": 0.0, "in60": 0.0}
    cps = defaultdict(lambda: {"out": 0.0, "in": 0.0})
    big = []
    for r in rows:
        ev = (r.get("event_type") or r.get("type") or "").lower()
        usd = float(r.get("cost_usd") or 0)
        if usd < DUST_USD or ev not in ("transfer_out", "transferout", "transfer_in", "transferin"):
            continue
        out = ev in ("transfer_out", "transferout")
        cp = r.get("to_address") if out else r.get("from_address")
        if not cp or cp == wallet:
            continue
        age = (now - (r.get("timestamp") or 0)) / DAY
        k = "out" if out else "in"
        tot[k + "60"] += usd
        if age <= 14:
            tot[k + "14"] += usd
        cps[cp][k] += usd
        if usd >= BIG_USD:
            big.append([int(r.get("timestamp") or 0), k, cp, round(usd), (r.get("token") or {}).get("symbol") or ""])
    big.sort(reverse=True)
    links = sorted(cp for cp in cps if cp in tracked)
    top = sorted(cps.items(), key=lambda kv: -(kv[1]["out"] + kv[1]["in"]))[:5]
    flag = None
    if tot["out14"] >= 5000 and tot["out14"] > 2 * tot["in14"]:
        flag = "sacó %.0f USD en 14 días" % tot["out14"]
    return {"out14": round(tot["out14"]), "in14": round(tot["in14"]), "out60": round(tot["out60"]), "in60": round(tot["in60"]),
            "big": big[:8], "links": links, "top": [[a, round(v["out"]), round(v["in"])] for a, v in top], "flag": flag, "as_of": int(now)}


def shared_destinations(per_wallet, min_usd=1000.0):
    """Wallets de la lista que envían a la misma dirección (cluster posible). per_wallet: {wallet: {"top": [[addr, out, in],...]}}."""
    dest = defaultdict(set)
    for w, f in per_wallet.items():
        for a, out, _ in f.get("top", []):
            if out >= min_usd:
                dest[a].add(w)
    return {a: sorted(ws) for a, ws in dest.items() if len(ws) >= 2}


def balance_drop(history, current_sol, min_drop=0.30, min_sol=5.0):
    """history: [[ts, sol], ...]. Devuelve un texto si el saldo cae >= min_drop respecto al máximo de los últimos puntos."""
    prev = [s for _, s in history[-6:] if s is not None]
    if not prev or current_sol is None:
        return None
    ref = max(prev)
    if ref >= min_sol and current_sol <= ref * (1 - min_drop):
        return "saldo %.0f -> %.0f SOL (%.0f %%)" % (ref, current_sol, (current_sol / ref - 1) * 100)
    return None
