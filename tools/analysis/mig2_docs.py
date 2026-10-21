import json,glob,os,sys
sys.path.insert(0,"/home/user/memecoin-migration-radar"); sys.path.insert(0,"/tmp/claude-0/-home-user/ab827291-fca8-57d8-8c23-dbfa0fc958b5/scratchpad")
from radar import crossing
from radar.copysim import trade_net
from bands import load_positions
S="/tmp/claude-0/-home-user/ab827291-fca8-57d8-8c23-dbfa0fc958b5/scratchpad/"
net=lambda p: trade_net(1.0 if (p.get("hold") or 0)<=30 else p["mult"],0.09,1.0,2.0,100,60.0)
wal=load_positions(sorted(glob.glob(S+"deep_*.json")))
known=[os.path.basename(f)[:-5] for f in glob.glob(S+"dbread4/wallets/*.json")]
cl=json.load(open(S+"clusters.json"))
out={}
for w in known:
    if w not in wal: continue
    s=crossing.summarize_mcap(wal[w],net_fn=net)
    mig={"pre":s["pre"],"post":s["post"],"cross":s["cross"],"near":s["near"],"bands":{k:s[k] for k,_,_ in crossing.BANDS},"basis":"mcap"}
    d={"mig":mig}
    for i,c in enumerate(cl):
        if w in c: d["cluster"]={"id":"c%d"%(i+1),"members":c,"why":"compran los mismos tokens con menos de 10 s de diferencia"}
    if w.startswith("HAFfm2fP"): d["excluded"]={"why":"vende en segundos tras comprar en la curva temprana: dumpea a quien la copia","ts":1792497600}
    out[w]=d
os.makedirs(S+"mig2_w",exist_ok=True)
for w,d in out.items(): json.dump(d,open(S+f"mig2_w/{w}.json","w"))
print(len(out),"docs; con cluster:",sum(1 for d in out.values() if "cluster" in d))
print(json.dumps(out["DA9nTGVx7NX2siZjMptCS2Pf6kdDgJW8A6Q1BPf8aHxC"]["mig"])[:700])
