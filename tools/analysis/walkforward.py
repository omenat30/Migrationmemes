"""Walk-forward sobre la caché de historiales (AUDITORIA 21-oct-2026, punto P0).

Para cada fecha de corte T: con SOLO lo conocido en T (posiciones cerradas con salida <= T) se aplican las reglas por defecto y las reglas de
auditoría, y después se mide, copiando SOLO las posiciones que se abren DESPUÉS de T, si las elegidas siguen siendo buenas.
Ojo, límite del propio método: las wallets de la caché ya fueron elegidas mirando los 60 días COMPLETOS (incluido el tramo posterior a T).
Un resultado nulo aquí es muy grave; uno positivo es una cota optimista, no una prueba.
Uso: python3 tools/analysis/walkforward.py <carpeta con deep_*.json> [fecha_ahora_epoch]
"""
import glob
import json
import statistics
import sys
import time

sys.path.insert(0, ".")
from radar import audit, copysim  # noqa: E402

DAY = 86400
SOFT = "--soft" in sys.argv   # costes suaves: sin impacto de curva ni retraso de salida (solo para medir la sensibilidad)
sys.argv = [x for x in sys.argv if x != "--soft"]
if SOFT:
    audit.EXIT_PEN = 0.0
    audit.curve_impact = lambda *a, **k: 0.0
D = sys.argv[1] if len(sys.argv) > 1 else "."
NOW = float(sys.argv[2]) if len(sys.argv) > 2 else time.time()


def load(folder):
    best = {}
    for f in sorted(glob.glob(folder + "/deep_*.json")):
        try:
            data = json.load(open(f))
        except Exception:
            continue
        for r in data if isinstance(data, list) else []:
            if isinstance(r, dict) and r.get("positions"):
                w = r["metrics"]["wallet"]
                if w not in best or len(r["positions"]) > len(best[w]["positions"]):
                    best[w] = r
    return best


def default_select(pre):
    """Reglas por defecto aplicadas a lo conocido en T (cerradas con salida <= T). Devuelve (cumple, R por defecto)."""
    closed = [p for p in pre if p.get("mult") is not None]
    if len(closed) < 15:
        return False, None
    cost = sum(p["cost"] for p in closed)
    roi = sum(p["proceeds"] - p["cost"] for p in closed) / cost if cost else None
    holds = [p["hold"] for p in closed if p.get("hold") is not None]
    cp = [[p["entry_ts"], p.get("hold") or 0.0, p["mult"], p["cost"]] for p in closed]
    full = copysim.simulate(cp, 100, 30)
    ex2 = copysim.simulate(sorted(cp, key=lambda x: -x[2])[2:], 100, 30)
    ok = (roi is not None and roi >= 0.30 and holds and statistics.median(holds) >= 300
          and sum(1 for h in holds if h < 120) / len(holds) <= 0.35 and full["expected_r"] >= 0.10 and ex2["total_usd"] > 0)
    return bool(ok), full["expected_r"]


def run(T, wal):
    rows = []
    for w, r in wal.items():
        pos = r["positions"]
        pre = [p for p in pos if p.get("closed") and p.get("mult") is not None and (p.get("exit_ts") or 0) <= T]
        post = [p for p in pos if p["entry_ts"] > T]
        ok, r_def = default_select(pre)
        hl = [p["hold"] for p in pre if p.get("hold") is not None]
        copiable = bool(hl) and statistics.median(hl) >= 300 and sum(1 for h in hl if h < 120) / len(hl) <= 0.35
        a_pre = audit.wallet_audit(pre, T) if len(pre) >= 15 else None
        # el tramo posterior se mide SIN quitar la mejor operación (esa exclusión es solo para el tramo de elección)
        a_post = audit.wallet_audit(post, NOW, exclude_trigger=False) if len(post) >= 5 else None
        a_post_nobag = audit.wallet_audit(post, NOW, exclude_trigger=False, stale_days=10 ** 6) if len(post) >= 5 else None  # sin bolsas: solo cerradas
        # resultado posterior "por defecto" (con stop) y de auditoría (sin stop, costes realistas) sobre las MISMAS posiciones posteriores
        post_closed = [p for p in post if p.get("closed") and p.get("mult") is not None]
        sim_def = copysim.simulate([[p["entry_ts"], p.get("hold") or 0.0, p["mult"], p["cost"]] for p in post_closed], 100, 30) if len(post_closed) >= 5 else None
        rows.append(dict(w=w, n_pre=len(pre), ok=ok, copiable=copiable, a_post_nobag=a_post_nobag, r_def=r_def, a_pre=a_pre, a_post=a_post,
                         post_def=None if not sim_def else sim_def["expected_r"], n_post=len(post_closed)))
    return rows


def summarize(T, rows):
    cand = [x for x in rows if x["r_def"] is not None and x["a_post"] is not None]
    out = {"T": time.strftime("%d-%m", time.gmtime(T)), "candidatas": len(cand)}
    if len(cand) < 8:
        return out
    # persistencia: correlación de rangos entre el R antes (reglas por defecto) y el R después (auditoría)
    out["spearman_def"] = audit.spearman([x["r_def"] for x in cand], [x["a_post"]["r"] for x in cand])
    # lo mismo con el R de auditoría antes (sin stop, sin la mejor operación, costes realistas)
    ca = [x for x in cand if x["a_pre"] is not None]
    out["spearman_aud"] = audit.spearman([x["a_pre"]["r"] for x in ca], [x["a_post"]["r"] for x in ca]) if len(ca) >= 8 else None
    # solo wallets que un seguidor podría copiar (tenencia mediana >= 5 min en lo conocido en T)
    out["spearman_copiables_def"] = None
    cc = [x for x in cand if x["copiable"]]
    out["copiables"] = len(cc)
    if len(cc) >= 8:
        out["spearman_copiables_def"] = audit.spearman([x["r_def"] for x in cc], [x["a_post"]["r"] for x in cc])
        cca = [x for x in cc if x["a_pre"] is not None]
        out["spearman_copiables_aud"] = audit.spearman([x["a_pre"]["r"] for x in cca], [x["a_post"]["r"] for x in cca]) if len(cca) >= 8 else None
        if len(cca) >= 8:
            _, pv = audit.spearman_perm_p([x["a_pre"]["r"] for x in cca], [x["a_post"]["r"] for x in cca])
            out["p_perm_aud"] = None if pv is None else round(pv, 4)
            out["n_aud"] = len(cca)
        mid = statistics.median(x["r_def"] for x in cc)
        hi = [x for x in cc if x["r_def"] >= mid]; lo = [x for x in cc if x["r_def"] < mid]
        out["copiables_mitad_alta_vs_baja"] = [round(statistics.mean(x["a_post"]["r"] for x in hi), 3), len(hi), round(statistics.mean(x["a_post"]["r"] for x in lo), 3), len(lo)]
    # descomposición: R posterior de las copiables con (i) auditoría completa, (ii) sin bolsas (solo cerradas, sin stop), (iii) por defecto (con stop, solo cerradas)
    if cc:
        mean = lambda xs: round(statistics.mean(xs), 3)
        out["post_copiables_R"] = {"auditoria": mean([x["a_post"]["r"] for x in cc]),
                                   "sin_bolsas": mean([x["a_post_nobag"]["r"] for x in cc if x["a_post_nobag"]]),
                                   "por_defecto_con_stop": mean([x["post_def"] for x in cc if x["post_def"] is not None])}
    sel = [x for x in cand if x["ok"]]
    rest = [x for x in cand if not x["ok"]]
    f = lambda xs: (round(statistics.mean(x["a_post"]["r"] for x in xs), 3), len(xs)) if xs else (None, 0)
    out["elegidas_por_defecto"] = f(sel)
    out["no_elegidas"] = f(rest)
    top = sorted(sel, key=lambda x: -x["r_def"])[:10]
    out["top10_por_R_en_T"] = f(top)
    # lo que habría visto el panel después (con stop): para ver cuánto del resultado «bueno» es el stop retrospectivo
    g = lambda xs: round(statistics.mean(x["post_def"] for x in xs if x["post_def"] is not None), 3) if xs else None
    out["elegidas_R_con_stop"] = g(sel)
    out["no_elegidas_R_con_stop"] = g(rest)
    # con encogimiento + p5 positivo (regla de auditoría) sobre lo conocido en T
    stats = {x["w"]: (x["a_pre"]["n"], x["a_pre"]["r"], (x["a_pre"]["r_sd"] or 0) ** 2) for x in ca}
    shr, k, mu = audit.shrink(stats)
    aud_sel = [x for x in ca if x["a_pre"]["p5"] is not None and x["a_pre"]["p5"] > 0 and (x["a_pre"]["ex10"] or -1) > 0 and shr.get(x["w"], -1) > 0]
    out["elegidas_por_auditoria"] = f(aud_sel)
    out["elegidas_por_auditoria_top10"] = f(sorted(aud_sel, key=lambda x: -shr[x["w"]])[:10])
    out["k_encogimiento"] = None if k is None else round(k, 1)
    return out


if __name__ == "__main__":
    wal = load(D)
    print(len(wal), "wallets en la caché")
    for days in (35, 28, 21, 14):
        T = NOW - days * DAY
        print(json.dumps(summarize(T, run(T, wal)), ensure_ascii=False))
