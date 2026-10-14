"""Estudio A (HIPOTESIS_v5.md): entrar DESPUÉS de migrar, 100 USD, stop -60 %, objetivo x3.

Entrada a D segundos de la migración (D en 30/60/120/300). Salidas: R1 = vender si llega a x3, si no mantener 2 h;
R2 = mantener 1 h. El stop del -60 % siempre activo, con tiempo de reacción manual. Una operación sin resolver (los datos
aún no cubren la salida) se EXCLUYE y se cuenta aparte.

SESGO: si los tokens vienen del listado de pump.fun (backfill), favorecen a los que siguen activos tras migrar. El resultado
es una COTA SUPERIOR, no una estimación.
"""
from . import costs, stats
from .util import median

DELAYS = (30, 60, 120, 300)


def _sample(p, liq):
    return {"price": p["price"], "vsol": None, "vtok": None, "liq": p.get("liq") or liq, "complete": True,
            "sol_usd": p.get("sol_usd"), "ts": p["ts"]}


def simulate_post(token, path, delay, rule, cfg, now):
    c = cfg["costs"]
    mig = token["completed_ts"]
    amm = [p for p in path if p["phase"] == "amm" and p["ts"] >= mig]
    fill = next((p for p in amm if p["ts"] >= mig + delay), None)
    if fill is None:
        return None
    hold = 7200 if rule == "R1" else 3600
    after = [p for p in amm if p["ts"] > fill["ts"]]
    floor = fill["price"] * (1 - c["stop_loss_pct"] / 100)
    target = fill["price"] * 3.0
    liq = fill.get("liq")
    entry = _sample(fill, liq)
    peak = max([p["price"] for p in after if p["ts"] <= fill["ts"] + hold] or [fill["price"]]) / fill["price"]
    exit_p, reason = None, None
    for i, p in enumerate(after):
        if p["ts"] > fill["ts"] + hold:
            exit_p, reason = after[i - 1] if i else fill, "tiempo"
            break
        if p["price"] <= floor:
            exit_p = next((q for q in after[i:] if q["ts"] >= p["ts"] + c["stop_reaction_s"]), p)
            reason = "stop"
            break
        if rule == "R1" and p["price"] >= target:
            exit_p = next((q for q in after[i:] if q["ts"] >= p["ts"] + c["stop_reaction_s"]), p)
            reason = "x3"
            break
    if exit_p is None:
        if after and after[-1]["ts"] >= fill["ts"] + hold - 60:
            exit_p, reason = after[-1], "tiempo"
        else:
            return {"censored": True}  # los datos aún no llegan a la salida
    ret, rug = costs.net_return(entry, _sample(exit_p, liq), cfg)
    return {"mint": token["mint"], "ret": ret, "reason": reason, "peak": peak, "rug": rug, "hold_s": exit_p["ts"] - fill["ts"]}


def run(store, cfg, now, src=None):
    toks = [t for t in store.rec_all(src) if t.get("completed_ts")]
    paths = {t["mint"]: store.rec_path_of(t["mint"]) for t in toks}
    rep = {"generated_at": now, "src": src or "todas", "n_tokens": len(toks), "rows": [], "caveat":
           "Los tokens del backfill salen del listado de pump.fun y favorecen a los que siguen activos: cota superior, no estimación."}
    for rule in ("R1", "R2"):
        for d in DELAYS:
            res, cens = [], 0
            for t in toks:
                r = simulate_post(t, paths[t["mint"]], d, rule, cfg, now)
                if r is None:
                    continue
                if r.get("censored"):
                    cens += 1
                else:
                    res.append(r)
            rets = [r["ret"] for r in res]
            row = {"rule": rule, "delay": d, "n": len(res), "censored": cens}
            if rets:
                peaks = [r["peak"] for r in res]
                row.update({"mean": stats.mean(rets), "median": median(rets), "ci90": stats.bootstrap_ci(rets, n=1500, seed=11),
                            "usd_per_trade": stats.mean(rets) * cfg["costs"]["position_usd"],
                            "stop_pct": sum(1 for r in res if r["reason"] == "stop") / len(res) * 100,
                            "x3_pct": sum(1 for r in res if r["reason"] == "x3") / len(res) * 100,
                            "peak_ge2": sum(1 for p in peaks if p >= 2) / len(peaks) * 100,
                            "peak_ge3": sum(1 for p in peaks if p >= 3) / len(peaks) * 100,
                            "peak_ge5": sum(1 for p in peaks if p >= 5) / len(peaks) * 100,
                            "median_peak": median(peaks)})
            rep["rows"].append(row)
    return rep
