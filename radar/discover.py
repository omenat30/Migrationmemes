"""Descubrimiento de wallets candidatas desde tokens de pump.fun que YA migraron (HIPOTESIS_v7.md).

Para cada token migrado se leen sus operaciones en la curva (API de pump.fun, sin gastar Helius) y se calcula, por wallet,
lo que gastó, lo que cobró y cuánto tardó. Una wallet es candidata si en al menos `min_tokens` tokens distintos salió con
ganancia (múltiplo >= `min_mult` sobre lo gastado, cobrando >= `min_proceeds` SOL) y aguantó >= `min_hold_s`. Eso solo
mira la fase de curva: el historial completo de 30/60 días se verifica después con deepwallet.
"""
from collections import defaultdict


def wallet_results(trades):
    """trades de un token -> {wallet: {cost, proceeds, hold, entry}} (solo wallets que compraron y vendieron)."""
    by = defaultdict(lambda: {"b": [], "s": []})
    for t in trades:
        if t.get("wallet"):
            by[t["wallet"]]["b" if t["is_buy"] else "s"].append((t["ts"], t["sol"]))
    out = {}
    for w, d in by.items():
        if not d["b"] or not d["s"]:
            continue
        cost = sum(x for _, x in d["b"])
        proceeds = sum(x for _, x in d["s"])
        if cost <= 0 or proceeds <= 0:
            continue
        t_in = sum(ts * x for ts, x in d["b"]) / cost
        t_out = sum(ts * x for ts, x in d["s"]) / proceeds
        out[w] = {"cost": cost, "proceeds": proceeds, "hold": max(0.0, t_out - t_in), "entry": min(ts for ts, _ in d["b"])}
    return out


def pick_candidates(per_token, min_tokens=2, min_mult=2.0, min_proceeds=1.0, min_hold_s=600):
    """per_token: {mint: wallet_results}. Devuelve [(wallet, [(mint, mult, hold)...])] ordenado por nº de tokens."""
    wins = defaultdict(list)
    for mint, res in per_token.items():
        for w, r in res.items():
            mult = r["proceeds"] / r["cost"]
            if mult >= min_mult and r["proceeds"] >= min_proceeds and r["hold"] >= min_hold_s:
                wins[w].append((mint, mult, r["hold"]))
    cands = [(w, v) for w, v in wins.items() if len(v) >= min_tokens]
    cands.sort(key=lambda x: (-len(x[1]), -max(m for _, m, _ in x[1])))
    return cands
