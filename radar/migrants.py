"""Quién repite los x10 rápidos en tokens recién migrados de pump.fun (HIPOTESIS_v7.md).

Para cada token migrado se leen, con GMGN (solo lectura), sus 100 mejores traders por ganancia. Un trader cuenta como «acierto rápido»
si COMPRÓ de verdad (descarta lo recibido por transferencia: devs e insiders), cobró al menos `min_mult` veces lo que gastó y
tuvo la posición abierta como mucho `max_hold_s` segundos. Después se buscan las wallets que repiten ese acierto en varios tokens.
Límite: los 100 mejores por ganancia no son TODOS los que operaron, así que el grupo que sale es un mínimo, no el total; y la tenencia
sale de las marcas de tiempo del primer y último movimiento de GMGN, no de cada operación.
"""
from collections import defaultdict


def fast_winners(rows, min_buy_usd=150.0, min_mult=5.0, max_hold_s=1800, min_hold_s=20):
    """rows: filas normalizadas de Gmgn.top_traders. Devuelve los aciertos rápidos [{wallet, buy, sell, mult, hold, start}]."""
    out = []
    for r in rows:
        buy, sell = r.get("buy_usd") or 0.0, r.get("sell_usd") or 0.0
        if buy < min_buy_usd or sell <= 0:
            continue
        start, end = r.get("start"), r.get("end")
        if not start or not end or end < start:
            continue
        hold = end - start
        mult = sell / buy
        if mult >= min_mult and min_hold_s <= hold <= max_hold_s:
            out.append({"wallet": r["wallet"], "buy": round(buy), "sell": round(sell), "mult": round(mult, 1), "hold": int(hold), "start": int(start)})
    return out


def group(per_token, min_tokens=3):
    """per_token: {mint: {"winners": [...]}}. Devuelve [(wallet, [(mint, mult, hold, buy)...])] con >= min_tokens aciertos, más repetidores primero."""
    by = defaultdict(list)
    for mint, d in per_token.items():
        for w in d.get("winners", []):
            by[w["wallet"]].append((mint, w["mult"], w["hold"], w["buy"]))
    out = [(w, v) for w, v in by.items() if len(v) >= min_tokens]
    out.sort(key=lambda x: (-len(x[1]), -sum(m for _, m, _, _ in x[1])))
    return out
