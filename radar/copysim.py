"""Simulador de copia: ¿qué habría ganado un seguidor que copia las operaciones de una wallet? (HIPOTESIS_v7.md)

Referencia en Python de la lógica que usa el panel (dashboard/copy.html reproduce exactamente estas fórmulas; hay una prueba de
paridad con Node). Una posición es [hora_entrada, tenencia_s, múltiplo, coste_sol].

Supuestos explícitos, todos editables en el panel:
  - Entrada tardía: el seguidor compra `entry_penalty` más caro que la wallet. Valores por defecto MEDIDOS en tokens cerca de
    migrar (mediana del movimiento del precio tras una compra de >=0,3 SOL): +9 % a 30 s, +17 % a 60 s, +20 % a 120 s. Es una
    muestra concreta (tokens que suben hacia la migración): puede no valer para otras wallets.
  - Salida: NO se acredita ninguna mejora por salir después de la wallet (conservador).
  - Comisión 1 % por lado y deslizamiento `impact_per_1k` % por cada 1.000 USD, por lado (SIN VERIFICAR; sube con tu tamaño).
  - Stop opcional del -60 %: recorta la pérdida a -60 % (optimista: en un hundimiento brusco el stop no se ejecuta a ese precio).
  - R = resultado / (stop x tamaño): 1R es lo que pierdes si saltas el stop.
"""
ENTRY_PENALTY = {30: 0.09, 60: 0.17, 120: 0.20}


def trade_net(mult, entry_penalty, fee_pct, impact_per_1k_pct, size_usd, stop_pct=None):
    """Retorno neto (0.10 = +10 %) de copiar una posición con múltiplo bruto `mult` de la wallet."""
    c = fee_pct / 100.0 + (impact_per_1k_pct / 100.0) * (size_usd / 1000.0)
    c = min(c, 0.95)
    net = mult * (1 - c) ** 2 / (1 + entry_penalty) - 1
    if stop_pct is not None:
        net = max(net, -stop_pct / 100.0)
    return net


def simulate(positions, size_usd, delay_s=30, entry_penalty=None, fee_pct=1.0, impact_per_1k_pct=2.0, stop_pct=60.0,
             apply_stop=True, since_ts=None):
    """Simula copiar una lista de posiciones. Devuelve métricas y la curva de capital (ordenada por hora de entrada)."""
    pen = ENTRY_PENALTY.get(delay_s, 0.17) if entry_penalty is None else entry_penalty
    rows = []
    for ts, hold, mult, cost in sorted(positions, key=lambda p: p[0]):
        if since_ts is not None and ts < since_ts:
            continue
        net = trade_net(mult, pen, fee_pct, impact_per_1k_pct, size_usd, stop_pct if apply_stop else None)
        rows.append((ts, net, size_usd * net, net / (stop_pct / 100.0)))
    n = len(rows)
    eq, peak, dd, curve = 0.0, 0.0, 0.0, []
    for ts, _, usd, _ in rows:
        eq += usd
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
        curve.append((ts, eq))
    return {"n": n, "win": (sum(1 for r in rows if r[1] > 0) / n) if n else None,
            "expected_r": (sum(r[3] for r in rows) / n) if n else None,
            "mean_net": (sum(r[1] for r in rows) / n) if n else None,
            "total_usd": eq, "max_drawdown_usd": dd, "curve": curve}
