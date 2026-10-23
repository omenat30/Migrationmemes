"""Segunda pasada de la auditoría de copias: guarda las posiciones en bruto y mide por día, tamaño, mcap de entrada, tenencia y bolsas.
Uso (desde la raíz del proyecto): python3 tools/analysis/audit_copias2.py <wallet> <salida.json>"""
import json
import sys
import time

sys.path.insert(0, ".")
from radar import gmgnwallet  # noqa: E402
from radar.config import load_config  # noqa: E402
from radar.sources.gmgn import Gmgn  # noqa: E402
from radar import discover  # noqa: E402

W, OUT = sys.argv[1], sys.argv[2]
cfg = load_config()
g = Gmgn(cfg)
SOL = 104.2
m, pos = gmgnwallet.analyze(g, W, cfg, SOL, days=60, max_pages=80, early=False)
st = discover._patient(lambda: g.wallet_stats([W], "30d").get(W), log=lambda x: None) or {}
st7 = discover._patient(lambda: g.wallet_stats([W], "7d").get(W), log=lambda x: None) or {}
info = {}
for p in pos:
    if not p["closed"]:
        try:
            info[p["mint"]] = discover._patient(lambda: g.info(p["mint"]), log=lambda x: None)
        except Exception as e:
            info[p["mint"]] = {"err": str(e)[:60]}
json.dump({"metrics": m, "positions": pos, "stats30": st, "stats7": st7, "open_info": info, "ts": time.time()}, open(OUT, "w"), default=str)
print("guardado", OUT, len(pos), "posiciones")
