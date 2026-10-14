"""Backtest de tu operación exacta sobre el histórico GRABADO: 100 USD por trade, stop -60 % desde tu entrada.

Reglas (fijadas antes de ver datos, ver HIPOTESIS_v4.md):
  - Una entrada por token y variante: la primera muestra de curva con avance >= `entry` y capitalización >=
    `min_mcap_usd`. La compra se ejecuta `latency_s` después, al precio de la primera muestra desde entonces
    (si el token ya migró para entonces, se compra en el pool: así se cuenta llegar tarde).
  - Los filtros usan solo características grabadas ANTES o EN el momento de la entrada (`feat_ts <= entrada`).
  - Salidas: stop -60 % (con tiempo de reacción manual), la regla de la variante y un límite de 2 h.
  - Costes: comisión por lado, deslizamiento de curva o pool, comisión de red (costs.net_return).
  - Se elige variante con la primera mitad (por hora de entrada) y se prueba SOLO esa en la segunda.
  - Una operación cuya salida aún no se puede saber (datos todavía en curso) se EXCLUYE y se cuenta aparte.
"""
import json
import os
import random

from . import costs, stats
from .util import median


def load_variants(path=None):
    path = path or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bt_variants.json")
    with open(path, encoding="utf-8") as f:
        vs = json.load(f)["variants"]
    assert len(vs) <= 12, "máximo 12 variantes"
    return vs


def _sample(p):
    """Muestra con el formato que espera costs.net_return."""
    return {"price": p["price"], "vsol": p.get("vsol"), "vtok": p.get("vtok"), "liq": p.get("liq"),
            "complete": p["phase"] == "amm", "sol_usd": p.get("sol_usd"), "ts": p["ts"]}


def passes_filters(variant, feat, entry_ts):
    """Un filtro sin dato disponible en el momento de la entrada NO deja pasar (no se asume bueno)."""
    needs = [k for k in ("top10_max", "creator_rugs_max", "buyers5_min", "wash_max") if k in variant]
    if not needs:
        return True
    if not feat or (feat.get("_ts") or 10 ** 12) > entry_ts:
        return False
    t10, rg, by, ws = feat.get("top10_pct"), feat.get("creator_rugs"), feat.get("buyers5"), feat.get("wash_share")
    if "top10_max" in variant and (t10 is None or t10 > variant["top10_max"]):
        return False
    if "creator_rugs_max" in variant and (rg is None or rg > variant["creator_rugs_max"]):
        return False
    if "buyers5_min" in variant and (by is None or by < variant["buyers5_min"]):
        return False
    if "wash_max" in variant and (ws is None or ws > variant["wash_max"]):
        return False
    return True


def simulate(token, path, variant, cfg, now, latency_s=None, entry_override=None):
    """Simula una operación. Devuelve dict de resultado, {'censored': True} o None si no hay entrada."""
    c, b = cfg["costs"], cfg["backtest"]
    lat = c["latency_s"] if latency_s is None else latency_s
    curve = [p for p in path if p["phase"] == "curve"]
    if entry_override is not None:
        sig = entry_override
    else:
        sig = next((p for p in curve if p["progress"] >= variant["entry"] and p["mcap"] >= b["min_mcap_usd"]), None)
    if sig is None:
        return None
    feat = json.loads(token["feat"]) if token.get("feat") else None
    if feat is not None:
        feat["_ts"] = token.get("feat_ts")
    if entry_override is None and not passes_filters(variant, feat, sig["ts"]):
        return None
    fill = next((p for p in path if p["ts"] >= sig["ts"] + lat), None)
    if fill is None:
        return {"censored": True, "mint": token["mint"], "entry_ts": sig["ts"]}
    entry = _sample(fill)
    floor = fill["price"] * (1 - c["stop_loss_pct"] / 100)
    limit_ts = fill["ts"] + b["max_hold_s"]
    after = [p for p in path if p["ts"] > fill["ts"]]
    comp = token.get("completed_ts")
    exit_p, reason = None, None
    for i, p in enumerate(after):
        if p["price"] <= floor:
            exit_p = next((q for q in after[i:] if q["ts"] >= p["ts"] + c["stop_reaction_s"]), p)
            reason = "stop"
            break
        if variant["exit"] == "target30" and p["price"] >= fill["price"] * (1 + b["target_pct"] / 100):
            exit_p = next((q for q in after[i:] if q["ts"] >= p["ts"] + c["stop_reaction_s"]), p)
            reason = "objetivo"
            break
        if variant["exit"] == "time30" and p["ts"] >= fill["ts"] + b["time30_s"]:
            exit_p, reason = p, "tiempo"
            break
        if p["ts"] >= limit_ts:
            exit_p, reason = p, "límite 2h"
            break
        if variant["exit"] in ("migrate", "target30") and comp and fill["phase"] == "curve" and p["phase"] == "amm" \
                and p["ts"] >= comp + b["exit_delay_s"]:
            exit_p, reason = p, "migración"
            break
        if variant["exit"] in ("migrate", "target30") and comp and fill["phase"] == "amm" and p["ts"] >= fill["ts"] + b["exit_delay_s"]:
            exit_p, reason = p, "migración"   # compró ya migrado: sale a los pocos instantes, no espera 2 h
            break
    if exit_p is None:
        last = after[-1] if after else fill
        ended = now - token["last_ts"] > cfg["recorder"]["stale_s"] and not (comp and now - comp <= cfg["recorder"]["post_s"])
        if not ended:
            return {"censored": True, "mint": token["mint"], "entry_ts": fill["ts"]}
        exit_p, reason = last, "sin más datos"
    ret, rug = costs.net_return(entry, _sample(exit_p), cfg)
    return {"mint": token["mint"], "entry_ts": fill["ts"], "mcap": fill["mcap"], "ret": ret, "rug": rug, "reason": reason,
            "stopped": reason == "stop", "hold_s": exit_p["ts"] - fill["ts"], "late": fill["phase"] == "amm"}


def _summary(rets, cfg, seed_off=0):
    b = cfg["backtest"]
    if not rets:
        return {"n": 0}
    pos = sum(r for r in rets if r > 0)
    neg = -sum(r for r in rets if r < 0)
    eq, peak, dd = 0.0, 0.0, 0.0
    for r in rets:  # curva de capital con 100 USD por operación, en orden de entrada
        eq += r * cfg["costs"]["position_usd"]
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {"n": len(rets), "mean": stats.mean(rets), "median": median(rets), "win": sum(1 for r in rets if r > 0) / len(rets),
            "usd_per_trade": stats.mean(rets) * cfg["costs"]["position_usd"], "total_usd": sum(rets) * cfg["costs"]["position_usd"],
            "profit_factor": (pos / neg) if neg > 0 else None, "max_drawdown_usd": dd,
            "ci90": stats.bootstrap_ci(rets, n=b["boot"], seed=b["ci_seed"] + seed_off)}


def run(store, cfg, now):
    b = cfg["backtest"]
    variants = load_variants()
    tokens = store.rec_all()
    paths = {t["mint"]: store.rec_path_of(t["mint"]) for t in tokens}
    sims = {v["id"]: [] for v in variants}
    cens = {v["id"]: 0 for v in variants}
    for t in tokens:
        for v in variants:
            r = simulate(t, paths[t["mint"]], v, cfg, now)
            if r is None:
                continue
            if r.get("censored"):
                cens[v["id"]] += 1
            else:
                sims[v["id"]].append(r)
    for v in sims.values():
        v.sort(key=lambda r: r["entry_ts"])
    rep = {"generated_at": now, "n_tokens": len(tokens), "n_with_feat": sum(1 for t in tokens if t.get("feat")),
           "n_completed": sum(1 for t in tokens if t.get("completed_ts")), "censored": cens, "verdict": None, "detail": ""}
    base = sims["B02"]
    if len(base) < 2 * b["min_n_select"]:
        rep["verdict"] = "SIN DATOS SUFICIENTES"
        rep["detail"] = (f"La variante base tiene {len(base)} operaciones simuladas y hacen falta al menos "
                         f"{2 * b['min_n_select']} para partir en dos mitades. Sigue grabando.")
        rep["base"] = _summary([r["ret"] for r in base], cfg)
        return rep
    cut = base[len(base) // 2 - 1]["entry_ts"]
    rep["cut_ts"] = cut
    table, best, best_v = [], None, None
    for v in variants:
        sel = [r["ret"] for r in sims[v["id"]] if r["entry_ts"] <= cut]
        row = {"id": v["id"], "desc": v["desc"], "n_select": len(sel), "mean": stats.mean(sel) if sel else None}
        table.append(row)
        if len(sel) >= b["min_n_select"] and (best is None or row["mean"] > best):
            best, best_v = row["mean"], v
    rep["selection_table"] = table
    if best_v is None:
        rep["verdict"] = "SIN DATOS SUFICIENTES"
        rep["detail"] = f"Ninguna variante llega a {b['min_n_select']} operaciones en la primera mitad."
        return rep
    rep["chosen"] = {"id": best_v["id"], "desc": best_v["desc"], "select_mean": best}
    test = [r for r in sims[best_v["id"]] if r["entry_ts"] > cut]
    rets = [r["ret"] for r in test]
    s = _summary(rets, cfg, 1)
    reasons = {}
    for r in test:
        reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1
    s.update({"stop_pct": sum(1 for r in test if r["stopped"]) / len(test) * 100 if test else None,
              "rug_pct": sum(1 for r in test if r["rug"]) / len(test) * 100 if test else None,
              "late_pct": sum(1 for r in test if r["late"]) / len(test) * 100 if test else None, "reasons": reasons})
    rep["test"] = s
    # el filtro, ¿mejora al mismo plan sin filtro? (solo si la elegida tiene filtros)
    unf = [r["ret"] for r in sims.get("B02", []) if r["entry_ts"] > cut]
    # robustez al retraso: la elegida con distintas latencias, solo en la segunda mitad
    grid = {}
    for lat in b["latency_grid_s"]:
        lr = []
        for t in tokens:
            r = simulate(t, paths[t["mint"]], best_v, cfg, now, latency_s=lat)
            if r and not r.get("censored") and r["entry_ts"] > cut:
                lr.append(r["ret"])
        grid[lat] = {"n": len(lr), "mean": stats.mean(lr) if lr else None}
    rep["latency_grid"] = grid
    rep["unfiltered_test_mean"] = stats.mean(unf) if unf else None
    n = len(rets)
    if n < b["min_n_test"]:
        rep["verdict"] = "SIN DATOS SUFICIENTES"
        rep["detail"] = (f"La variante elegida ({best_v['id']}) tiene {n} operaciones en la segunda mitad y se necesitan "
                         f"{b['min_n_test']}. No se concluye nada todavía.")
    elif s["mean"] <= 0 or (s["ci90"] and s["ci90"][1] <= 0):
        rep["verdict"] = "DESCARTAR"
        rep["detail"] = (f"En la segunda mitad la variante elegida pierde dinero neto de costes: {s['usd_per_trade']:+.1f} USD por "
                         f"operación de 100 USD. Se documenta como idea descartada.")
    elif s["ci90"] and s["ci90"][0] > 0 and (s["profit_factor"] or 0) > 1.2:
        rep["verdict"] = "RENTABLE (provisional)"
        rep["detail"] = (f"En la segunda mitad la variante elegida gana {s['usd_per_trade']:+.1f} USD por operación, con el intervalo "
                         f"al 90 % por encima de cero. Provisional: repite con más días y otra racha de mercado antes de usar dinero.")
    else:
        rep["verdict"] = "INCONCLUSO"
        rep["detail"] = (f"Resultado positivo ({s['usd_per_trade']:+.1f} USD por operación) pero el intervalo al 90 % incluye el cero "
                         f"o el factor de beneficio es bajo. Hace falta más muestra.")
    return rep
