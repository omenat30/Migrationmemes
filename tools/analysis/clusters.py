import json,glob,sys
from collections import defaultdict
sys.path.insert(0,"/tmp/claude-0/-home-user/ab827291-fca8-57d8-8c23-dbfa0fc958b5/scratchpad")
from bands import load_positions
S="/tmp/claude-0/-home-user/ab827291-fca8-57d8-8c23-dbfa0fc958b5/scratchpad/"
wal=load_positions(sorted(glob.glob(S+"deep_*.json")))
ent={w:{p["mint"]:p["entry_ts"] for p in ps if p.get("mint")} for w,ps in wal.items()}
ws=sorted(ent); print(len(ws),"wallets con posiciones")
res=[]
for i,a in enumerate(ws):
    for b in ws[i+1:]:
        sh=set(ent[a])&set(ent[b])
        if len(sh)<5: continue
        near=sum(1 for m in sh if abs(ent[a][m]-ent[b][m])<=10)
        small=min(len(ent[a]),len(ent[b]))
        res.append((near,len(sh),near/small,a,b,len(ent[a]),len(ent[b])))
res.sort(key=lambda r:-r[0])
print("co-entrada <=10 s | tokens compartidos | % de la wallet menor | A | B")
for r in res[:30]:
    if r[0]<5: break
    print(f"{r[0]:>4} | {r[1]:>4} | {r[2]*100:4.0f}% | {r[3][:10]} ({r[5]}) | {r[4][:10]} ({r[6]})")
par={}
def f(x):
    while par.setdefault(x,x)!=x: x=par[x]
    return x
for near,sh,frac,a,b,_,_ in res:
    if near>=10 and frac>=0.2: par[f(a)]=f(b)
comp=defaultdict(list)
for x in list(par): comp[f(x)].append(x)
cl=[sorted(v) for v in comp.values() if len(v)>1]
print("\nclusters (co-entrada <=10 s en >=10 tokens y >=20 % de la wallet menor):")
for c in cl: print("  ",[w for w in c])
json.dump(cl,open(S+"clusters.json","w"))
