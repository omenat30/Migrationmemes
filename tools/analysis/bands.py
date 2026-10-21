import json,glob,os,sys,statistics as st
sys.path.insert(0,"/home/user/memecoin-migration-radar")
from radar.copysim import trade_net
S="/tmp/claude-0/-home-user/ab827291-fca8-57d8-8c23-dbfa0fc958b5/scratchpad/"
G=383.0
BANDS=[("temprana",0,0.35),("media",0.35,0.6),("a_punto",0.6,1.0),("recien",1.0,3.0),("tarde",3.0,1e9)]
def band(x):
    for k,a,b in BANDS:
        if a*G<=x<b*G: return k
def load_positions(files):
    wal={}
    for f in files:
        try: data=json.load(open(f))
        except Exception: continue
        for r in data if isinstance(data,list) else []:
            if isinstance(r,dict) and "metrics" in r and r.get("positions"):
                w=r["metrics"]["wallet"]
                if w not in wal or len(r["positions"])>len(wal[w]): wal[w]=r["positions"]
    return wal
def rows_of(ps):
    out=[]
    for p in ps:
        if not p.get("closed") or p.get("mult") is None or not p.get("bought") or not p.get("cost"): continue
        em=p["cost"]/p["bought"]*1e9; xm=(p["proceeds"]/p["sold"]*1e9) if p.get("sold") else None
        if em>1e6: continue   # supply distinta de 1.000 M: no es pump.fun estándar
        out.append(dict(ts=p["entry_ts"],hold=p.get("hold") or 0,mult=p["mult"],cost=p["cost"],em=em,xm=xm,b=band(em)))
    return sorted(out,key=lambda r:r["ts"])
def stat(rs,pen=0.09):
    if not rs: return None
    nets=[trade_net(1.0 if r["hold"]<=30 else r["mult"],pen,1,2,100,60) for r in rs]   # <=30 s: la wallet ya salió, sin ventaja
    c=sum(r["cost"] for r in rs); srt=sorted(nets,reverse=True)
    return dict(n=len(rs),roi=round(sum(r["cost"]*(r["mult"]-1) for r in rs)/c,3),win=round(sum(1 for r in rs if r["mult"]>1)/len(rs),3),
                er=round(sum(x/0.6 for x in nets)/len(nets),3),er2=round(sum(x/0.6 for x in srt[2:])/max(1,len(nets)-2),3) if len(nets)>2 else None,
                usd=round(sum(x*100 for x in nets)),fast=round(sum(1 for r in rs if r["hold"]<=30)/len(rs),3),hold=round(st.median(r["hold"] for r in rs)/60,1))
def summary(ps):
    rs=rows_of(ps); out={k:stat([r for r in rs if r["b"]==k]) for k,_,_ in BANDS}
    near=[r for r in rs if r["b"] in ("a_punto","recien")]
    out["near"]=stat(near)
    if len(near)>=8:
        mid=near[len(near)//2]["ts"]; out["near_h1"]=stat([r for r in near if r["ts"]<mid]); out["near_h2"]=stat([r for r in near if r["ts"]>=mid])
    out["n"]=len(rs)
    return out
if __name__=="__main__":
    wal=load_positions(sorted(glob.glob(S+"deep_*.json")))
    known=[os.path.basename(f)[:-5] for f in glob.glob(S+"dbread4/wallets/*.json")]
    res={w:summary(wal[w]) for w in known if w in wal}
    json.dump(res,open(S+"bands_db.json","w"))
    print("wallet       n  | temprana        | media           | a_punto         | recien          | tarde   || near ER (ER sin2) usd  h1/h2")
    def f(s): return f"{s['n']:>3} {s['er']:+5.2f}" if s else "  -      "
    for w,v in sorted(res.items(),key=lambda kv:-((kv[1]["near"] or {}).get("usd") or -1e9)):
        nr=v["near"]
        print(f"{w[:10]} {v['n']:>4} | "+" | ".join(f(v[k]) for k,_,_ in BANDS)+(f" || {nr['n']:>3} {nr['er']:+.2f} ({nr['er2']}) {nr['usd']:+6d} fast {nr['fast']*100:.0f}%" if nr else "")+(f"  {v['near_h1']['er']:+.2f}/{v['near_h2']['er']:+.2f}" if v.get('near_h1') else ""))
