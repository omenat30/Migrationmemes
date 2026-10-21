import sys,json,time,os
sys.path.insert(0,"/home/user/memecoin-migration-radar")
from radar.config import load_config
from radar.sources.gmgn import Gmgn
from radar import discover
S="/tmp/claude-0/-home-user/ab827291-fca8-57d8-8c23-dbfa0fc958b5/scratchpad/"
g=Gmgn(load_config("/home/user/memecoin-migration-radar/config.json"))
f=S+"live_trades.json"
tr=json.load(open(f)) if os.path.exists(f) else {}
log=lambda m: print(time.strftime("%H:%M:%S"),m,flush=True)
for k in range(int(sys.argv[1])):
    new=0
    for ep in ("smartmoney","kol"):
        try: d=discover._patient(lambda: g._request("GET","/v1/user/"+ep,{"chain":"sol","limit":100}),log=lambda m:None)
        except Exception as e: log(f"{ep} error {str(e)[:60]}"); continue
        for r in (d.get("list") or []):
            h=r.get("transaction_hash")
            if not h or h in tr: continue
            bt=r.get("base_token") or {}
            sup=float(bt.get("total_supply") or 0); p=float(r.get("price_usd") or 0)
            tr[h]={"w":r.get("maker"),"side":r.get("side"),"t":r.get("timestamp"),"mint":r.get("base_address"),"sym":bt.get("symbol"),
                   "usd":float(r.get("amount_usd") or 0),"mc":round(p*sup) if sup and p else None,"lp":bt.get("launchpad"),"src":ep,
                   "tags":(r.get("maker_info") or {}).get("tags")}
            new+=1
    json.dump(tr,open(f,"w"))
    log(f"ronda {k+1}: +{new} · {len(tr)} operaciones · {len({v['w'] for v in tr.values()})} wallets")
    time.sleep(25)
