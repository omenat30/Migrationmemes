"""Tokens que pumpean de repente y quién estaba dentro ANTES del pump (HIPOTESIS_v7.md).

Fuente: ranking de GMGN (solo lectura) por número de swaps y por volumen, con la variación de precio a 5 min, 1 h y 6 h. Un token «pumpea»
si en alguna ventana sube más de un umbral, ya tiene liquidez y no es un lanzamiento de hace minutos. De cada uno se leen los 100 mejores
traders; se considera que entró ANTES del pump si su precio medio de compra es como mucho `slack` veces el precio previo implícito
(precio actual / (1 + subida)). Un trader así gana mucho en ese token por definición, así que su presencia aquí NO prueba nada por sí sola:
hace falta que repita en varios tokens y, sobre todo, verificar su historial completo (el mismo sesgo del ganador que en las demás búsquedas).
"""
import time

WINDOWS = (("5m", "price_change_percent5m", 40.0), ("1h", "price_change_percent1h", 150.0), ("6h", "price_change_percent", 300.0))


def is_pumping(t, now=None, min_mcap=15000.0, min_liq=8000.0, min_age_s=1800):
    """t: fila cruda del ranking. Devuelve (ventana, subida %) o None."""
    now = now or time.time()
    if t.get("is_wash_trading") or t.get("is_honeypot"):
        return None
    if (t.get("market_cap") or 0) < min_mcap or (t.get("liquidity") or 0) < min_liq:
        return None
    created = t.get("creation_timestamp") or t.get("open_timestamp") or 0
    if created and now - created < min_age_s:
        return None
    best = None
    for name, key, thr in WINDOWS:
        ch = t.get(key)
        if ch is not None and ch >= thr and (best is None or ch / thr > best[1] / best[2]):
            best = (name, ch, thr)
    return None if best is None else (best[0], best[1])


def pre_price(price, change_pct):
    return price / (1.0 + change_pct / 100.0)


def early_buyers(rows, price, change_pct, supply, min_buy_usd=150.0, slack=1.3, min_mult=1.5):
    """rows: salida normalizada de Gmgn.top_traders. Devuelve los que compraron de verdad antes del pump y ganaron >= min_mult veces lo gastado."""
    base = pre_price(price, change_pct)
    out = []
    for r in rows:
        buy, sell, ac = r.get("buy_usd") or 0.0, r.get("sell_usd") or 0.0, r.get("avg_cost")
        if r.get("transfer_in") or buy < min_buy_usd or not ac or ac > base * slack:
            continue
        mult = (sell + max(0.0, (r.get("profit") or 0) - (sell - buy))) / buy  # ventas más lo que aún mantiene (profit realizado + latente)
        if mult < min_mult:
            continue
        out.append({"wallet": r["wallet"], "buy": round(buy), "mult": round(mult, 2), "entry_mcap": round(ac * supply) if supply else None,
                    "start": r.get("start"), "sold": round(sell)})
    return out


def discover_wallets(g, data, now, discover_mod, max_tokens=80, max_wallets=400, skip=(), min_pnl=0.30, min_buys=20, min_profit=1000.0,
                     min_winrate=0.35, log=print, save=None):
    """Un pase completo: tokens que pumpean ahora -> quién entró antes -> estadísticas de 30 días (con caché en data["stats"]).
    `data` = {"tokens": {...}, "stats": {...}} se va completando (y `save(data)` se llama de vez en cuando). Devuelve [(wallet, stats)] por rentabilidad."""
    found = {}
    for iv in ("5m", "1h", "6h"):
        for ob in ("swaps", "volume"):
            try:
                rows = discover_mod._patient(lambda: g.rank_raw(iv, 100, ob), log=lambda x: None)
            except Exception as e:
                log(f"  ranking {iv}/{ob}: {str(e)[:70]}")
                continue
            for t in rows:
                if not (t["address"].endswith("pump") or t.get("launchpad") == "pump"):
                    continue
                pm = is_pumping(t, now)
                if pm and t["address"] not in data["tokens"]:
                    found[t["address"]] = (t, pm)
    log(f"tokens que pumpean y aún no mirados: {len(found)} (ya guardados: {len(data['tokens'])})")
    todo = sorted(found.items(), key=lambda kv: -kv[1][1][1])[:max_tokens]
    for i, (m, (t, (win, ch))) in enumerate(todo, 1):
        try:
            rows = discover_mod._patient(lambda: g.top_traders(m, 100, "profit"), log=lambda x: None)
        except Exception as e:
            log(f"  {m[:8]} error {str(e)[:60]}")
            continue
        eb = early_buyers(rows, t.get("price") or 0, ch, t.get("total_supply") or 1e9)
        data["tokens"][m] = {"sym": t.get("symbol"), "ts": int(now), "win": win, "chg": round(ch), "mcap": t.get("market_cap"), "buyers": eb}
        if save:
            save(data)
        log(f"[{i}/{len(todo)}] {t.get('symbol')} +{ch:.0f}% ({win}) mcap ${t.get('market_cap') or 0:,.0f}: {len(eb)} entraron antes")
    pool = {}
    for m, d in data["tokens"].items():
        for b in d["buyers"]:
            pool.setdefault(b["wallet"], []).append((m, b))
    log(f"wallets que entraron antes de algún pump: {len(pool)}; en >= 2 tokens: {sum(1 for v in pool.values() if len(v) >= 2)}")
    order = [w for w in sorted(pool, key=lambda w: (-len(pool[w]), -sum(b["buy"] for _, b in pool[w]))) if w not in skip][:max_wallets]
    out = []
    for i, w in enumerate(order, 1):
        s = data["stats"].get(w)
        if s is None:
            try:
                s = discover_mod._patient(lambda: g.wallet_stats([w], "30d").get(w), log=lambda x: None)
            except Exception as e:
                log(f"  estadísticas {w[:8]}: {str(e)[:60]}")
                continue
            data["stats"][w] = s
            if save and i % 10 == 0:
                save(data)
        if s and (s["pnl"] or 0) >= min_pnl and (s["buys"] or 0) >= min_buys and (s["realized_profit"] or 0) >= min_profit and (s["winrate"] or 0) >= min_winrate:
            out.append((w, dict(s, tokens=len(pool[w]), trigger_mints=[m for m, _ in pool[w]])))
    if save:
        save(data)
    out.sort(key=lambda x: -(x[1]["pnl"] or 0))
    return out
