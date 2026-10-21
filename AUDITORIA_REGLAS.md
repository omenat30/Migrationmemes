# Auditoría técnica: cómo se eligen las wallets copiables

Documento autocontenido para que una persona o una IA audite la metodología **sin acceso a la conversación original**.
Escrito el 21-oct-2026. Todo lo descrito está implementado en este repositorio (se indica archivo y función). Los números concretos
(umbrales) son los valores por defecto del código en esa fecha. Al final hay una lista de debilidades conocidas y de preguntas concretas.

## 0. Qué es y qué NO es

- **Qué es:** un panel en vivo (`dashboard/copy.html`, publicado como artefacto) que lista wallets de Solana del ecosistema pump.fun que, según su
  historial de los últimos 60 días, habrían sido **rentables de copiar** con un importe fijo por operación (por defecto 100 USD), y simula cuánto se habría
  ganado copiándolas. Un barrido (`python -m radar daily`) añade wallets nuevas y retira las que dejan de cumplir.
- **Qué NO es:** no ejecuta ninguna compra ni venta. No hay claves de firma en el proyecto. Es una **simulación retrospectiva** con supuestos explícitos.
  Nada de lo que se muestra es una expectativa fuera de muestra demostrada (ver §8).
- **Objetivo del usuario:** copiar manualmente (o con copy-trading de un tercero) wallets con alta rentabilidad por operación **sin que el seguidor sea la
  liquidez de salida** (tenencia mínima de ~5 min y pocas salidas inmediatas), con un mínimo de operaciones y de historial.

## 1. Flujo completo

```
fuentes de candidatas (§3) ──► prefiltro barato (GMGN wallet_stats 30 d) ──► historial completo 60 d (GMGN wallet_activity o Helius)
   ──► posiciones por token (§4) ──► métricas (§4) ──► filtros por defecto (§5) ──► simulación de copia (§6) ──► documentos en la base de datos del panel
   ──► el panel RE-APLICA filtros y simulación en el navegador con los parámetros que elija el usuario (§7)
```

La decisión final la toman los filtros de `radar/deepwallet.py::passes` (Python, barrido) y `evalWallet` en `dashboard/copy.html` (JS, panel). Ambos
implementan las mismas reglas; la simulación tiene una **prueba de paridad Python↔JS** (`tests/test_parity_js.py`).

## 2. Datos y su fiabilidad

| Fuente | Para qué | Límites conocidos |
|---|---|---|
| GMGN OpenAPI (solo lectura, plan gratuito, ~1 unidad/s) | descubrimiento (ranking, top traders, smart money/KOL), estadísticas de PnL a 30 d, historial por wallet (`wallet_activity`), transferencias | `wallet_activity` devuelve páginas de 20 filas y **~1.000 filas máximo por wallet** → en wallets muy activas la ventana de 60 d queda **parcial** (marcado `complete=false` / «historial parcial»). Importes en **USD** (`cost_usd`), no en SOL. |
| Helius (RPC enriquecido) | historial alternativo desde la cadena (cuota gratuita **agotada**; ya no se usa) | Deducción de compras/ventas en `wallet_history.derive_trade`: ignora transacciones con varios tokens a la vez y las de importe ínfimo. |
| DexScreener | precio / pool | Para pools de PumpSwap devuelve la fecha de **creación del token**, no la de migración (error descubierto el 20-oct; ver §9). |
| pump.fun frontend API | listas de tokens migrados, reservas virtuales | Algunos endpoints devuelven 400/404. |

Precio de SOL: el de `meta.sol_usd` del último barrido (≈104–105 USD) para convertir USD→SOL; solo afecta al tamaño típico mostrado y al mcap aproximado,
no a los múltiplos ni a la rentabilidad porcentual.

## 3. Cómo se encuentran candidatas (descubrimiento)

Las fuentes **solo proponen**; ninguna decide. Todas pasan por el mismo historial completo y los mismos filtros.

1. **Tokens en tendencia → mejores traders** (`discover.gmgn_candidates`): ranking de GMGN (intervalos 24 h y 6 h; orden por volumen y por nº de wallets
   «smart_degen»; ≤ 40 tokens por lista; solo mints `...pump`). Por token, los 100 mejores traders por ganancia; se conservan los de ganancia ≥ 300 USD en ese
   token. Prefiltro de 30 d con `wallet_stats` (una llamada por wallet, con caché): rentabilidad realizada ≥ **30 %**, ≥ **20** compras, ganancia realizada ≥ **1.000 USD**.
2. **Smart money / KOL en directo** (`/v1/user/smartmoney`, `/v1/user/kol`): sondeo repetido que guarda cada operación con su precio → mcap de entrada (`tools/analysis/poll_live.py`). Se
   agrupan wallets que compran repetidamente en una franja de mcap.
3. **Tokens migrados** (`python -m radar migrants`): top 100 traders por ganancia de cada token migrado; «acierto rápido» = compra ≥ 150 USD, cobrado ≥ x5,
   posición ≤ 30 min. Se agrupan por wallet.
4. **Tokens que pumpean de golpe** (`radar/pumps.py`, `python -m radar pumps`): del ranking (5 m / 1 h / 6 h) se toman tokens con subida ≥ **40 %** (5 m),
   ≥ **150 %** (1 h) o ≥ **300 %** (6 h), mcap ≥ 15.000 USD, liquidez ≥ 8.000 USD, edad ≥ 30 min, sin marca de wash-trading ni honeypot. De cada uno se leen los 100
   mejores traders y se marcan los que **entraron antes del pump**: precio medio de compra ≤ **1,3 ×** el precio previo implícito (`precio_actual / (1 + subida)`),
   compra real ≥ 150 USD, no recibida por transferencia, y que cobraron ≥ 1,5 × lo gastado. Luego prefiltro de 30 d (≥ 30 %, ≥ 20 compras, ≥ 1.000 USD, acierto ≥ 35 %).
5. **Co-operación** (`discover.cotraders`, `pool_trades`, `venue_trades`; comando `cotrade`): wallets que operan los mismos tokens que una semilla buena.
6. **Lista manual del usuario** (`watchlist/*.txt`).

La tasa de acierto del descubrimiento es baja (≈ 2–5 % de las candidatas acaban cumpliendo los filtros).

## 4. Construcción de posiciones y métricas (`radar/deepwallet.py`, `radar/gmgnwallet.py`)

**Posición** = todas las compras y ventas de una wallet en un mismo mint.
- Coste = suma de lo gastado en compras; ingresos = suma de lo cobrado en ventas; tokens comprados/vendidos.
- **Cerrada** ⇔ vendió ≥ **90 %** de lo comprado. **Solo las cerradas entran en la rentabilidad.** Las abiertas o parciales **no suman ni restan** (se
  cuentan aparte en `n_open`).
- Múltiplo `mult = ingresos / coste` (solo cerradas).
- **Tenencia** = hora media de las ventas (ponderada por lo cobrado) − hora media de las compras (ponderada por lo gastado), mínimo 0.

**Métricas por wallet** (`deepwallet.metrics`):
- `n_closed`; `roi = Σ(ingresos − coste) / Σ coste` de las cerradas; `win_rate`; `median_hold_s`; `short_hold_share` = proporción de cerradas con tenencia < **120 s**.
- `hits10` = nº de cerradas con múltiplo ≥ **11** (≥ +1000 %); `best_mult`.
- `bot` = `operaciones / días > 300` (`config.history.bot_trades_per_day`).
- `span_days` = días de historial observado; `closed_recent` = cerradas en los últimos 14 d; `last_ts` = última actividad (incluye compras abiertas).
- `copy_r` y `copy_total_ex2`: resultado de **simular la copia** de todas las cerradas (y de todas menos las 2 de mayor múltiplo) con 100 USD fijos y 30 s de retraso (§6).

## 5. Filtros por defecto (`deepwallet.passes`; mismos valores en el panel, preset «Por defecto»)

Una wallet entra como **activa** si cumple TODO:

| Regla | Valor | Intención |
|---|---|---|
| No es bot | ≤ 300 operaciones/día | no copiable a mano |
| Historial | ≥ **15 días** (se omite si la cobertura es parcial) | evitar rachas de pocos días |
| Operaciones cerradas | ≥ **20** | muestra mínima |
| Tenencia mediana | ≥ **5 min** (300 s) | no ser la liquidez de salida |
| Salidas < 2 min | ≤ **35 %** | idem |
| Rentabilidad total | ≥ **30 %** sobre lo invertido (si es positiva) y > 0 | alto rendimiento |
| Expected R copiando | ≥ **0,10** | que copiarla aún sea rentable con costes |
| Robustez | si se quitan sus **2 mejores** operaciones, el resultado **copiado** sigue > 0 | no vivir de 1–2 aciertos |
| (opcionales, desactivados) | ≥ N ops. cerradas en 14 d; máx. días sin operar; ≥ N operaciones de +1000 % | el panel tiene presets «Con actividad reciente», «Estrictos», «Laxos», «Cerca de migrar» |

**Estados** (`radar/sweep.py::build_docs`): se guarda en la base de datos toda wallet con ≥ 5 cerradas y (algún +1000 % o rentabilidad > 5 %). `active` si cumple los
filtros por defecto; `candidate` si no; `dropped` si estaba activa y dejó de cumplir (no se borra, para conservar su tramo hacia adelante). Todo cambio queda en
`meta/sweep.changes` con motivo.

**`joined_ts`** = primera vez que cumplió los filtros. Es el inicio de la prueba **«Desde que entró»**: el único tramo no contaminado por haber elegido la wallet mirando
su pasado. Nunca se rehace al volver a entrar.

**Exclusión manual** (`excluded` en el documento): wallets que el usuario o el análisis descartan (p. ej. una que compra en la curva temprana y vende en ~2 s: «dumpea a
quien la copia»). El panel nunca las muestra como cumplidoras.

## 6. Simulación de copia (`radar/copysim.py`; réplica en JS)

Para cada posición cerrada de la wallet, un seguidor con tamaño `S` USD habría obtenido:

```
c   = fee_por_lado + impacto_por_1000USD * S/1000          (por defecto 1 % + 2 % por cada 1.000 USD → 100 USD: 1,2 % por lado)
net = mult * (1 - c)^2 / (1 + penalización_entrada) - 1
net = max(net, -stop)                                      (stop −60 %, ejecutado «a ese precio»)
R   = net / 0,60                                           (1R = lo que se pierde si salta el stop)
```

- `penalización_entrada` por defecto: **+9 % (30 s), +17 % (60 s), +20 % (120 s)**. Se **midió** como mediana del movimiento del precio tras una compra de ≥ 0,3 SOL en
  tokens cercanos a migrar. Es una muestra concreta; **no está validada** para otras wallets o fases del token.
- No se acredita ninguna mejora por salir después que la wallet. Tampoco se penaliza salir peor que ella (salvo comisión e impacto).
- Expected R = media de R de todas las operaciones; intervalo 95 % = ±1,96·EE (supone operaciones independientes).
- Robustez (`copy_total_ex2`): resultado total en USD copiando todas menos las 2 de mayor múltiplo.

## 7. Qué recalcula el panel

El navegador lee `wallets/*` y `meta/sweep` y, con los parámetros del usuario (importe, retraso, ventana 60 d o «desde que entró», filtros, mcap mín./máx. de entrada,
incluir bots), vuelve a evaluar cada wallet (`evalWallet`), ordena las que cumplen por Expected R, limita a las `top_n` (10 por defecto) y simula la copia **conjunta**.
**No se rellena** con wallets que no cumplan: si hay menos de N, se muestran menos.

**Análisis por mcap de entrada** (añadido el 20-oct; `radar/crossing.py`): mcap medio de entrada en SOL = `coste / tokens comprados × 1.000 M` (supply estándar de pump.fun;
se descartan mints con otro supply). La curva se completa a ≈ **383 SOL** (≈ 40k USD; mediana de las reservas virtuales de 50 tokens completos). Franjas: temprana
< 0,35 G, media 0,35–0,6 G, **a punto de migrar 0,6–1 G**, **recién migrado 1–3 G**, tarde > 3 G. Se muestra ROI/R por franja; el preset «Cerca de migrar» copia solo
entradas de 24k–120k USD.

**Clusters** (misma persona, heurística): dos wallets entran en el mismo token con ≤ 10 s de diferencia en ≥ 10 tokens y ≥ 20 % de los de la menor; se marcan con etiqueta
«cluster». No es prueba de identidad on-chain. Esta detección **no está en `radar/`**: es el script `tools/analysis/clusters.py` y su resultado se escribió a mano en los documentos. **Capital** (`radar/flows.py`): transferencias entrantes/salientes (GMGN), enlaces entre wallets seguidas, destinos comunes y
caídas de saldo ≥ 30 % entre barridos (si el saldo ≥ 5 SOL).

## 8. Estado de la evidencia (honesto)

- Los resultados mostrados son **dentro de muestra**: las wallets se eligen mirando sus últimos 60 días. El panel avisa de ello. La única prueba limpia es «Desde que entró», que
  hoy cubre pocos días.
- No se ha calculado Deflated Sharpe ni corrección por comparaciones múltiples. Se han examinado **miles** de wallets candidatas (decenas de miles de filas de traders);
  con tasas de acierto del 2–5 % parte de lo que cumple puede ser azar.
- El resultado positivo observado hasta ahora en el panel (simulado) **no es una garantía**; el usuario lo describe como «de momento rentable» tras ver las operaciones.
- Ideas probadas y **descartadas** (ver `HIPOTESIS_v7.md`): (a) «entra antes de migrar y vende después» (los cruces salen +300–800 % por **sesgo de supervivencia**: solo se
  observan tokens que ya migraron; con la cifra justa «entra en curva» casi desaparece); (b) listas de «mejores traders de cada token» como fuente sin verificar (62 candidatas
  «cerca de migrar»: 61 verificadas, 0 pasaron); (c) wallets que compran en el bloque de creación y venden en segundos (no copiables); (d) clusters perdedores.

## 9. Debilidades conocidas (revisar con prioridad)

1. **`copy_r` no descuenta operaciones inviables.** `deepwallet.metrics` simula la copia con el múltiplo completo de **todas** las cerradas, incluidas las de tenencia de
   segundos que ningún seguidor puede copiar. Lo mitigan `median_hold_s ≥ 5 min` y `short_hold_share ≤ 35 %`, pero una wallet con 30 % de salidas instantáneas muy rentables
   puede salir mejor de lo real. (En los análisis ad hoc por mcap se trataron las de ≤ 30 s como «sin ventaja»; **no** está así en el filtro por defecto.)
2. **Posiciones abiertas no restan.** Quien no vende sus pérdidas infla su rentabilidad. Se muestra `n_open` pero **ningún filtro lo penaliza**.
3. **Salida optimista.** El seguidor vende al mismo precio que la wallet (más comisión e impacto); no hay modelo de salida tardía ni de otros seguidores. El stop del −60 % se
   supone ejecutado a ese precio (en una caída brusca no ocurriría).
4. **Penalización de entrada medida en una muestra concreta** (tokens cerca de migrar). Para tokens muy tempranos (< 4k USD de mcap) el retraso real puede ser mucho peor.
5. **Cobertura parcial** (tope de ~1.000 filas de GMGN): se salta el filtro de ≥ 15 días y las métricas se calculan solo sobre el tramo visto, que puede ser de pocos días
   (p. ej. una wallet con «10 días de historial»).
6. **Aproximaciones de mcap**: precio medio de varias compras (no la primera), SOL constante y supply de 1.000 M; con GMGN el coste es USD/precio actual del SOL.
7. **Dependencia entre operaciones**: el intervalo de confianza supone independencia, pero wallets que copian los mismos tokens están correlacionadas; los **clusters** cuentan
   varias veces la misma persona en el agregado del panel.
8. **Robustez débil con pocas operaciones**: quitar solo las 2 mejores no protege si n ≈ 20–30; no hay bootstrap ni prueba de permutación.
9. **El barrido diario aún no se ha ejecutado de verdad**: la rutina programada falló por falta del secreto `GMGN_API_KEY` en su entorno (no ha escrito nada). Todos los datos
   actuales proceden de ejecuciones manuales de esta sesión.
10. **Sesgo de la fuente**: GMGN solo muestra los 100 mejores traders por token; de una wallet que gana en 1 token y pierde en 9 solo se ve el acierto.
11. **Bots**: el umbral de 300 operaciones/día es arbitrario; varias wallets de alto volumen quedan en el límite y el panel permite incluirlas con una casilla.

## 10. Preguntas concretas para el auditor

1. ¿Es coherente exigir robustez «sin las 2 mejores» con n ≥ 20? ¿Qué prueba estadística sería mejor (bootstrap por posición, permutación de signos, Deflated Sharpe con el número real de candidatas)?
2. ¿La penalización de entrada (+9 %/+17 %/+20 %) y el modelo de salida son plausibles para tokens de 5k–120k USD de mcap? ¿Qué modelo de latencia/slippage propondrías?
3. ¿Hay fuga de información hacia adelante en el cálculo de `closed_recent`, `joined_ts` o en la selección «entró antes del pump» (precio previo implícito calculado con datos del propio pump)?
4. ¿Debe `copy_r` excluir o neutralizar operaciones de tenencia < N segundos? ¿Con qué N?
5. ¿Cómo corregirías el efecto de las posiciones abiertas (marcar a mercado, exigir ratio abiertas/cerradas, etc.)?
6. ¿Es sólido el criterio de cluster (co-entrada ≤ 10 s en ≥ 10 tokens)? ¿Qué falsos positivos (copiadores del mismo bot, grupos de Telegram) esperas?
7. ¿El tamaño de muestra y el reparto 60 d / «desde que entró» permiten sacar alguna conclusión, o hace falta un periodo de validación hacia adelante de N semanas antes de confiar?
8. ¿Qué métrica adicional (drawdown por wallet, concentración por token, correlación entre wallets) añadirías antes de ponerle dinero real?

## 11. Mapa del código

| Qué | Dónde |
|---|---|
| Parámetros por defecto | `radar/config.py` (bloque `copy`, `history`, `gmgn`) |
| Posiciones y métricas (Helius) | `radar/deepwallet.py` (`positions_from_txs`, `metrics`, `passes`) |
| Posiciones y métricas (GMGN) | `radar/gmgnwallet.py` (`fetch_activity`, `positions_from_activity`, `analyze`) |
| Deducción compra/venta | `radar/wallet_history.py::derive_trade` |
| Simulación de copia | `radar/copysim.py` (`trade_net`, `simulate`) · réplica JS entre `BEGIN SIM` y `END SIM` en `dashboard/copy.html` |
| Descubrimiento | `radar/discover.py`, `radar/migrants.py`, `radar/pumps.py` |
| Mcap / franjas | `radar/crossing.py` |
| Estados y documentos | `radar/sweep.py::build_docs` |
| Barrido diario | `radar/daily.py::run` · `python -m radar daily` · rutina programada «Barrido diario de wallets copiables» |
| Capital entre wallets | `radar/flows.py` |
| Filtros del panel | `dashboard/copy.html::evalWallet` |
| Conclusiones y descartes | `HIPOTESIS_v7.md` |
| Scripts de análisis puntual (no forman parte del barrido) | `tools/analysis/` (ver `LEEME.md`: rutas de la sesión que hay que ajustar) |
| Pruebas | `tests/` (`python3 -m unittest discover -s tests`; incluye paridad Python↔JS) |

Reproducir una wallet: `python -m radar deep <fichero con direcciones> --source gmgn --days 60 --out <salida.json>` (necesita `GMGN_API_KEY` en `.env`; nunca se imprime ni se sube).


## 12. Actualización del 21-oct-2026 (tras la auditoría externa)

Este documento describe la metodología ORIGINAL (§0-§11). Después se recibió una auditoría externa y se aplicó parte de ella; el detalle y los resultados están en `HIPOTESIS_v7.md`, sección «Respuesta a la auditoría externa». Resumen:

- Nuevo módulo `radar/audit.py` y «Modo auditoría» opcional en el panel (no quita ninguna wallet de la lista por defecto): sin stop, sin la operación de descubrimiento, tenencia frente a latencia (< 30 s no se copia; 30-60 s solo costes),
  bolsas valoradas (cota pesimista), impacto de curva y salida con retraso (placeholders), R encogido hacia la media de la población (Bayes empírico), percentil 5 del bootstrap por bloques de un día, resultado sin el 10 % mejor y reparto del beneficio en las 3 mejores.
- Walk-forward sobre la caché: hay persistencia de rango entre las wallets copiables (Spearman +0,37 a +0,68, p 0,0005-0,08) pero el R medio posterior solo es positivo en 3 de 4 cortes y el método es optimista (las wallets ya se eligieron mirando todo el periodo).
- Prueba hacia adelante sin filtrar en el panel e instantánea inmutable por barrido con huella de configuración.
- El barrido ya no borra `cluster`, `excluded`, `source_tag` ni `trigger_mints`.
- Debilidades de §9 que siguen abiertas: 3 (salida optimista: ahora hay un 5 % provisional), 4 (penalización de entrada solo medida cerca de migrar), 6 (mcap aproximado), 7 (dependencia entre operaciones y clusters), 9 (barrido diario sin secreto), 10 (sesgo de la fuente). Cerradas parcialmente: 1 (modo auditoría), 2 (bolsas, a falta de la re-descarga), 5 (cobertura parcial en modo auditoría), 8 (bootstrap).
