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


# ---------- clasificación por market cap de entrada (20-oct-2026)
# DexScreener da ahora al pool de PumpSwap la fecha de CREACIÓN del token, no la de migración: las horas de migración de arriba
# salen mal en muchos tokens. En pump.fun la migración ocurre a un mcap casi fijo (curva estándar: ~383 SOL al completarse,
# medido con las reservas virtuales de 50 tokens completos), así que la franja se puede medir con el precio medio de entrada.
GRAD_SOL = 383.0
SUPPLY = 1e9
BANDS = (("temprana", 0.0, 0.35), ("media", 0.35, 0.6), ("a_punto", 0.6, 1.0), ("recien", 1.0, 3.0), ("tarde", 3.0, float("inf")))


def entry_mcap_sol(pos):
    """mcap medio de entrada en SOL (coste / tokens comprados x supply), o None. Con historial de GMGN el coste es USD / SOL actual."""
    if not pos.get("bought") or not pos.get("cost"):
        return None
    return pos["cost"] / pos["bought"] * SUPPLY


def exit_mcap_sol(pos):
    if not pos.get("sold") or not pos.get("proceeds"):
        return None
    return pos["proceeds"] / pos["sold"] * SUPPLY


def band(mcap_sol, grad=GRAD_SOL):
    if mcap_sol is None or mcap_sol > 1e6:  # supply distinta de 1.000 M: no es un token estándar de pump.fun
        return None
    for k, a, b in BANDS:
        if a * grad <= mcap_sol < b * grad:
            return k


def summarize_mcap(positions, net_fn=None, grad=GRAD_SOL):
    """Por franja de mcap de entrada: n, roi, win, hold (min) y, si se pasa net_fn(pos) -> retorno copiando, er (en R de un stop del 60 %).
    Además: pre (entra en la curva), post (entra ya migrado), cross (entra en la curva y vende de media por encima de la graduación) y
    near (a punto de migrar + recién migrado)."""
    rows = []
    for p in positions:
        if not p.get("closed") or p.get("mult") is None:
            continue
        b = band(entry_mcap_sol(p), grad)
        if b is None:
            continue
        xm = exit_mcap_sol(p)
        rows.append((b, p, xm is not None and xm >= grad))

    def agg(ps):
        if not ps:
            return None
        cost = sum(p["cost"] for p in ps)
        d = {"n": len(ps), "roi": round(sum(p["cost"] * (p["mult"] - 1) for p in ps) / cost, 3) if cost else None,
             "win": round(sum(1 for p in ps if p["mult"] > 1) / len(ps), 3),
             "hold": round(statistics.median((p.get("hold") or 0) for p in ps) / 60, 1)}
        if net_fn:
            d["er"] = round(sum(net_fn(p) for p in ps) / len(ps) / 0.6, 3)
        return d
    out = {k: agg([p for b, p, _ in rows if b == k]) for k, _, _ in BANDS}
    out["pre"] = agg([p for b, p, _ in rows if b in ("temprana", "media", "a_punto")])
    out["post"] = agg([p for b, p, _ in rows if b in ("recien", "tarde")])
    out["cross"] = agg([p for b, p, x in rows if b in ("temprana", "media", "a_punto") and x])
    out["near"] = agg([p for b, p, _ in rows if b in ("a_punto", "recien")])
    return out
