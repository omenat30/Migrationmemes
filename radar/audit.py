"""Métricas de auditoría de una wallet copiable (AUDITORIA 21-oct-2026; ver HIPOTESIS_v7.md).

Cada función corrige un sesgo concreto de la simulación por defecto de `copysim`/`deepwallet.metrics`:
  - sin stop (C1): sin la trayectoria del precio no se puede saber si una ganadora pasó por -60 % antes de subir, así que el stop retrospectivo
    solo recorta pérdidas. Aquí el suelo es -100 %.
  - bolsas (C3): una posición con ventas < 90 % o sin vender sigue contando; si lleva >= STALE_DAYS sin movimientos se valora PESIMISTA
    (lo realizado; lo que queda, a 0). Sin precio actual del token es una cota inferior, no el valor real.
  - impacto de curva: en la curva de pump.fun comprar S SOL cuesta de media ~ S / v_sol sobre el precio, con v_sol = sqrt(mcap_sol * k / 1e9) y k = 30 * 1.073e9.
  - salida con retraso (EXIT_PEN, provisional hasta medirlo) y comisión por lado (FEE).
  - operación de descubrimiento (C2): se excluye la posición que hizo encontrar la wallet; si no se sabe cuál es, se excluye la de mayor múltiplo (aproximación).
  - estadística: encogimiento (Bayes empírico) hacia la media de la población, bootstrap por bloques de un día, resultado sin el 10 % mejor y % del beneficio en las 3 mejores.
Todos los supuestos de coste son PLACEHOLDERS conservadores: se sustituyen por medidas reales cuando existan (reproducción sobre el tape).
"""
import math
import random
import statistics

DAY = 86400
STALE_DAYS = 7
K_CURVE = 30.0 * 1.073e9
GRAD_SOL = 383.0
FEE = 0.012           # por lado: 1 % + 0,2 % de impacto lineal a 100 USD (como el modelo por defecto)
ENTRY_PEN = 0.09      # retraso de 30 s medido cerca de migrar
EXIT_PEN = 0.05       # PROVISIONAL: precio de salida un 5 % peor por el retraso (sin medir)
SOL_USD = 104.2
DELTA_E = 30.0        # segundos hasta que el seguidor entra (retraso medido cerca de migrar; a mano serán minutos)
DELTA_S = 30.0        # segundos hasta que el seguidor sale


def curve_impact(mcap_sol, size_sol):
    """Sobreprecio medio de comprar size_sol en la curva con ese mcap (0 si el token ya migró o no se conoce)."""
    if not mcap_sol or mcap_sol <= 0 or mcap_sol > GRAD_SOL * 1.15:
        return 0.0
    v = math.sqrt(mcap_sol * K_CURVE / 1e9)
    return min(size_sol / v, 0.5)


def net_return(mult, mcap_sol=None, size_usd=100.0, sol_usd=SOL_USD, entry_pen=None, exit_pen=None, fee=None):
    """Retorno neto de copiar una posición con múltiplo bruto `mult`; sin stop (suelo -100 %). Los costes se leen del módulo en cada llamada."""
    entry_pen = ENTRY_PEN if entry_pen is None else entry_pen
    exit_pen = EXIT_PEN if exit_pen is None else exit_pen
    fee = FEE if fee is None else fee
    pen = entry_pen + curve_impact(mcap_sol, size_usd / sol_usd)
    net = mult * (1 - exit_pen) * (1 - fee) ** 2 / (1 + pen) - 1
    return max(net, -1.0)


def valued_positions(positions, now, stale_days=STALE_DAYS):
    """Posiciones valoradas para la auditoría. Cerradas: su múltiplo. Abiertas/parciales sin movimientos desde hace >= stale_days:
    lo realizado / coste (lo que queda, a 0). Las abiertas recientes se dejan fuera (aún pueden cambiar). Devuelve filas dict."""
    out = []
    for p in positions:
        if not p.get("cost"):
            continue
        last = p.get("exit_ts") or p["entry_ts"]
        if p.get("closed") and p.get("mult") is not None:
            out.append(dict(ts=p["entry_ts"], last=last, mult=p["mult"], cost=p["cost"], hold=p.get("hold") or 0.0, mint=p.get("mint"),
                            em=_em(p), stale=False))
        elif now - last >= stale_days * DAY:
            out.append(dict(ts=p["entry_ts"], last=last, mult=(p.get("proceeds") or 0.0) / p["cost"], cost=p["cost"], hold=p.get("hold") or 0.0,
                            mint=p.get("mint"), em=_em(p), stale=True))
    return sorted(out, key=lambda r: r["ts"])


def _em(p):
    if p.get("bought") and p.get("cost"):
        em = p["cost"] / p["bought"] * 1e9
        return em if em <= 1e6 else None  # supply distinta de 1.000 M: no es un token estándar de pump.fun
    return None


def drop_trigger(rows, trigger_mints=None):
    """Quita la operación que hizo descubrir la wallet (C2). Sin dato: la de mayor múltiplo."""
    if not rows:
        return rows, None
    if trigger_mints:
        keep = [r for r in rows if r["mint"] not in set(trigger_mints)]
        if len(keep) < len(rows):
            return keep, "token disparador"
    i = max(range(len(rows)), key=lambda j: rows[j]["mult"])
    return rows[:i] + rows[i + 1:], "mejor operación (aproximación)"


def copiable(rows):
    """Tenencia frente a tu latencia (AUDITORIA): < DELTA_E la wallet ya salió cuando entrarías -> no se copia (fuera);
    < DELTA_E + DELTA_S -> no hay ventaja que capturar, solo costes (múltiplo 1). Devuelve (filas, nº fuera)."""
    out, skipped = [], 0
    for r in rows:
        h = r.get("hold")
        if h is not None and h < DELTA_E:
            skipped += 1
        elif h is not None and h < DELTA_E + DELTA_S:
            out.append(dict(r, mult=1.0))
        else:
            out.append(r)
    return out, skipped


def copy_returns(rows, size_usd=100.0):
    """R por operación (neto / 0,60) y el neto, en el orden de entrada."""
    nets = [net_return(r["mult"], r.get("em"), size_usd) for r in rows]
    return [n / 0.60 for n in nets], nets


def winsor(xs, cap=10.0):
    return [max(-cap, min(cap, x)) for x in xs]


def day_block_bootstrap(rows, rs, n_boot=1000, seed=7):
    """Percentil 5 del R medio remuestreando DÍAS completos (las operaciones del mismo día están correlacionadas)."""
    if len(rs) < 5:
        return None
    days = {}
    for r, x in zip(rows, rs):
        days.setdefault(r["ts"] // DAY, []).append(x)
    blocks = list(days.values())
    rnd = random.Random(seed)
    means = []
    for _ in range(n_boot):
        pick = [blocks[rnd.randrange(len(blocks))] for _ in blocks]
        tot = sum(len(b) for b in pick)
        means.append(sum(sum(b) for b in pick) / tot if tot else 0.0)
    means.sort()
    return means[int(0.05 * n_boot)]


def top_share(nets, rows, k=3):
    """% del beneficio positivo total que está en las k mejores operaciones (en USD de 100 por operación, ponderado por nada: neto)."""
    gains = sorted((x for x in nets if x > 0), reverse=True)
    tot = sum(gains)
    return (sum(gains[:k]) / tot) if tot > 0 else None


def ex_top_fraction(nets, frac=0.10, min_drop=2):
    """Suma de los netos quitando el mejor `frac` de operaciones (mínimo `min_drop`)."""
    if len(nets) <= min_drop:
        return None
    k = max(min_drop, int(math.ceil(frac * len(nets))))
    s = sorted(nets, reverse=True)
    return sum(s[k:]) if len(s) > k else None


def wallet_audit(positions, now, size_usd=100.0, trigger_mints=None, exclude_trigger=True, stale_days=STALE_DAYS):
    """Resumen de auditoría de una wallet a partir de sus posiciones. Devuelve un dict con todo lo que pinta el panel."""
    rows = valued_positions(positions, now, stale_days)
    rows, how = drop_trigger(rows, trigger_mints) if exclude_trigger else (rows, None)
    rows, skipped = copiable(rows)
    if not rows:
        return None
    rs, nets = copy_returns(rows, size_usd)
    cost = sum(r["cost"] for r in rows)
    roi_pess = sum(r["cost"] * (r["mult"] - 1) for r in rows) / cost if cost else None
    ex10 = ex_top_fraction(nets)
    return {
        "n": len(rows), "n_skip": skipped, "n_stale": sum(1 for r in rows if r["stale"]), "excl": how,
        "roi_pess": None if roi_pess is None else round(roi_pess, 3),
        "r": round(sum(rs) / len(rs), 3), "r_sd": round(statistics.pstdev(winsor(rs)), 3) if len(rs) > 1 else None,
        "r_w": round(sum(winsor(rs)) / len(rs), 3),
        "p5": None if (b := day_block_bootstrap(rows, winsor(rs))) is None else round(b, 3),
        "ex10": None if ex10 is None else round(ex10 * size_usd, 1), "top3": None if (t := top_share(nets, rows)) is None else round(t, 3),
        "usd": round(sum(nets) * size_usd, 1),
    }


def shrink(stats, k=None):
    """Encogimiento hacia la media de la población. stats: {id: (n, mean_R, var_R)}. k = sigma2_dentro / tau2_entre (si no se da, se estima).
    Devuelve ({id: R_encogido}, k, media_poblacion)."""
    items = [(i, n, m, v) for i, (n, m, v) in stats.items() if n and m is not None and v is not None]
    if len(items) < 3:
        return {i: m for i, (n, m, v) in stats.items()}, None, None
    mu = sum(m for _, _, m, _ in items) / len(items)
    within = sum(v for _, n, _, v in items) / len(items)                      # varianza media de una operación
    noise = sum(v / n for _, n, _, v in items) / len(items)                    # ruido muestral medio de las medias
    between = max(statistics.pvariance([m for _, _, m, _ in items]) - noise, 1e-9)
    kk = k if k is not None else within / between
    return {i: (n / (n + kk)) * m + (kk / (n + kk)) * mu for i, n, m, _ in items}, kk, mu


def spearman(a, b):
    """Correlación de rangos (con empates promediados) entre dos listas del mismo largo."""
    def ranks(x):
        order = sorted(range(len(x)), key=lambda i: x[i])
        r = [0.0] * len(x)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and x[order[j + 1]] == x[order[i]]:
                j += 1
            for t in range(i, j + 1):
                r[order[t]] = (i + j) / 2.0 + 1
            i = j + 1
        return r
    if len(a) < 3:
        return None
    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va, vb = sum((x - ma) ** 2 for x in ra), sum((y - mb) ** 2 for y in rb)
    return cov / math.sqrt(va * vb) if va > 0 and vb > 0 else None


def spearman_perm_p(a, b, n_perm=2000, seed=11):
    """p-valor (una cola, correlación > 0) por permutación de la correlación de rangos. None si no se puede calcular."""
    obs = spearman(a, b)
    if obs is None:
        return None, None
    rnd = random.Random(seed)
    b2 = list(b)
    ge = 0
    for _ in range(n_perm):
        rnd.shuffle(b2)
        c = spearman(a, b2)
        if c is not None and c >= obs:
            ge += 1
    return obs, (ge + 1) / (n_perm + 1)
