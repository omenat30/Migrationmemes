"""Cribado de wallets sobre los tokens vigilados: ¿quién gana de verdad y quién gana vendiéndote a ti? (HIPOTESIS_v6.md)"""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import stats, wallet_history
from .util import median

D_GRID = (30, 60, 120)


def classify(s, cfg):
    """s: resumen de wallet_history.summarize. Reglas fijas de HIPOTESIS_v6."""
    h = cfg["history"]
    if s.get("bot"):
        return "BOT"
    sold, closed = s.get("sold", 0), s.get("closed", 0)
    qx = s.get("quick_exit_ratio")
    if sold >= 5 and qx is not None and qx >= 0.5:
        return "EXTRACTORA"
    if closed < 5:
        return "SIN HISTORIAL"
    if s.get("pnl_sol", 0) <= 0:
        return "PIERDE"
    if (s.get("median_hold_s") or 0) >= h["min_hold_s"] and (qx or 0) <= 0.3:
        return "CANDIDATA"
    return "PIERDE" if (s.get("median_hold_s") or 0) < h["min_hold_s"] else "EXTRACTORA"


def ledger(store, min_buy_sol=1.0):
    """Por wallet: tokens en los que operó y SOL comprados/vendidos en los tokens vigilados."""
    rows = store.db.execute("SELECT wallet, mint, is_buy, sol FROM trades").fetchall()
    agg = defaultdict(lambda: {"buy": 0.0, "sell": 0.0, "mints": set()})
    for r in rows:
        a = agg[r["wallet"]]
        a["buy" if r["is_buy"] else "sell"] += r["sol"]
        a["mints"].add(r["mint"])
    return {w: {"buy_sol": a["buy"], "sell_sol": a["sell"], "tokens": len(a["mints"])}
            for w, a in agg.items() if a["buy"] >= min_buy_sol}


def screen(store, helius, cfg, wallets, now, workers=5, log=print):
    """Historial y clasificación de cada wallet (con caché). Devuelve {wallet: {summary, class}}."""
    out, todo = {}, []
    for w in wallets:
        c = store.get_wallet("w:" + w, cfg["wallets"]["wallet_cache_s"], now)
        if c is not None and "pnl_ex_top2" in c.get("summary", {}):  # caché de una versión anterior: se vuelve a pedir
            out[w] = c
        else:
            todo.append(w)

    def fetch(w):
        txs = helius.wallet_txs(w)
        p = wallet_history.parse_wallet_txs(w, txs, 100, cfg["wallets"]["min_fund_sol"])
        s = wallet_history.summarize(p, cfg)
        return {"summary": s, "class": classify(s, cfg)}

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fetch, w): w for w in todo}
        for f in as_completed(futs):
            w = futs[f]
            try:
                out[w] = f.result()
                store.put_wallet("w:" + w, out[w], now)
            except Exception as e:
                log(f"! wallet {w[:6]}…: {str(e)[:60]}")
            done += 1
            if done % 25 == 0:
                log(f"  {done}/{len(todo)} wallets analizadas")
    return out


def follower_returns(store, wallets_by_class, fee=0.01):
    """Seguidor que copia compras con retraso D. Devuelve {clase: {D: [retornos]}} y cuántas quedaron sin resolver."""
    by_mint = defaultdict(list)
    for r in store.db.execute("SELECT mint, ts, wallet, is_buy, sol, tokens FROM trades WHERE tokens > 0 AND sol > 0 ORDER BY ts").fetchall():
        by_mint[r["mint"]].append((r["ts"], r["wallet"], bool(r["is_buy"]), r["sol"] / r["tokens"], r["sol"]))
    cls = {w: c for c, ws in wallets_by_class.items() for w in ws}
    res = {c: {d: [] for d in D_GRID} for c in wallets_by_class}
    unresolved = {c: 0 for c in wallets_by_class}
    for mint, tr in by_mint.items():
        last_price = tr[-1][3]
        for i, (ts, w, buy, p, sol) in enumerate(tr):
            c = cls.get(w)
            if c is None or not buy or sol < 0.3:
                continue
            exit_ts = next((t2 for t2, w2, b2, _, _ in tr[i + 1:] if w2 == w and not b2), None)
            for d in D_GRID:
                entry = next((p2 for t2, _, _, p2, _ in tr if t2 >= ts + d), None)
                if entry is None:
                    continue
                if exit_ts is not None:
                    ex = next((p2 for t2, _, _, p2, _ in tr if t2 >= exit_ts + d), None)
                    if ex is None:
                        unresolved[c] += 1
                        continue
                else:
                    ex = last_price
                    unresolved[c] += 1  # sigue dentro: se marca al último precio conocido, no es resultado cerrado
                    continue
                res[c][d].append(ex / entry * (1 - fee) ** 2 - 1)
    return res, unresolved


def run(store, helius, cfg, now, min_buy_sol=1.0, log=print):
    led = ledger(store, min_buy_sol)
    log(f"wallets con ≥{min_buy_sol} SOL comprados en los tokens vigilados: {len(led)}")
    scr = screen(store, helius, cfg, list(led), now, log=log)
    groups = defaultdict(list)
    for w, v in scr.items():
        groups[v["class"]].append(w)
    fr, unres = follower_returns(store, groups)
    rep = {"generated_at": now, "n_wallets": len(led), "n_screened": len(scr), "classes": {c: len(ws) for c, ws in groups.items()},
           "follower": {}, "candidates": []}
    for c in groups:
        rep["follower"][c] = {"unresolved": unres[c], "by_delay": {}}
        for d, rets in fr[c].items():
            rep["follower"][c]["by_delay"][d] = ({"n": len(rets), "mean": stats.mean(rets), "median": median(rets),
                                                  "win": sum(1 for r in rets if r > 0) / len(rets), "ci90": stats.bootstrap_ci(rets, n=1500, seed=5)}
                                                 if rets else {"n": 0})
    for w in sorted(groups.get("CANDIDATA", []), key=lambda w: -scr[w]["summary"]["pnl_sol"]):
        s = scr[w]["summary"]
        rep["candidates"].append({"wallet": w, "pnl_sol": s["pnl_sol"], "closed": s["closed"], "win_rate": s["win_rate"],
                                  "median_hold_s": s["median_hold_s"], "quick_exit_ratio": s["quick_exit_ratio"],
                                  "tokens_in_window": led[w]["tokens"], "bought_sol": led[w]["buy_sol"], "sold_sol": led[w]["sell_sol"]})
    return rep
