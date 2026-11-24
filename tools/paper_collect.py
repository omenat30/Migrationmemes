#!/usr/bin/env python3
"""Recolector para la prueba en papel de «cazar tokens nuevos de baja cap» (HIPOTESIS_v8).

Solo LEE la API pública de pump.fun. No opera, no firma, no usa claves.

Cada ciclo:
  1) lista los ~1.000 tokens más nuevos y anota los que no conocía (mint, creador, hora de creación);
  2) cuando un token cumple MIN_AGE_MIN minutos de vida, baja TODOS sus trades (hasta MAX_TRADES) y lo guarda.

No hay filtro de selección: entra todo token nuevo (incluidos los muertos), para no medir solo a los ganadores.
Salida (carpeta --out):
  mints.jsonl   una línea por token nuevo visto
  trades.jsonl  una línea por token ya descargado: {mint, created_ms, n, truncated, rows:[[ms, side, trader, quoteSOL, baseTokens, priceSOL, late]]}
"""
import argparse, json, os, sys, time, urllib.request, urllib.error

B = "https://frontend-api-v3.pump.fun"
C = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
UA = {"User-Agent": "Mozilla/5.0"}


def get(path, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(B + path, headers=UA), timeout=25) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(10 * (i + 1))
            elif e.code in (400, 404):
                return None
            else:
                time.sleep(3 * (i + 1))
        except Exception:
            time.sleep(3 * (i + 1))
    return None


def list_new():
    out = []
    for off in range(0, 1000, 50):
        d = get(f"/coins?offset={off}&limit=50&sort=created_timestamp&order=DESC&includeNsfw=true")
        if not d:
            break
        out += d
        time.sleep(0.15)
    return out


def fetch_trades(mint, max_trades):
    rows, cursor, truncated = [], None, False
    while True:
        q = f"/trades/{C}/{mint}?limit=100" + (f"&cursor={cursor}" if cursor else "")
        d = get(q)
        if d is None:
            return None, False
        for t in d.get("trades", []):
            try:
                qa = int(t["quoteAmount"]["raw"]) / 10 ** t["quoteAmount"]["decimals"]
                ba = int(t["baseAmount"]["raw"]) / 10 ** t["baseAmount"]["decimals"]
                rows.append([t["blockTimeMs"], 1 if t["side"] == "buy" else 0, t["trader"]["address"], qa, ba,
                             float(t["priceQuote"]), 1 if t.get("late") else 0])
            except Exception:
                continue
        cursor = d.get("cursor")
        if not cursor:
            break
        if len(rows) >= max_trades:
            truncated = True
            break
        time.sleep(0.12)
    rows.sort(key=lambda r: r[0])
    return rows, truncated


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-age-min", type=float, default=45)
    ap.add_argument("--max-trades", type=int, default=25000)
    ap.add_argument("--max-trades-final", type=int, default=25000)
    ap.add_argument("--hours", type=float, default=12)
    ap.add_argument("--poll-s", type=int, default=120)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    mp, tp = os.path.join(a.out, "mints.jsonl"), os.path.join(a.out, "trades.jsonl")
    seen, done = {}, set()
    if os.path.exists(mp):
        for l in open(mp):
            r = json.loads(l); seen[r["mint"]] = r
    if os.path.exists(tp):
        for l in open(tp):
            r_ = json.loads(l)
            if not r_["truncated"] or r_["n"] >= a.max_trades_final:
                done.add(r_["mint"])
    t_end = time.time() + a.hours * 3600
    while time.time() < t_end:
        t0 = time.time()
        new = 0
        with open(mp, "a") as f:
            for c in list_new():
                m = c.get("mint")
                if m and m not in seen:
                    r = {"mint": m, "created_ms": c.get("created_timestamp"), "creator": c.get("creator"),
                         "name": (c.get("name") or "")[:30], "seen_ms": int(time.time() * 1000)}
                    seen[m] = r
                    f.write(json.dumps(r) + "\n")
                    new += 1
        due = [r for m, r in seen.items() if m not in done and r["created_ms"] and time.time() * 1000 - r["created_ms"] >= a.min_age_min * 60000]
        due.sort(key=lambda r: r["created_ms"])
        got = 0
        with open(tp, "a") as f:
            for r in due:
                rows, trunc = fetch_trades(r["mint"], a.max_trades)
                if rows is None:
                    continue
                f.write(json.dumps({"mint": r["mint"], "created_ms": r["created_ms"], "n": len(rows), "truncated": trunc, "rows": rows}) + "\n")
                f.flush()
                done.add(r["mint"])
                got += 1
                if time.time() - t0 > a.poll_s * 3:   # no dejar de listar demasiado tiempo
                    break
        print(time.strftime("%H:%M:%S", time.gmtime()), f"nuevos {new} · vistos {len(seen)} · descargados {len(done)} (+{got}) · pendientes {len(seen) - len(done)}", flush=True)
        time.sleep(max(5, a.poll_s - (time.time() - t0)))


if __name__ == "__main__":
    main()
