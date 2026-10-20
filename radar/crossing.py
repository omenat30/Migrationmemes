"""Wallets que entran ANTES de la migración de pump.fun y salen después (HIPOTESIS_v7.md).

Para cada posición cerrada de una wallet se mira si el token migró y cuándo (hora de creación del pool en DexScreener):
  - cruce:  entró antes de migrar y terminó de vender después  (la apuesta «entro en la curva, vendo en el pool»)
  - previa: entró y salió antes de migrar (se quedó en la curva)
  - tras:   entró después de migrar
  - curva:  token sin pool de migración (no llegó o DexScreener no lo conoce)
Límite: la hora de la posición es la del primer movimiento y la del último; la migración, la creación del pool.
"""
import statistics

from .util import http_json

MARGIN = 20  # segundos de tolerancia alrededor de la migración


def migration_times(mints, limiter=None, batch=30, log=None):
    """{mint: hora_migración (s) o None}. Usa DexScreener (hasta 30 mints por llamada)."""
    out = {}
    mints = list(dict.fromkeys(mints))
    for i in range(0, len(mints), batch):
        chunk = mints[i:i + batch]
        try:
            r = http_json("https://api.dexscreener.com/tokens/v1/solana/" + ",".join(chunk), limiter=limiter)
        except Exception as e:
            if log:
                log(f"  dexscreener: {str(e)[:60]}")
            continue
        best = {}
        for p in r or []:
            base = (p.get("baseToken") or {}).get("address")
            if base in chunk and p.get("dexId") in ("pumpswap", "raydium", "meteora", "orca") and p.get("pairCreatedAt"):
                t = p["pairCreatedAt"] / 1000.0
                if base not in best or t < best[base]:
                    best[base] = t
        for m in chunk:
            out[m] = best.get(m)
    return out


def classify(pos, mig_ts):
    """pos: {entry_ts, exit_ts}; mig_ts: hora de migración o None."""
    if not mig_ts:
        return "curva"
    e, x = pos["entry_ts"], pos.get("exit_ts") or pos["entry_ts"]
    if e < mig_ts - MARGIN:
        return "cruce" if x > mig_ts + MARGIN else "previa"
    return "tras"


def summarize(positions, mig):
    """Estadística por clase para una wallet. positions: dicts con mint, entry_ts, exit_ts, mult, cost, hold."""
    groups = {}
    for p in positions:
        if p.get("mult") is None:
            continue
        groups.setdefault(classify(p, mig.get(p["mint"])), []).append(p)
    out = {}
    for k, ps in groups.items():
        cost = sum(p["cost"] for p in ps)
        out[k] = {"n": len(ps), "roi": (sum(p["cost"] * (p["mult"] - 1) for p in ps) / cost) if cost else None,
                  "win": sum(1 for p in ps if p["mult"] > 1) / len(ps), "med_mult": statistics.median(p["mult"] for p in ps),
                  "med_hold_min": statistics.median(p.get("hold") or 0 for p in ps) / 60, "best": max(p["mult"] for p in ps)}
    return out
