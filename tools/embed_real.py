"""Incrusta en dashboard/index.html una CAPTURA DE DATOS REALES de data/radar.sqlite (modo real-snapshot).
Uso:  python tools/embed_real.py   (después de grabar / hacer backfill / ejecutar `study` y `backtest`)
Nada sintético: si no hay datos reales, el panel lo dice en lugar de inventar.
"""
import json, os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from radar.config import load_config
from radar.state import build_state
from radar.store import Store

cfg = load_config("config.json")
st = Store("data/radar.sqlite")
state = build_state(st, cfg, int(time.time()), mode="real-snapshot")
state["candidates"] = state["candidates"]
html = open("dashboard/index.html", encoding="utf-8").read()
blob = json.dumps(state, ensure_ascii=False, separators=(",", ":"), default=str).replace("</", "<\\/")
html = re.sub(r'(<script type="application/json" id="sample">).*?(</script>)', lambda m: m.group(1) + blob + m.group(2), html, flags=re.S)
open("dashboard/index.html", "w", encoding="utf-8").write(html)
print("captura real incrustada:", len(blob) // 1024, "KB | migraciones:", len(state["history"]), "| tokens vigilados:", state["recorder"]["tokens"])
