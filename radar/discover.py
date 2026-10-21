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


def pool_trades(h, pool, mint, max_txs=700):
    """Operaciones de la wallet que firma en el pool de PumpSwap (tras migrar). Devuelve lista de {wallet, is_buy, sol, ts}."""
    from .wallet_history import derive_trade
    sigs, before = [], None
    for _ in range(3):
        page = h.curve_signatures(pool, limit=1000, before=before)
        if not page:
            break
        sigs.extend(x for x in page if not x.get("err"))
        before = page[-1]["signature"]
        if len(page) < 1000 or len(sigs) >= max_txs:
            break
    out = []
    sigs = sigs[:max_txs]
    for i in range(0, len(sigs), 100):
        for t in h.parse_transactions([x["signature"] for x in sigs[i:i + 100]]) or []:
            w = t.get("feePayer")
            tr = derive_trade(w, t) if w else None
            if tr and tr[1] == mint:
                side, _, sol, _ = tr
                out.append({"wallet": w, "is_buy": side == "buy", "sol": sol, "ts": t.get("timestamp") or 0})
    return out


def venue_trades(h, address, mint, t0, t1, kind, max_pages=12, parse_budget=700):
    """Operaciones de un token en un lugar (curva de pump.fun o pool) entre t0 y t1 (segundos). kind: 'curve' o 'pool'.
    Pagina las firmas hacia atrás hasta pasar t0. Devuelve lista de {wallet, is_buy, sol, ts}."""
    from .sources.curve_trades import trades_from_enhanced
    from .wallet_history import derive_trade
    sigs, before = [], None
    for _ in range(max_pages):
        page = h.curve_signatures(address, limit=1000, before=before)
        if not page:
            break
        sigs.extend(x for x in page if not x.get("err"))
        before = page[-1]["signature"]
        if (page[-1].get("blockTime") or 0) < t0 or len(page) < 1000:
            break
    win = [x for x in sigs if t0 <= (x.get("blockTime") or 0) <= t1][:parse_budget]
    out = []
    for i in range(0, len(win), 100):
        txs = h.parse_transactions([x["signature"] for x in win[i:i + 100]]) or []
        if kind == "curve":
            tr, _ = trades_from_enhanced(txs, mint, address)
            out.extend({"wallet": t["wallet"], "is_buy": t["is_buy"], "sol": t["sol"], "ts": t["ts"]} for t in tr)
        else:
            for t in txs:
                w = t.get("feePayer")
                d = derive_trade(w, t) if w else None
                if d and d[1] == mint:
                    out.append({"wallet": w, "is_buy": d[0] == "buy", "sol": d[2], "ts": t.get("timestamp") or 0})
    return out


def cotraders(per_token_results, seed_wallets, min_tokens=3, min_mult=1.3, min_proceeds=0.5, min_hold_s=420):
    """Wallets distintas de las semillas que ganaron en varios de los mismos tokens que la semilla."""
    wins = defaultdict(list)
    for mint, res in per_token_results.items():
        for w, r in res.items():
            if w in seed_wallets:
                continue
            mult = r["proceeds"] / r["cost"]
            if mult >= min_mult and r["proceeds"] >= min_proceeds and r["hold"] >= min_hold_s:
                wins[w].append((mint, mult, r["hold"]))
    out = [(w, v) for w, v in wins.items() if len(v) >= min_tokens]
    out.sort(key=lambda x: -len(x[1]))
    return out


def _patient(fn, tries=4, log=print, net_tries=6):
    """Llama a fn(); si GMGN limita el uso, espera a que acabe el bloqueo (más un margen) y vuelve a intentarlo.
    Nunca reintenta durante el bloqueo: hacerlo lo alarga. Los fallos de red (conexión rechazada, tiempo agotado, DNS) se reintentan con
    espera creciente (10, 20, 40... s): antes un solo corte abortaba una descarga de horas."""
    import time as _t
    from .sources.gmgn import GmgnRateLimited
    net = 0
    i = 0
    while True:
        try:
            return fn()
        except GmgnRateLimited as e:
            i += 1
            if i >= tries:
                return fn()
            wait = max(5.0, (e.reset_at or _t.time() + 60) - _t.time() + 4)
            log(f"  GMGN limita el uso; espero {wait:.0f} s")
            _t.sleep(wait)
        except OSError as e:   # URLError, ConnectionError y TimeoutError heredan de OSError
            net += 1
            if net > net_tries:
                raise
            wait = min(10.0 * 2 ** (net - 1), 160.0)
            log(f"  fallo de red ({str(e)[:50]}); reintento en {wait:.0f} s")
            _t.sleep(wait)


def gmgn_candidates(g, intervals=("24h", "6h"), tokens_per_interval=40, order_by=("volume", "smart_degen_count"),
                    min_trader_profit_usd=300.0, min_pnl=0.30, min_winrate=0.0, min_buys=20, min_profit_usd=1000.0,
                    period="30d", pump_only=True, cache=None, max_wallets=400, skip=(), log=print, tag=None):
    """Descubrimiento con GMGN (solo lectura): tokens en tendencia -> mejores traders de cada uno -> estadísticas de PnL a 30 días
    una a una (con caché en disco) -> filtro. Devuelve [(wallet, stats)] ordenado por rentabilidad. Los filtros de aquí solo
    reducen el trabajo: la decisión final la toman los filtros de deepwallet/gmgnwallet con el historial completo."""
    import json as _json
    import os as _os
    stats_cache = {}
    if cache and _os.path.exists(cache):
        try:
            stats_cache = _json.load(open(cache))
        except Exception:
            stats_cache = {}
    pool_file = (cache + ".pool.json") if cache else None
    pool, tokens = {}, {}
    if pool_file and _os.path.exists(pool_file):
        try:
            saved = _json.load(open(pool_file))
            tokens, pool = saved["tokens"], saved["pool"]
            log(f"reutilizo la lista guardada: {len(tokens)} tokens, {len(pool)} wallets con ganancia")
        except Exception:
            pool, tokens = {}, {}
    for iv in (intervals if not tokens else ()):
        for ob in order_by:
            try:
                for t in _patient(lambda: g.trending(iv, 100, ob), log=log)[:tokens_per_interval]:
                    if t["mint"] and (not pump_only or t["mint"].endswith("pump")):
                        tokens[t["mint"]] = t
            except Exception as e:
                log(f"  tendencia {iv}/{ob}: {str(e)[:70]}")
    log(f"tokens en tendencia a revisar: {len(tokens)}")
    for i, mint in enumerate(tokens if not pool else (), 1):
        try:
            for tr in _patient(lambda: (g.top_traders(mint, 100, "profit", tag) if tag else g.top_traders(mint, 100, "profit")), log=log):
                if (tr["profit"] or 0) >= min_trader_profit_usd:
                    pool.setdefault(tr["wallet"], []).append((tr["profit"] or 0))
        except Exception as e:
            log(f"  top traders {mint[:8]}: {str(e)[:70]}")
        if i % 10 == 0:
            log(f"  [{i}/{len(tokens)}] wallets con ganancia hasta ahora: {len(pool)}")
    if pool_file and pool and not _os.path.exists(pool_file):
        _json.dump({"tokens": tokens, "pool": pool}, open(pool_file, "w"))
    # las que más ganaron en total (suma entre tokens) primero
    wallets = sorted((w for w in pool if w not in skip), key=lambda w: -sum(pool[w]))[:max_wallets]
    log(f"wallets con ganancia >= ${min_trader_profit_usd:.0f} en algún token: {len(pool)} (se miran {len(wallets)})")
    out = []
    for i, w in enumerate(wallets, 1):
        s = stats_cache.get(w)
        if s is None:
            try:
                s = _patient(lambda: g.wallet_stats([w], period).get(w), log=log)
            except Exception as e:
                log(f"  estadísticas {w[:8]}: {str(e)[:70]}")
                continue
            stats_cache[w] = s
            if cache and i % 10 == 0:
                _json.dump(stats_cache, open(cache, "w"))
            if i % 25 == 0:
                log(f"  [{i}/{len(wallets)}] estadísticas leídas")
        if s and ((s["pnl"] or 0) >= min_pnl and (s["winrate"] or 0) >= min_winrate and (s["buys"] or 0) >= min_buys
                  and (s["realized_profit"] or 0) >= min_profit_usd):
            out.append((w, dict(s, tokens=len(pool.get(w, [])))))
    if cache:
        _json.dump(stats_cache, open(cache, "w"))
    out.sort(key=lambda x: -(x[1]["pnl"] or 0))
    return out
