"""Auditoría de las copias reales de un usuario en GMGN (21-23 oct 2026).
Lee (solo lectura) el historial de la wallet del usuario, reconstruye sus posiciones y atribuye cada compra a la wallet copiada
(la primera de las wallets seguidas que compró ese mismo token en los minutos anteriores). Después mide por wallet copiada, por tamaño,
por mcap de entrada y por tenencia dónde se pierde el dinero.
Uso: python3 tools/analysis/audit_copias.py <wallet_del_usuario> <carpeta con deep_*.json de las wallets seguidas> [dias=60]
"""
import glob
import json
import os
import statistics
import sys
import time

sys.path.insert(0, ".")
from radar import gmgnwallet  # noqa: E402
from radar.config import load_config  # noqa: E402
from radar.sources.gmgn import Gmgn  # noqa: E402

DAY = 86400
W, D = sys.argv[1], sys.argv[2]
DAYS = int(sys.argv[3]) if len(sys.argv) > 3 else 60
cfg = load_config()
g = Gmgn(cfg)
SOL = 104.2
m, pos = gmgnwallet.analyze(g, W, cfg, SOL, days=DAYS, max_pages=80, early=False)
print(f"{len(pos)} posiciones del usuario ({m['n_closed']} cerradas, {m['n_open']} abiertas); cobertura {m.get('coverage')}")

# wallets seguidas: todas las de las cachés (mint -> [(wallet, entry_ts, mult, hold)])
src = {}
for f in glob.glob(D + "/deep_*.json"):
    try:
        data = json.load(open(f))
    except Exception:
        continue
    for r in data if isinstance(data, list) else []:
        w = r["metrics"]["wallet"]
        for p in r.get("positions") or []:
            if p.get("mint"):
                src.setdefault(p["mint"], {})[w] = p

rows = []
for p in pos:
    cands = [(w, q) for w, q in src.get(p["mint"], {}).items() if -3600 <= p["entry_ts"] - q["entry_ts"] <= 1800 and w != W]
    cands.sort(key=lambda x: x[1]["entry_ts"])
    leader = cands[0][0] if cands else None
    q = cands[0][1] if cands else None
    usd = p["cost"] * SOL
    out = (p["proceeds"] * SOL) if p["closed"] else None
    rows.append(dict(mint=p["mint"], entry=p["entry_ts"], exit=p.get("exit_ts"), closed=p["closed"], cost=usd,
                     pnl=None if out is None else out - usd, mult=p.get("mult"), hold=p.get("hold"),
                     leader=leader, delay=None if q is None else p["entry_ts"] - q["entry_ts"],
                     lmult=None if q is None else q.get("mult"), lhold=None if q is None else q.get("hold"),
                     open_cost=0 if p["closed"] else usd, realized_open=0 if p["closed"] else p["proceeds"] * SOL))
rows.sort(key=lambda r: r["entry"])
closed = [r for r in rows if r["closed"] and r["pnl"] is not None]
tot_cost = sum(r["cost"] for r in closed)
print(f"\nCERRADAS: {len(closed)} · invertido {tot_cost:.0f} USD · resultado {sum(r['pnl'] for r in closed):+.0f} USD · acierto {100*sum(1 for r in closed if r['pnl']>0)/max(1,len(closed)):.0f} %")
op = [r for r in rows if not r["closed"]]
print(f"ABIERTAS/PARCIALES: {len(op)} · coste {sum(r['cost'] for r in op):.0f} USD · ya cobrado de ellas {sum(r['realized_open'] for r in op):.0f} USD  (si valen 0: {sum(r['realized_open']-r['cost'] for r in op):+.0f} USD)")

print("\nCURVA (resultado acumulado de las cerradas, por semana de salida):")
eq = 0.0
by_week = {}
for r in sorted(closed, key=lambda r: r["exit"] or r["entry"]):
    eq += r["pnl"]
    by_week[time.strftime("%d-%b", time.gmtime((r["exit"] or r["entry"]) // (7 * DAY) * 7 * DAY))] = eq
for k, v in by_week.items():
    print(f"  semana {k}: {v:+.0f} USD")

print("\nPOR WALLET COPIADA (cerradas):")
by = {}
for r in closed:
    by.setdefault(r["leader"] or "sin atribuir", []).append(r)
for w, L in sorted(by.items(), key=lambda kv: sum(r["pnl"] for r in kv[1])):
    pnl = sum(r["pnl"] for r in L)
    dl = [r["delay"] for r in L if r["delay"] is not None]
    gap = [r["mult"] - r["lmult"] for r in L if r["lmult"] is not None and r["mult"] is not None]
    print(f"  {w[:10]:<12} n={len(L):>3} resultado {pnl:+7.0f} USD  acierto {100*sum(1 for r in L if r['pnl']>0)/len(L):3.0f}%  retraso med {statistics.median(dl) if dl else float('nan'):6.0f}s  "
          f"tu múltiplo - el suyo (med) {statistics.median(gap) if gap else float('nan'):+.2f}")

print("\nLAS 10 PEORES OPERACIONES:")
for r in sorted(closed, key=lambda r: r["pnl"])[:10]:
    print(f"  {r['mint'][:8]} {time.strftime('%d-%b %H:%M', time.gmtime(r['entry']))} coste {r['cost']:.0f} -> {r['pnl']:+.0f} USD (x{r['mult']:.2f}) tenencia {((r['hold'] or 0)/60):.0f} min, copiada de {(r['leader'] or '—')[:8]} con {r['delay'] if r['delay'] is not None else '—'} s de retraso")

print("\nTAMAÑO por operación (USD): mediana %.0f, mín %.0f, máx %.0f" % (statistics.median(r["cost"] for r in rows), min(r["cost"] for r in rows), max(r["cost"] for r in rows)))
print("TENENCIA mediana tuya %.1f min" % (statistics.median([(r["hold"] or 0) / 60 for r in closed]) if closed else float("nan")))
json.dump(rows, open("audit_copias_filas.json", "w"), default=str)
