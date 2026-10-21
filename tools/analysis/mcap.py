import json,sys,statistics as st
sys.path.insert(0,"/home/user/memecoin-migration-radar")
from radar.copysim import trade_net
S="/tmp/claude-0/-home-user/ab827291-fca8-57d8-8c23-dbfa0fc958b5/scratchpad/"
w="HAFfm2fPfpTKjcHVmJivDPHT8Lx2yfxmVDigbG958JJV"
pos=None
for r in json.load(open(S+"deep_co3.json")):
    if r["metrics"]["wallet"]==w: pos=r["positions"]
SOL=105.0
rows=[]
for p in pos:
    if not p.get("closed") or p.get("mult") is None or not p["bought"] or not p["sold"]: continue
    em=p["cost"]/p["bought"]*1e9*SOL
    xm=p["proceeds"]/p["sold"]*1e9*SOL
    rows.append(dict(ts=p["entry_ts"],hold=p["hold"] or 0,mult=p["mult"],cost=p["cost"],em=em,xm=xm))
rows.sort(key=lambda r:r["ts"])
print(len(rows),"posiciones; mcap entrada mediana $%.0f"%st.median(r["em"] for r in rows))
qs=st.quantiles([r["em"] for r in rows],n=10); print("deciles mcap entrada:",[round(q) for q in qs])
def stats(rs,pen=0.09):
    if not rs: return None
    nets=[trade_net(r["mult"],pen,1.0,2.0,100,60.0) for r in rs]
    c=sum(r["cost"] for r in rs)
    srt=sorted(nets,reverse=True)
    return dict(n=len(rs),win=sum(1 for r in rs if r["mult"]>1)/len(rs),roi=sum(r["cost"]*(r["mult"]-1) for r in rs)/c,
      ER=sum(n/0.6 for n in nets)/len(nets),usd=sum(n*100 for n in nets),usd_ex2=sum(n*100 for n in srt[2:]),
      hold=st.median(r["hold"] for r in rs)/60,xm=st.median(r["xm"] for r in rs),em=st.median(r["em"] for r in rs))
def show(tag,rs):
    s=stats(rs)
    if not s: print(tag,"-"); return
    print(f"{tag:<22} n={s['n']:>3} acierto={s['win']*100:3.0f}% ROIwallet={s['roi']*100:+5.0f}% ER={s['ER']:+.2f} USD100={s['usd']:+8.0f} sin2={s['usd_ex2']:+7.0f} hold={s['hold']:.1f}m mcap_sal_med=${s['xm']:.0f}")
edges=[0,4000,5000,6000,7000,8000,10000,15000,25000,50000,1e12]
print("\n== por tramo de mcap de entrada (copiando con 30 s de retraso, 100 USD) ==")
for a,b in zip(edges,edges[1:]): show(f"${a:.0f}-{b:.0f}" if b<1e11 else f">${a:.0f}",[r for r in rows if a<=r["em"]<b])
print("\n== umbral mínimo: copiar solo si mcap entrada >= X ==")
for x in [0,4000,5000,6000,7000,8000,10000,15000,25000]: show(f">= ${x}",[r for r in rows if r["em"]>=x])
print("\n== con el retraso el mcap sube ~9%: efecto de pen 17% (60 s) ==")
for x in [0,6000,8000,10000]:
    rs=[r for r in rows if r["em"]>=x]; s=stats(rs,0.17); print(f">= ${x} 60s: ER={s['ER']:+.2f} USD={s['usd']:+.0f} n={s['n']}")
mid=rows[len(rows)//2]["ts"]
print("\n== fuera de muestra: elegir umbral en 1ª mitad, probar en 2ª ==")
A=[r for r in rows if r["ts"]<mid]; B=[r for r in rows if r["ts"]>=mid]
for x in [0,5000,6000,8000,10000,15000]:
    sa=stats([r for r in A if r["em"]>=x]); sb=stats([r for r in B if r["em"]>=x])
    print(f">= ${x:<6} 1ªmitad: n={sa['n']:>3} ER={sa['ER']:+.2f} | 2ªmitad: "+(f"n={sb['n']:>3} ER={sb['ER']:+.2f} USD={sb['usd']:+.0f}" if sb else "-"))
json.dump(rows,open(S+"mcap_rows.json","w"))
