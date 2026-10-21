"""Verifica candidatas «cerca de migrar» a partir de la salida de `radar deep --source gmgn` y prepara documentos del panel."""
import json,sys,os,time
sys.path.insert(0,"/home/user/memecoin-migration-radar")
from radar import crossing, sweep
from radar.config import load_config
from radar.copysim import trade_net
S="/tmp/claude-0/-home-user/ab827291-fca8-57d8-8c23-dbfa0fc958b5/scratchpad/"
cfg=load_config()
net=lambda p: trade_net(1.0 if (p.get("hold") or 0)<=30 else p["mult"],0.09,1.0,2.0,100,60.0)
def near_check(pos):
    rows=sorted([p for p in pos if p.get("closed") and p.get("mult") is not None and crossing.band(crossing.entry_mcap_sol(p)) in ("a_punto","recien")],key=lambda p:p["entry_ts"])
    if len(rows)<4: return None
    nets=[net(p) for p in rows]; srt=sorted(nets,reverse=True); mid=len(rows)//2
    er=lambda xs: sum(x/0.6 for x in xs)/len(xs) if xs else None
    return dict(n=len(rows),er=er(nets),er2=er(srt[2:]),h1=er(nets[:mid]),h2=er(nets[mid:]),
                fast=sum(1 for p in rows if (p.get("hold") or 0)<=30)/len(rows),win=sum(1 for p in rows if p["mult"]>1)/len(rows),
                days=(rows[-1]["entry_ts"]-rows[0]["entry_ts"])/86400)
def ok_near(c):
    return c and c["n"]>=15 and c["er"]>=0.3 and c["er2"]>0 and c["h1"]>0 and c["h2"]>0 and c["fast"]<=0.35
if __name__=="__main__":
    res=json.load(open(sys.argv[1])); clusters=json.load(open(sys.argv[2])) if len(sys.argv)>2 else []
    out=[]
    for r in res:
        m,pos=r["metrics"],r["positions"]; c=near_check(pos)
        out.append((m["wallet"],c,ok_near(c),m))
        f=lambda v:"—" if v is None else f"{v:+.2f}"
        if c: print(f"{m['wallet']} cerca n={c['n']:>3} R {f(c['er'])} sin2 {f(c['er2'])} mitades {f(c['h1'])}/{f(c['h2'])} rápidas {c['fast']*100:.0f}% acierto {c['win']*100:.0f}% en {c['days']:.0f} d | total {m['n_closed']} op, roi {m['roi']*100 if m['roi'] is not None else 0:.0f}% {'<<< CUMPLE' if ok_near(c) else ''}")
        else: print(f"{m['wallet']} sin entradas cerca de migrar ({m['n_closed']} op.)")
    keep=[r for r,(w,c,ok,m) in zip(res,out) if ok]
    print("cumplen:",len(keep),"de",len(res))
    if keep:
        docs,meta=sweep.build_docs(keep,{},cfg,sol_usd=104.2)
        for w,d in docs.items():
            s=crossing.summarize_mcap([p for p in next(x for x in keep if x["metrics"]["wallet"]==w)["positions"]],net_fn=net)
            d["mig"]={"pre":s["pre"],"post":s["post"],"cross":s["cross"],"near":s["near"],"bands":{k:s[k] for k,_,_ in crossing.BANDS},"basis":"mcap"}
            d["source_tag"]="cerca de migrar"
            for i,cl in enumerate(clusters):
                if w in cl["members"]: d["cluster"]={"id":cl["id"],"members":cl["members"],"why":cl["why"]}
        os.makedirs(S+"near_docs",exist_ok=True)
        for w,d in docs.items(): json.dump(d,open(S+f"near_docs/{w}.json","w"),separators=(",",":"))
        print("documentos:",len(docs),"status:",{w:d["status"] for w,d in docs.items()})
