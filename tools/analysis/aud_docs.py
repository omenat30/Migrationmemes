"""Calcula `aud` (métricas de auditoría) de las wallets del panel y la media poblacional para el encogimiento.
Uso: python3 tools/analysis/aud_docs.py <carpeta con deep_*.json> <carpeta con documentos del panel (JSON por wallet)> <salida>
Las bolsas solo entran si el JSON trae posiciones abiertas (los `deep` anteriores al 21-oct solo guardaban cerradas -> bags_known = false)."""
import glob
import json
import os
import statistics
import sys
import time

sys.path.insert(0, ".")
from radar import audit  # noqa: E402

D, DOCS, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
NOW = time.time()
best = {}
for f in sorted(glob.glob(D + "/deep_*.json")):
    try:
        data = json.load(open(f))
    except Exception:
        continue
    for r in data if isinstance(data, list) else []:
        if isinstance(r, dict) and r.get("positions"):
            w = r["metrics"]["wallet"]
            has_open = any(not p.get("closed") for p in r["positions"])
            key = (has_open, len(r["positions"]))
            if w not in best or key > best[w][0]:
                best[w] = (key, r)
aud, stats = {}, {}
for w, (key, r) in best.items():
    a = audit.wallet_audit(r["positions"], NOW)
    if a:
        a["bags_known"] = key[0] or r["metrics"].get("n_open", 0) == 0
        aud[w] = a
        if a["n"] >= 8 and a.get("r_sd") is not None:
            stats[w] = (a["n"], a["r"], a["r_sd"] ** 2)
shr, k, mu = audit.shrink(stats)
os.makedirs(OUT, exist_ok=True)
panel = [os.path.basename(f)[:-5] for f in glob.glob(DOCS + "/*.json")]
n_ok = 0
for w in panel:
    a = aud.get(w)
    if not a:
        continue
    a["rs"] = round(shr[w], 3) if w in shr else a["r"]
    json.dump({"aud": a, "bags_known": a.pop("bags_known")}, open(os.path.join(OUT, w + ".json"), "w"), separators=(",", ":"))
    n_ok += 1
pop = {"n": len(stats), "k": None if k is None else round(k, 2), "mu": None if mu is None else round(mu, 3), "ts": int(NOW)}
json.dump(pop, open(os.path.join(OUT, "_pop.json"), "w"))
print(len(best), "wallets en la caché;", len(stats), "en la población del encogimiento;", n_ok, "documentos del panel con aud;", pop)
