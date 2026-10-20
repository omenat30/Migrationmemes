# Hipótesis v7: panel de wallets copiables (en vivo)

Escrito antes de mirar resultados del barrido amplio.

## Qué se quiere
Un panel vivo con hasta 10 wallets de Solana que (1) hayan hecho operaciones sueltas de +1000 % o más en los últimos 30 días,
(2) no entren y salgan en minutos ni dejen a sus seguidores con la bolsa, (3) tengan rentabilidad y (4) un mínimo de operaciones.
El panel simula el Expected R de copiarlas con el importe por operación que elija el usuario. Cada día un barrido mete wallets
nuevas y saca las que dejan de cumplir.

## Definiciones (todas editables en el panel)
- **Retorno brutal** = una operación cerrada con múltiplo ≥ x11 (+1000 %). Exigirlo al retorno total sobre lo invertido no es
  realista: en las wallets medidas, el retorno global fue de +8 % a +70 %, aunque tuvieran operaciones sueltas de x14 a x32.
- **Operación cerrada** = vendió al menos el 90 % de lo comprado en ese token. Las abiertas no cuentan (inflan a quien no vende
  sus pérdidas) y se muestran aparte.
- **No dumpea** (decisión del usuario, 14-oct): ventana de 30 días y tenencia mediana ≥ 10 min, con como mucho 35 % de salidas en menos de 2 min. La tenencia es la hora media de venta
  menos la hora media de compra, ponderadas por importe.
- **Mínimo de operaciones**: 20 cerradas en el periodo; más de 300 al día se descarta como bot.
- **No vive de suerte**: retorno positivo y ganancia positiva quitando sus 2 mejores operaciones.

## Simulación de copia
`neto = múltiplo × (1 − c)² / (1 + entrada_tardía) − 1`, con c = comisión por lado + impacto por cada 1.000 USD. El stop del −60 %
recorta la pérdida (optimista). R = neto / 0,60. Entrada tardía medida: +9 % a 30 s, +17 % a 60 s, +20 % a 120 s. No se acredita
ninguna mejora por salir más tarde que la wallet. Comisión 1 % e impacto 2 % por 1.000 USD son supuestos sin verificar.
Lógica en `radar/copysim.py` y en `dashboard/copy.html`; `tests/test_parity_js.py` comprueba que dan lo mismo.

## Qué cuenta como prueba
- El tramo de 30 días es **dentro de muestra**: las wallets se eligieron mirando ese pasado (sesgo del ganador). Es un techo.
- La prueba que cuenta es **«desde que entró»**: operaciones posteriores a la primera vez que la wallet cumplió los filtros
  (`joined_ts`, que no se rehace). Hasta que haya semanas de ese tramo no hay conclusión.
- Regla de descarte: si pasadas 4 semanas el Expected R «desde que entró» de la cartera no es positivo con intervalo del 95 %
  por encima de cero, esta idea se documenta como descartada.

## Límites conocidos
- Descubrir wallets es la parte débil: el barrido analiza una lista de semillas (`watchlist/seed.txt`). Añadir direcciones de
  mejores traders de GMGN/Axiom la mejora más que cualquier ajuste.
- Helius gratuito limita el ritmo (~15 s por wallet) y a 40 páginas (4.000 transacciones): wallets muy activas salen con
  «historial parcial».
- La reconstrucción de compras y ventas ignora transacciones con varios tokens a la vez.
- La simulación suma operaciones una tras otra sin límite de capital abierto a la vez.

## Resultado del primer piloto (6 wallets)
Ninguna cumple todos los filtros por defecto. Con tenencia mediana ≥ 30 min, 0 de 6 pasan; BcKqw3ZNH8 es la mejor (ROI +70 %,
317 SOL sin sus 2 mejores operaciones, 2 operaciones ≥ x11) pero tiene mediana de 23 min y 27 % de salidas en menos de 2 min.

## Resultado del barrido de 130 wallets (14-oct-2026, Helius)
- 130 analizadas; 19 con alguna operación ≥ x11 (15 con 5 o más cerradas); **0 cumplen los filtros estrictos** (tenencia mediana ≥ 30 min,
  ≤ 25 % de salidas en menos de 2 min). Casi todas las que tienen operaciones de +1000 % son rápidas: tenencia mediana de 2 a 5 min.
- Con filtros medios (≥ 10 min, ≤ 35 % cortas, ≥ 30 operaciones): 3 wallets. Con laxos (≥ 2 min, ≤ 55 %): 7.
- Las cifras de Expected R de esas wallets son de los días en que se eligieron: techo, no expectativa. Varias tienen historial parcial
  (límite de 4.000 transacciones).
- El lote de 130 sale de mi cribado previo, no de las mejores listas de GMGN/Axiom; es una muestra pequeña y con sesgo.

## Decisión del usuario y primer estado (14-oct-2026)
Ventana de 60 días y tenencia mediana de al menos 10 minutos. Con esos filtros, de las 130 wallets analizadas cumplen 3:
BcKqw3ZNH8 (97 op., 2 de +1000 %, 23 min), DK3h7FvuGz (343 op., 6 de +1000 %, 11 min) y HD37a8wp8m (296 op., 1 de +1000 %, 10 min).
Entraron en la lista el 14-oct; desde esa fecha corre el tramo «desde que entró», que es la prueba fuera de muestra.
Quedan 7 puestos vacíos: no se rellenan con wallets que no cumplan.

## Corrección del usuario: 30 días, no 60 (14-oct-2026)
Ventana de 30 días, tenencia mediana ≥ 10 min, ≤ 35 % de salidas en menos de 2 min, ≥ 20 operaciones cerradas, ≥ 1 operación de +1000 %.
Recalculado sobre las mismas 130 wallets: **cumple 1** (BcKqw3ZNH8: 93 op., 2 de +1000 %, 23 min, +302 SOL sin sus 2 mejores).
DK3h7FvuGz y HD37a8wp8m, que habían entrado con la ventana de 60 días, salen el mismo día: en 30 días DK3h7FvuGz baja a 8 min de tenencia
y pierde sin sus 2 mejores operaciones, y HD37a8wp8m no tiene ninguna operación de +1000 % dentro de los 30 días. Queda registrado como cambio en el panel.

## Corrección del usuario y barrido ampliado (18-oct-2026)
Instrucciones: «al menos 30 días» de historial, periodo libre, al menos 5 carteras muy rentables.
- Ventana de análisis 60 días; historial mínimo 30 días; tenencia mediana ≥ 10 min; ≤ 35 % de salidas en menos de 2 min; ≥ 20 operaciones cerradas;
  rentabilidad ≥ 5 % y ganancia positiva sin sus 2 mejores operaciones. Ya no se exige una operación de +1000 %; se muestra su recuento.
- Fallo de datos corregido: rutas de Jupiter con polvo de otros tokens (~1e-9 del token principal) hacían descartar hasta el 40 % de las operaciones de algunas
  wallets (DK3h7FvuGz pasó de +8 % a −0 % de rentabilidad al corregirlo). Todo se reanalizó (145 wallets) con la corrección. Prueba en `tests/test_sweep.py`.
- Descubrimiento nuevo (`python -m radar discover`): lee las operaciones del pool de ~280 tokens ya migrados y se queda con quien ganó ≥ x3 aguantando ≥ 10 min.
  Dio 23 candidatas; ninguna repetía en dos tokens. Entraron al análisis completo 18 de ellas (el resto falló por límite de ritmo de Helius).
- Resultado con los filtros por defecto: **3 wallets** (BcKqw3ZNH8, AfBKTi18w7, DNPx2RFkeM). Casi entran 7XURCfraWR (+805 SOL, 8,9 min) y HD37a8wp8m (9 min).
- Copiadas con costes (1 % por lado, impacto 2 % por 1.000 USD, 30 s de retraso, stop −60 %, 100 USD por operación): BcKqw3ZNH8 +0,87 R; DNPx2RFkeM +0,02 R;
  AfBKTi18w7 −0,03 R. **Solo una de las tres es rentable de copiar**: las otras ganan en la cadena pero no sobreviven a costes y retraso.
- Conclusión: con este origen de candidatas no salen 5 carteras de mucha rentabilidad. El cuello de botella es descubrir wallets, no la lectura de Helius.

## Búsqueda de wallets parecidas a BcKqw3ZNH8 (18-oct-2026)
- Wallet de ejemplo del usuario, HSeCG7T2KC…: no es analizable como trader. Es una cuenta del sistema con ~692 SOL que figura (sin firmar y con saldo sin cambios)
  en cientos de transacciones por segundo de pump.fun, casi todas fallidas. En 12.000 transacciones (menos de un minuto de actividad) no hay ninguna compra ni venta
  suya. El historial por dirección de Helius no llega a 60 días hacia atrás en una cuenta así. Falta confirmar de dónde salió la dirección.
- Co-operación (`python -m radar cotrade`): se leen, para los 114 tokens que operó BcKqw3ZNH8, todas las operaciones del token (curva por PDA y pool de DexScreener) en una
  ventana de −30 min / +2 h alrededor de su entrada, y se buscan wallets que ganaron en varios de los mismos tokens aguantando ≥ 5 min.
  Resultado: 12 co-operadoras con ≥ 2 tokens en común, 8 nuevas. Ninguna cumple los filtros: 5 son bots o scalpers (tenencia de 2–4 min) y las demás tienen < 30 días
  de historial o no son rentables. La más rentable, HAFfm2fPfp (+92 %, 11 operaciones de +1000 %), sale y entra en 2 min de mediana: otro arquetipo.
- Tasa de acierto: 1 wallet como BcKqw3ZNH8 entre ~175 analizadas (~0,6 %). Para 5 harían falta ~800 candidatas.

## Descubrimiento con GMGN (19-oct-2026)
- Clave de solo lectura verificada. Límite real medido con las cabeceras `x-ratelimit-remaining`: el cubo (capacidad 5) se vacía a ~1 unidad por segundo,
  no a 5 como dice la documentación. Una llamada de estadísticas con 74 wallets a la vez bloqueó la clave 5 min; desde entonces una wallet por llamada y espera ante bloqueo.
- Búsqueda (no parte de las 74 del usuario): 49 tokens de pump.fun en tendencia (24 h y 6 h) -> sus mejores traders -> 3.150 wallets con ganancia >= 300 USD en alguno ->
  estadísticas de PnL a 30 días de las 300 que más ganaron -> 15 con PnL >= 30 %, winrate >= 35 %, >= 20 compras y >= 1.000 USD de ganancia.
- Verificación con el historial de GMGN (`deep --source gmgn`, mismos filtros que con Helius): **cumplen 3 de 15**.
  - 6HJetMbdHB: 142 operaciones, +210 %, 6 de +1000 %, 48 min de tenencia mediana, 9 % de salidas en < 2 min. Historial parcial (tope de 1.600 filas).
  - DMTgKsvm44: 32 operaciones, +79 %, 1 de +1000 %, 16 min.
  - 9PLvx6JvBm: 28 operaciones, +50 %, tenencia mediana de ~22 h (más swing que scalping).
  - Casi: 2GtmuqG31L (+98 %, 29 días de historial en vez de 30), 2xUbYAVq1o (+119 %, 16 operaciones en vez de 20).
- Aviso de método: BcKqw3ZNH8 sale +51 % con Helius (SOL, 60 d) y +23 % con GMGN (USD, 60 d). Tenencia parecida (24 vs 19 min). No sé cuál de las dos mediciones es más fiel;
  las wallets leídas con GMGN llevan la etiqueta GMGN en el panel.

## Investigación de 6HJetMbdHB: ¿ha movido el dinero o no opera? (19-oct-2026, GMGN)
- Saldo: **183,1 SOL** (~19.000 USD) siguen en la wallet. No ha retirado los fondos.
- Sí opera en octubre, pero solo **compra**: BANDIT (1-oct, 2.494 USD), DEX y STONK (3-oct), Onwards, baton y PUMP (12-oct, ~2.000 USD cada una). Su última venta fue el 1-oct
  (la de x21). Esas compras siguen abiertas: mi análisis solo guarda posiciones CERRADAS, por eso en octubre no se veía nada. Fallo corregido: las compras abiertas cuentan ya como actividad.
- Últimos 7 días: 0 compras y 0 ventas (la última compra fue el 12-oct). Antes, en la ventana de 30 días, 31 compras y 59 ventas: ha frenado mucho.
- 22-sep, 01:53: sacó tokens PUMP por ~19.400 USD (6.197 y 13.241) a dos direcciones. Podría ser reparto entre wallets propias; no está verificado.
- Nuevo filtro: «máx. días sin operar» (14 por defecto), y el panel muestra la última operación y las posiciones abiertas de cada wallet.

## Historial mínimo de 15 días (19-oct-2026, a petición del usuario)
Muchas cuentas rotan capital rápido, así que el mínimo de historial baja de 30 a 15 días. El resto de reglas no cambia (tenencia mediana >= 10 min, <= 35 % salidas en < 2 min,
>= 20 operaciones cerradas, rentabilidad >= 30 %, ganancia positiva sin las 2 mejores). Con eso cumplen 5: BcKqw3ZNH8, DMTgKsvm44, 2GtmuqG31L, 6HJetMbdHB y 9PLvx6JvBm.
El filtro de actividad reciente (>= 5 cerradas en 14 d, <= 14 días sin operar) queda opcional; la tabla marca «poca actividad reciente».
Movimientos de capital (GMGN, primera pasada): sin enlaces entre las 12 wallets ni destinos comunes. Saldos actuales llamativos: DMTgKsvm44 0,86 SOL, 2GtmuqG31L 0,16 SOL,
9PLvx6JvBm 2,0 SOL pese a ganancias grandes a 30 días: lo más probable es que la ganancia esté fuera de la wallet o en tokens, y pendiente de confirmar a dónde fue.

## Búsqueda de rentabilidad de 15 días con smart money (20-oct-2026)
Petición: wallets con +100 % en 15 días. Método nuevo: top traders de ~146 tokens filtrados por etiqueta `smart_degen` de GMGN (125 wallets) más el endpoint `smartmoney`/`kol` en directo
(150 wallets; solo cuesta 1 unidad por llamada) -> 225 únicas -> estadísticas de PnL a 7 días -> las de >= +30 % se verifican con su actividad de 15 días.
- Medidas: ninguna wallet con TODAS las operaciones ganadoras en 15 días (entre 81 con >= 4 operaciones cerradas). Mejor acierto: AcGLjWVZKR, 93 % de 92 operaciones.
- Con +100 % o más en 15 días solo aparece FDuUUwd2j2 (+151 %, 23 operaciones, tenencia mediana de 1 min, 70 % de salidas en < 2 min): no cumple tenencia.
- Entran (cumplen todos los filtros, ventana de 15 días): AcGLjWVZKR (+46 %, 92 op., 3 % de salidas cortas, 22 min), GAsnqm4XkN (+68 %, 22 op., 48 min),
  5LLTYLm8se (+43 %, 50 op., ~24 h), AqSUfx6Y2e (+35 %, 181 op., 12 min).
- Aviso de cobertura: GMGN solo devuelve ~1.000 filas de historial por wallet; en las más activas la ventana es parcial (marcado en el panel).

## Reglas por defecto desde el 20-oct-2026 (petición del usuario: tenencias de 5-10 min valen si copiar sale rentable)
- Tenencia mediana >= 5 min (antes 10), <= 35 % de salidas en < 2 min, >= 20 operaciones cerradas, rentabilidad >= 30 %, historial >= 15 días (con cobertura parcial no se penaliza).
- Nuevo: **Expected R copiando >= 0,10** (100 USD fijos por operación, retraso 30 s, comisión 1 % y 2 % de impacto por 1.000 USD, stop -60 %) y robustez medida **copiando**:
  si sin sus 2 mejores operaciones el resultado copiado no es positivo, la wallet vive de suerte. Antes se medía en SOL y pesaba más lo que mueve más dinero; el usuario copia con importe fijo.
- Con esto cumplen 11 wallets de 55 (ordenadas por Expected R): 3bzaJd5yZG, DMTgKsvm44, 2GtmuqG31L, 5LLTYLm8se, 6HJetMbdHB, GAsnqm4XkN, BcKqw3ZNH8, DxM1hfY8FQ, AcGLjWVZKR, GDpqhJgwzg, AqSUfx6Y2e.
  Aviso: el Expected R de 3bzaJd5yZG (+11,97) lo dominan unas pocas operaciones enormes (sin las 2 mejores baja a +0,23 y sin el 5 % mejor a -0,15).

## Tokens migrados de pump.fun: ¿hay un grupo que repite x5-x10 en < 30 min? (en curso)
Método (`python -m radar migrants`): para cada token migrado (lista de pump.fun con complete=true, por market cap o por fecha) se leen sus 100 mejores traders por ganancia (GMGN) y se marcan
«aciertos rápidos»: compra real >= 150 USD, cobrado >= x5, posición abierta <= 30 min (marcas de primer y último movimiento). Luego se agrupan por wallet.
Primeros 95 tokens (los de mayor market cap desde junio): 44 aciertos rápidos de 44 wallets distintas, **ninguna repite**; 19 de 43 entraron antes de migrar y 9 en los 30 min posteriores.
Límite: el top 100 por ganancia no es todo el que operó; los aciertos pequeños no salen.

## Entrar antes de migrar y vender después: ¿existe un patrón copiable? (20-oct-2026)
Petición: mirar wallets que entran antes de la migración y salen tras ella (`radar/crossing.py`). Hora de migración = creación del pool en DexScreener (3.629 de 23.025 tokens con pool conocido).
Cada operación cerrada se clasifica: **cruce** (entra antes de migrar y termina de vender después), **previa** (entra y sale antes), **tras** (entra con el pool ya creado) y **curva** (sin pool conocido).
- Sesgo de selección: los cruces salen altísimos (HAFfm2fP +840 %, 3jUDDXW2 +347 %, HD37a8wp +321 %, 7Eav6kHm +318 %, DypmN13z +305 %, en las ~36 wallets con >= 5 cruces) porque solo se ven tokens que ya sabemos que migraron.
  Hace falta saberlo ANTES de comprar, y eso no se puede copiar. La cifra justa es **entra en curva** (cruce + previa + curva): incluye los tokens que nunca migraron.
- Con la cifra justa, la mayoría desaparece: en 4gG4V4iPrw (2.706 entradas en curva) el ROI es +9 %, en DypmN13zYi +2 %, en CyJLNEWdAu +6 %, aunque sus cruces rindan +240-300 %.
- Solo dos wallets cumplen filtros y tienen ROI justo claro entrando en curva: **AcGLjWVZKR** (80 op., +47 %, 96 % de acierto, tenencia mediana 23 min, Expected R +0,57, +0,52 sin sus 2 mejores)
  y **DA9nTGVx7N** (2.200 op., +35 %, tenencia 4 min; con GMGN la cobertura es parcial).
- Las demás ganadoras lo son entrando **tras migrar**: 6HJetMbdHB (+296 %), 3bzaJd5yZG (+195 %), DxM1hfY8FQ (+111 %), 2GtmuqG31L (+100 %), DMTgKsvm44 (+85 %), GAsnqm4XkN (+66 %), AqSUfx6Y2e (+52 %), 5LLTYLm8se (+47 %).
- El panel muestra tres columnas añadidas (ROI y n): «Entra en curva», «Entra tras migrar» y «Cruces (sesgado)». Se guardan en `wallets/{addr}.mig`. Nada se ha quitado.
- Pendiente: `migrants` sobre 447 tokens con filas por wallet (`rows`) para ver quién entra antes de migrar de forma repetida; el run lleva 85/447 al escribir esto (23 aciertos rápidos, ninguna wallet repetida todavía).
