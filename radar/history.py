"""Reconstrucción desde la cadena de migraciones YA OCURRIDAS (backfill).

Pre-migración: se lee el estado final de la curva y se deshacen las operaciones una a una hacia atrás; como la
variación de saldo de la curva en cada operación es exacta, las reservas (y el precio) de cada instante salen exactas.
Post-migración: se leen las operaciones del pool de PumpSwap y el precio de cada una sale de SOL/tokens movidos.

SESGO: los tokens candidatos salen del listado de pump.fun (los más recientemente operados), así que sobrerrepresentan
a los que siguen activos tras migrar. Sirve para ver cómo es una migración real y para acotar por arriba qué se puede
ganar entrando después de migrar. NO sirve para estimar cuántos tokens completan la curva: para eso hace falta el
grabador en vivo, que ve también a los que no completan.
"""
import random
import time

from . import evaluate
from .sources.curve_trades import trades_from_enhanced
from .sources.dexscreener import SOL_MINT
from .util import http_json


# Estado de una curva estándar justo al completarse. VERIFICADO: la migración real saca 85,005 SOL de la curva y la API
# de pump.fun muestra 115,005359175 SOL virtuales / 279,9 M tokens virtuales en un token completado. Tras migrar, la cuenta
# en la cadena queda a cero, así que se parte de este estado teórico.
FINAL_VSOL, FINAL_VTOK = 115.005359175, 279_900_000.0


def reconstruct_curve(h, mint, curve, sol_usd, cfg, max_txs=600):
    """Puntos [{ts, progress, price, mcap, vsol, vtok}] cronológicos del último tramo de la curva, o None."""
    final = h.curve_state(curve)
    if not final:
        return None, {"error": "sin cuenta de curva"}
    if final["complete"] or final["vtok"] <= 0:
        fvs, fvt = FINAL_VSOL, FINAL_VTOK
    elif final["standard"]:
        fvs, fvt = final["vsol"], final["vtok"]
    else:
        return None, {"error": "curva no estándar"}
    sigs = [s for s in h.curve_signatures(curve, limit=1000) if not s.get("err")][:max_txs]
    order = {s["signature"]: i for i, s in enumerate(sigs)}  # 0 = la más reciente
    trades = []
    for i in range(0, len(sigs), 100):
        txs = h.parse_transactions([s["signature"] for s in sigs[i:i + 100]])
        for t in txs:
            if t.get("signature") in order:
                t["_o"] = order[t["signature"]]
        tr, _ = trades_from_enhanced(txs, mint, curve)
        o = {t["signature"]: t["_o"] for t in txs if "_o" in t}
        for x in tr:
            x["_o"] = o.get(x["sig"], 10 ** 9)
        trades.extend(tr)
    trades.sort(key=lambda t: t["_o"])  # de la más reciente a la más antigua
    vs, vt = fvs, fvt
    pts = []
    for t in trades:
        pts.append({"ts": t["ts"], "vsol": vs, "vtok": vt})  # estado DESPUÉS de esta operación
        sign = 1 if t["is_buy"] else -1
        vs -= sign * t["sol"]
        vt += sign * t["tokens"]
        if vt <= 0 or vs < 30 - 0.5:  # inconsistencia: no seguir deshaciendo
            break
    pts.reverse()
    out = []
    for p in pts:
        rtok = p["vtok"] - 279_900_000
        prog = max(0.0, min(100.0, (1 - rtok / cfg["curve_tokens_initial"]) * 100))
        price = p["vsol"] / p["vtok"] * sol_usd
        out.append({"ts": p["ts"], "progress": prog, "price": price, "mcap": price * 1e9, "vsol": p["vsol"], "vtok": p["vtok"]})
    meta = {"trades": len(trades), "reached_start": len(sigs) < max_txs}
    return out, meta


def pool_swaps(h, pool, mint, t_from, t_to, sol_usd, max_pages=6, parse_budget=800):
    """Precio de cada operación del pool entre t_from y t_to. Devuelve (puntos, meta)."""
    sigs, before, reached = [], None, False
    for _ in range(max_pages):
        page = h.curve_signatures(pool, limit=1000, before=before)
        if not page:
            reached = True
            break
        sigs.extend(page)
        before = page[-1]["signature"]
        if page[-1].get("blockTime", 0) <= t_from or len(page) < 1000:
            reached = True
            break
    win = [s for s in sigs if not s.get("err") and t_from <= (s.get("blockTime") or 0) <= t_to]
    win.sort(key=lambda s: s["blockTime"])
    win = win[:parse_budget]  # las más tempranas primero: lo que importa es justo tras migrar
    pts = []
    for i in range(0, len(win), 100):
        for t in h.parse_transactions([s["signature"] for s in win[i:i + 100]]) or []:
            if t.get("transactionError"):
                continue
            tr = t.get("tokenTransfers") or []
            w = [float(x.get("tokenAmount") or 0) for x in tr if x.get("mint") == SOL_MINT]
            k = [float(x.get("tokenAmount") or 0) for x in tr if x.get("mint") == mint]
            if w and k and max(k) > 0 and max(w) > 0:
                price = max(w) / max(k) * sol_usd
                pts.append({"ts": t["timestamp"], "price": price, "mcap": price * 1e9})
    pts.sort(key=lambda p: p["ts"])
    return pts, {"sigs": len(sigs), "parsed": len(win), "reached_start": reached, "points": len(pts)}


def pick_recent_migrations(pump, dex_get, sol_usd, hours, n, seed=7, pages=6):
    """Migraciones recientes del listado de pump.fun (solo mints de pump.fun que cotizan en SOL), elegidas AL AZAR
    con semilla fija, sin mirar cómo les fue. dex_get(mint) -> dict con pairCreatedAt/pairAddress/liq/mcap o None."""
    seen, cands = set(), []
    for off in range(0, 50 * pages, 50):
        for c in pump.list_live(sol_usd, offset=off):
            if c["mint"] in seen or not c["mint"].endswith("pump") or not (c["complete"] or c["pool"]) or c.get("quote_decimals") != 9:
                continue
            seen.add(c["mint"])
            cands.append(c)
    rng = random.Random(seed)
    rng.shuffle(cands)
    out = []
    for c in cands:
        d = dex_get(c["mint"])
        if not d or not d.get("created"):
            continue
        age_h = (time.time() - d["created"]) / 3600
        if 0.15 <= age_h <= hours and d.get("dex") == "pumpswap":
            out.append((c, d))
        if len(out) >= n:
            break
    return out, len(cands)


def dex_pair(mint, limiter=None):
    try:
        r = http_json(f"https://api.dexscreener.com/latest/dex/tokens/{mint}", limiter=limiter)
    except Exception:
        return None
    ps = [p for p in (r.get("pairs") or []) if p.get("chainId") == "solana"]
    if not ps:
        return None
    p = max(ps, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0)
    return {"pool": p.get("pairAddress"), "dex": p.get("dexId"), "created": (p.get("pairCreatedAt") or 0) / 1000,
            "liq": (p.get("liquidity") or {}).get("usd"), "mcap": p.get("marketCap"), "price": float(p["priceUsd"]) if p.get("priceUsd") else None,
            "url": p.get("url")}
