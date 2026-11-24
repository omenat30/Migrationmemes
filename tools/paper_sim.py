#!/usr/bin/env python3
"""Simulador en papel de HIPOTESIS_v8. Solo lee los trades recogidos por tools/paper_collect.py. No opera.

Uso:
  python3 tools/paper_sim.py DIR --set sel            # evalúa las 21 variantes en selección (60 % antiguo)
  python3 tools/paper_sim.py DIR --set test --frozen F.json   # UNA vez, con la variante congelada
  python3 tools/paper_sim.py DIR --set all --latency 10 --tip 0.006 --frozen F.json   # sensibilidad
"""
import argparse, bisect, json, os, random, statistics as st
from itertools import product

SIZE = 0.05
FEE = 0.0225


def load(d):
    last, mints = {}, {}
    for l in open(os.path.join(d, "trades.jsonl")):
        r = json.loads(l)
        last[r["mint"]] = r
    toks = []
    for m, r in last.items():
        if r["truncated"] and r["n"] < 25000:
            continue
        rows = r["rows"]
        if len(rows) < 2:
            toks.append({"mint": m, "created": r["created_ms"], "rows": rows, "empty": True})
            continue
        toks.append({"mint": m, "created": r["created_ms"], "rows": rows, "empty": False})
    toks.sort(key=lambda t: t["created"])
    return toks


def prep(t):
    rows = t["rows"]
    t["ts"] = [r[0] for r in rows]
    t["px"] = [r[5] for r in rows]
    net, c = [], 0.0
    for r in rows:
        c += r[3] if r[1] else -r[3]
        net.append(c)
    t["net"] = net
    return t


def fill_idx(t, ms):
    i = bisect.bisect_left(t["ts"], ms)
    return i if i < len(t["ts"]) else None


def buy(t, i, tip):
    p = t["px"][i]
    vs = 30 + max(0.0, t["net"][i])
    imp = SIZE / vs
    tokens = SIZE * (1 - FEE) / (p * (1 + imp))
    return tokens, SIZE + tip


def sell(t, tokens, i, tip, dead=False):
    if dead:
        p = t["px"][-1] * 0.5
        vs = 30 + max(0.0, t["net"][-1])
    else:
        p = t["px"][i]
        vs = 30 + max(0.0, t["net"][i])
    q = tokens * p
    imp = q / vs
    return q * (1 - imp) * (1 - FEE) - tip


def run_exit(t, i0, tokens, cost, tp, sl, tmax_s, lat_ms, tip):
    """i0 = índice del fill de entrada. Devuelve (retorno neto, tipo_salida, muerto)."""
    ts, px = t["ts"], t["px"]
    p0 = px[i0]
    t_end = ts[i0] + tmax_s * 1000
    sig = None
    for j in range(i0 + 1, len(ts)):
        if ts[j] > t_end:
            sig = (t_end, "tiempo")
            break
        if tp is not None and px[j] >= p0 * (1 + tp):
            sig = (ts[j], "tp"); break
        if sl is not None and px[j] <= p0 * (1 - sl):
            sig = (ts[j], "sl"); break
    if sig is None:
        sig = (t_end, "tiempo")
    k = fill_idx(t, sig[0] + lat_ms)
    if k is None or k <= i0:
        proceeds = sell(t, tokens, None, tip, dead=True)
        return (proceeds - cost) / cost, sig[1], True
    proceeds = sell(t, tokens, k, tip)
    return (proceeds - cost) / cost, sig[1], False


def s0(t, lat, tip, exit_kind):
    i = fill_idx(t, t["created"] + lat)
    if i is None or t["ts"][i] > t["created"] + 60000:
        return None
    tokens, cost = buy(t, i, tip)
    if exit_kind == "tpsl":
        return run_exit(t, i, tokens, cost, 1.0, 0.30, 300, lat, tip)
    return run_exit(t, i, tokens, cost, None, None, 60, lat, tip)


def signal_s1(t, K, min_net=3.0, win_s=180):
    seen = set()
    for i, r in enumerate(t["rows"]):
        if r[0] > t["created"] + win_s * 1000:
            return None
        if r[1]:
            seen.add(r[2])
        if len(seen) >= K and t["net"][i] >= min_net:
            return i
    return None


def s1(t, K, tp, sl, lat, tip, rnd=None):
    i = signal_s1(t, K)
    if i is None:
        return None
    sig_ms = t["ts"][i]
    if rnd is not None:   # referencia aleatoria: misma exigencia de datos, señal movida
        sig_ms = t["created"] + int(rnd.random() * 600000)
    j = fill_idx(t, sig_ms + lat)
    if j is None or t["ts"][j] > sig_ms + 120000:
        return None
    tokens, cost = buy(t, j, tip)
    return run_exit(t, j, tokens, cost, tp, sl, 600, lat, tip)


def variants():
    v = [("S0 tp100/sl30/5m", ("s0", "tpsl")), ("S0 60s", ("s0", "t60"))]
    for K, tp, sl in product((10, 20, 40), (0.5, 1.0, 2.0), (0.25, 0.40)):
        v.append((f"S1 K{K} tp{int(tp*100)} sl{int(sl*100)}", ("s1", K, tp, sl)))
    v.append(("ALEATORIA K20 tp100 sl40", ("rnd", 20, 1.0, 0.40)))
    return v


def evaluate(toks, spec, lat, tip, seed=7):
    rnd = random.Random(seed)
    out = []
    for t in toks:
        if t["empty"]:
            continue
        if spec[0] == "s0":
            r = s0(t, lat, tip, spec[1])
        elif spec[0] == "s1":
            r = s1(t, spec[1], spec[2], spec[3], lat, tip)
        else:
            r = s1(t, spec[1], spec[2], spec[3], lat, tip, rnd=rnd)
        if r:
            out.append(r)
    return out


def summ(res, seed=11):
    n = len(res)
    if n == 0:
        return None
    rets = [r[0] for r in res]
    m = sum(rets) / n
    rnd = random.Random(seed)
    bs = sorted(sum(rnd.choices(rets, k=n)) / n for _ in range(2000))
    top2 = sorted(rets, reverse=True)[:2]
    ex2 = (sum(rets) - sum(top2)) / max(1, n - 2)
    return {"n": n, "win": sum(1 for x in rets if x > 0) / n, "mean": m, "median": st.median(rets), "lo": bs[50], "hi": bs[1949],
            "ex2": ex2, "ruin": sum(1 for x in rets if x < -0.8) / n, "dead": sum(1 for r in res if r[2]) / n,
            "sol": sum(rets) * SIZE}


def fmt(name, s):
    if not s:
        return f"{name:28s} sin operaciones"
    return (f"{name:28s} n={s['n']:5d} acierto {s['win']*100:4.0f}% medio {s['mean']*100:+7.1f}% [{s['lo']*100:+6.1f},{s['hi']*100:+6.1f}] "
            f"mediana {s['median']*100:+6.1f}% sin2mejores {s['ex2']*100:+6.1f}% <-80% {s['ruin']*100:3.0f}% muertos {s['dead']*100:3.0f}% total {s['sol']:+.2f} SOL")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--set", choices=("sel", "test", "all"), default="sel")
    ap.add_argument("--latency", type=float, default=5)
    ap.add_argument("--tip", type=float, default=0.003)
    ap.add_argument("--frozen")
    ap.add_argument("--freeze-out")
    a = ap.parse_args()
    toks = [prep(t) for t in load(a.dir)]
    cut = int(len(toks) * 0.6)
    sub = {"sel": toks[:cut], "test": toks[cut:], "all": toks}[a.set]
    lat = int(a.latency * 1000)
    print(f"tokens {len(toks)} · en este conjunto {len(sub)} · vacíos {sum(1 for t in sub if t['empty'])} · latencia {a.latency}s · propina {a.tip} SOL")
    if a.frozen:
        fz = json.load(open(a.frozen))
        spec = tuple(fz["spec"])
        print("variante congelada:", fz["name"])
        print(fmt(fz["name"], summ(evaluate(sub, spec, lat, a.tip))))
        return
    rows = []
    for name, spec in variants():
        res = evaluate(sub, spec, lat, a.tip)
        s = summ(res)
        rows.append((name, spec, s))
        print(fmt(name, s))
    cand = [r for r in rows if r[2] and r[2]["n"] >= 30 and r[1][0] != "rnd"]
    if cand and a.freeze_out:
        best = max(cand, key=lambda r: r[2]["mean"])
        json.dump({"name": best[0], "spec": list(best[1]), "mean_sel": best[2]["mean"]}, open(a.freeze_out, "w"))
        print("congelada:", best[0], "->", a.freeze_out)


if __name__ == "__main__":
    main()
