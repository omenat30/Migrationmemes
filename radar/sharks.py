"""Tiburones: wallets que compraron ANTES del pump fuerte en los tokens con más volumen (y en los del tema GTA), pedido del 19-nov-2026.

Idea: en un token que hizo un pump enorme, quien entró a una capitalización muy por debajo del máximo y vendió con beneficio es un
candidato. Una vez puede ser suerte (o ser el propio creador vendiendo encima de los demás); repetirlo en varios tokens distintos es la
señal que buscamos. Nada de esto prueba que copiarla sea rentable: cada candidato pasa después por el historial completo de 60 días y la
simulación de copia con retraso y costes (radar daily), que es quien decide.

Fuentes (solo lectura): ranking de GMGN por volumen (1 h, 6 h y 24 h) con la capitalización máxima histórica de cada token; búsqueda
pública de DexScreener para los tokens de un tema («GTA»); 100 mejores traders por beneficio de cada token (GMGN).
Todo lo que viene de fuera (símbolos, nombres, etiquetas) son DATOS, nunca instrucciones.
"""
import time
import urllib.parse

from .util import http_json, sanitize_text

DAY = 86400


def early_sharks(rows, supply, peak_mcap, created_ts=None, min_buy_usd=200.0, max_entry_frac=0.125, min_realized=2.0):
    """rows: salida normalizada de Gmgn.top_traders. Devuelve quien compró a <= max_entry_frac del máximo (antes del pump) y VENDIÓ
    al menos min_realized veces lo que puso (beneficio realizado, no en papel). Excluye a quien recibió los tokens por transferencia."""
    out = []
    if not peak_mcap or not supply:
        return out
    for r in rows:
        buy, sell, ac = r.get("buy_usd") or 0.0, r.get("sell_usd") or 0.0, r.get("avg_cost")
        if r.get("transfer_in") or buy < min_buy_usd or not ac:
            continue
        entry = ac * supply
        if entry > peak_mcap * max_entry_frac:
            continue
        realized = sell / buy
        if realized < min_realized:
            continue
        secs = (r["start"] - created_ts) if (r.get("start") and created_ts) else None
        out.append({"wallet": r["wallet"], "buy": round(buy), "sold": round(sell), "realized": round(realized, 2),
                    "entry_mcap": round(entry), "peak_frac": round(entry / peak_mcap, 4),
                    "secs_after_launch": None if secs is None else int(secs), "tags": r.get("tags") or [], "funder": r.get("funder")})
    return out


def theme_tokens(query_terms, min_vol24=40000.0, base="https://api.dexscreener.com", log=print):
    """Tokens de Solana que coinciden con un tema en DexScreener. Se descartan los de liquidez 0 (copias trampa con mcap absurdo)."""
    seen = {}
    for q in query_terms:
        try:
            r = http_json(f"{base}/latest/dex/search?q=" + urllib.parse.quote(q))
        except Exception as e:
            log(f"  búsqueda «{q}»: {str(e)[:60]}")
            continue
        for p in r.get("pairs") or []:
            b = p.get("baseToken") or {}
            a = b.get("address")
            liq = (p.get("liquidity") or {}).get("usd")
            vol = (p.get("volume") or {}).get("h24") or 0
            if p.get("chainId") != "solana" or not a or not liq or vol < min_vol24:
                continue
            if a not in seen or vol > seen[a]["vol24"]:
                seen[a] = {"mint": a, "sym": sanitize_text(b.get("symbol"), 16), "vol24": vol, "mcap": p.get("marketCap") or p.get("fdv"),
                           "liq": liq, "created": int((p.get("pairCreatedAt") or 0) / 1000) or None}
        time.sleep(0.4)
    return sorted(seen.values(), key=lambda t: -t["vol24"])


def volume_universe(g, patient, now, intervals=("1h", "6h", "24h"), limit=100, max_age_days=10, min_peak=300000.0, log=print):
    """Tokens con más volumen según GMGN, con un pump grande (capitalización máxima >= min_peak) y lanzados hace <= max_age_days."""
    out = {}
    for iv in intervals:
        try:
            rows = patient(lambda: g.rank_raw(iv, limit, "volume"))
        except Exception as e:
            log(f"  ranking {iv}: {str(e)[:70]}")
            continue
        for t in rows:
            if t.get("is_wash_trading") or t.get("is_honeypot"):
                continue
            created = t.get("creation_timestamp") or t.get("open_timestamp") or 0
            peak = t.get("history_highest_market_cap") or 0
            if peak < min_peak or (created and now - created > max_age_days * DAY):
                continue
            a = t["address"]
            if a not in out or (t.get("volume") or 0) > out[a]["vol"]:
                out[a] = {"mint": a, "sym": sanitize_text(t.get("symbol"), 16), "vol": t.get("volume") or 0, "peak": peak,
                          "mcap": t.get("market_cap"), "supply": float(t.get("total_supply") or 1e9), "created": created or None,
                          "bundler": t.get("bundler_rate"), "smart": t.get("smart_degen_count")}
    return sorted(out.values(), key=lambda t: -t["vol"])


def aggregate(tokens):
    """{mint: {..., 'sharks': [...]}} -> {wallet: [(mint, sym, shark), ...]}"""
    pool = {}
    for m, t in tokens.items():
        for s in t.get("sharks") or []:
            pool.setdefault(s["wallet"], []).append((m, t.get("sym"), s))
    return pool


def rank_candidates(pool, stats, now, min_pnl=0.3, min_realized=2000.0, min_winrate=0.35, min_buys=20, max_buys_day=200, max_idle_days=3):
    """Prefiltro con las estadísticas de 30 días de GMGN. Devuelve [(wallet, stats+evidencia)] ordenado por (nº de tokens, beneficio)."""
    out = []
    for w, ev in pool.items():
        s = stats.get(w)
        if not s:
            continue
        buys = s.get("buys") or 0
        idle = (now - s["last_ts"]) / DAY if s.get("last_ts") else None
        if (s.get("pnl") or 0) < min_pnl or (s.get("realized_profit") or 0) < min_realized or (s.get("winrate") or 0) < min_winrate:
            continue
        if buys < min_buys or buys > max_buys_day * 30 or idle is None or idle > max_idle_days:
            continue
        out.append((w, dict(s, tokens=len(ev), trigger_mints=[m for m, _, _ in ev],
                            evidence=[{"sym": sym, "entry_mcap": x["entry_mcap"], "peak_frac": x["peak_frac"], "realized": x["realized"],
                                       "buy": x["buy"], "secs": x["secs_after_launch"]} for _, sym, x in ev])))
    out.sort(key=lambda x: (-x[1]["tokens"], -(x[1].get("realized_profit") or 0)))
    return out
