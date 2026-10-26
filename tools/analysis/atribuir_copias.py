import json,collections,statistics as st,sys
S=sys.argv[1];SOL=100.9
rec=json.load(open(S+"/deep_recent.json"));u=json.load(open(S+"/user_positions_26.json"))["positions"]
by={r["metrics"]["wallet"]:{p["mint"]:p for p in r.get("positions") or []} for r in rec}
med=lambda v:st.median(v) if v else float("nan")
rows=[]
for p in u:
    c=[]
    for w,pm in by.items():
        q=pm.get(p["mint"])
        if q and -120<=p["entry_ts"]-q["entry_ts"]<=1800: c.append((p["entry_ts"]-q["entry_ts"],w,q))
    c.sort(key=lambda x:x[0])
    rows.append((p,c))
att=[(p,c) for p,c in rows if c]
print("compras atribuibles:",len(att),"de",len(rows),"| cerradas atribuibles",sum(1 for p,c in att if p["closed"]),"de",sum(1 for p,c in rows if p["closed"]))
W=collections.defaultdict(list)
for p,c in att: W[c[0][1]].append((p,c[0][0],c[0][2],len(c)))
out=[]
for w,v in W.items():
    cl=[x for x in v if x[0]["closed"]]
    if not cl: continue
    pn=[(x[0]["proceeds"]-x[0]["cost"])*SOL for x in cl]
    out.append((sum(pn),w,len(cl),sum(x>0 for x in pn),med([x[1] for x in cl]),med([x[0]["hold"] for x in cl])/60,med([x[2]["hold"]/60 for x in cl if x[2].get("hold")]),med([x[2]["mult"] for x in cl if x[2].get("mult")]),sum(x[3]>1 for x in cl)))
print("%-9s %3s %4s %7s %6s %8s %9s %s"%("wallet","n","gan","result","acier","retraso","mi tenenc","lider: tenencia/mult | n con varios lideres"))
for r in sorted(out):
    print("%-9s %3d %4d %+7.0f %5.0f%% %6.0fs %7.0fm   %.0fm x%.2f | %d"%(r[1][:8],r[2],r[3],r[0],100*r[3]/r[2],r[4],r[5],r[6],r[7],r[8]))
print("total atribuido cerradas: %+.0f USD"%sum(r[0] for r in out))
na=[p for p,c in rows if not c and p["closed"]]
print("sin atribuir:",len(na),"%+.0f USD"%(sum(p["proceeds"]-p["cost"] for p in na)*SOL))
json.dump({w:[(x[0]["mint"],x[1]) for x in v] for w,v in W.items()},open(S+"/attrib2.json","w"))
