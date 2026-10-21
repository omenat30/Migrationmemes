import json,glob,os,statistics as st,sys
from collections import defaultdict
S="/tmp/claude-0/-home-user/ab827291-fca8-57d8-8c23-dbfa0fc958b5/scratchpad/"
data=json.load(open(S+"migrants3.json"))
known={os.path.basename(f)[:-5] for f in glob.glob(S+"dbfull/*.json")}
G=383*104.2
by=defaultdict(list); tok=defaultdict(list); funders=defaultdict(set)
for m,d in data.items():
    for r in d["rows"]:
        if len(r)<8: continue
        w,b,s,a,e,mi,mo,fu=r
        if not mi: continue
        x=dict(m=m,b=b,s=s,a=a,e=e,mi=mi,mo=mo,band=("temprana" if mi<0.35*G else "media" if mi<0.6*G else "a_punto" if mi<G else "recien" if mi<3*G else "tarde"))
        by[w].append(x); tok[m].append((a,w))
        if fu: funders[fu].add(w)
print(len(data),"tokens ·",len(by),"wallets con compra real >= 100 USD")
bc=defaultdict(int)
for L in by.values():
    for x in L: bc[x["band"]]+=1
print("entradas por franja:",dict(bc))
res=[]
for w,L in by.items():
    near=[x for x in L if x["band"] in ("a_punto","recien")]
    if len(near)<int(sys.argv[1] if len(sys.argv)>1 else 3): continue
    B=sum(x["b"] for x in near); Sx=sum(x["s"] for x in near)
    holds=[(x["e"]-x["a"]) if x["e"] else None for x in near]
    hs=[h for h in holds if h is not None]
    res.append(dict(w=w,n=len(near),n_all=len(L),mult=Sx/B if B else 0,win=sum(1 for x in near if x["s"]>x["b"])/len(near),
        buy=st.median(x["b"] for x in near),hold=(st.median(hs)/60 if hs else None),fast=sum(1 for h in hs if h<=30)/max(1,len(hs)),known=w in known))
res.sort(key=lambda r:(-r["n"],-r["mult"]))
print("\nrepiten entradas cerca de migrar (24k-120k USD de mcap):",len(res))
for r in res[:40]:
    print(f"{r['w']} n={r['n']:>2}/{r['n_all']:<2} x{r['mult']:.2f} acierto {r['win']*100:3.0f}% compra med ${r['buy']:>6.0f} hold med {('%.0f'%r['hold']) if r['hold'] is not None else '-':>5} min rápidas {r['fast']*100:3.0f}%{' · PANEL' if r['known'] else ''}")
# clusters por fondeador (excluye fondeadores con > 30 wallets: exchanges)
cl=[(f,sorted(ws)) for f,ws in funders.items() if 2<=len(ws)<=30]
cl.sort(key=lambda x:-len(x[1]))
print("\nfondeadores comunes (2-30 wallets):",len(cl))
for f,ws in cl[:12]: print(" ",f[:10],len(ws),[w[:8] for w in ws][:8])
# co-entrada <= 2 s en >= 2 tokens
pair=defaultdict(set)
for m,L in tok.items():
    L.sort()
    for i in range(len(L)):
        for j in range(i+1,len(L)):
            if L[j][0]-L[i][0]>2: break
            a,b=sorted((L[i][1],L[j][1]))
            if a!=b: pair[(a,b)].add(m)
pp=sorted([(len(v),a,b) for (a,b),v in pair.items() if len(v)>=2],reverse=True)
print("\npares que entran a la vez (<=2 s) en >=2 tokens:",len(pp))
for n,a,b in pp[:15]: print(f"  {n} tokens: {a[:10]} + {b[:10]}")
json.dump({"res":res,"funders":cl,"pairs":pp},open(S+"pattern3_out.json","w"))
