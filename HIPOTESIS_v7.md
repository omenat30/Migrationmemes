# Hipótesis v7: panel de wallets copiables (en vivo)

Escrito antes de mirar resultados del barrido amplio.

## Qué se quiere
Un panel vivo con hasta 10 wallets de Solana que (1) hayan hecho operaciones sueltas de +1000 % o más en los últimos 60 días,
(2) no entren y salgan en minutos ni dejen a sus seguidores con la bolsa, (3) tengan rentabilidad y (4) un mínimo de operaciones.
El panel simula el Expected R de copiarlas con el importe por operación que elija el usuario. Cada día un barrido mete wallets
nuevas y saca las que dejan de cumplir.

## Definiciones (todas editables en el panel)
- **Retorno brutal** = una operación cerrada con múltiplo ≥ x11 (+1000 %). Exigirlo al retorno total sobre lo invertido no es
  realista: en las wallets medidas, el retorno global fue de +8 % a +70 %, aunque tuvieran operaciones sueltas de x14 a x32.
- **Operación cerrada** = vendió al menos el 90 % de lo comprado en ese token. Las abiertas no cuentan (inflan a quien no vende
  sus pérdidas) y se muestran aparte.
- **No dumpea**: tenencia mediana ≥ 30 min y como mucho 25 % de salidas en menos de 2 min. La tenencia es la hora media de venta
  menos la hora media de compra, ponderadas por importe.
- **Mínimo de operaciones**: 20 cerradas en el periodo; más de 300 al día se descarta como bot.
- **No vive de suerte**: retorno positivo y ganancia positiva quitando sus 2 mejores operaciones.

## Simulación de copia
`neto = múltiplo × (1 − c)² / (1 + entrada_tardía) − 1`, con c = comisión por lado + impacto por cada 1.000 USD. El stop del −60 %
recorta la pérdida (optimista). R = neto / 0,60. Entrada tardía medida: +9 % a 30 s, +17 % a 60 s, +20 % a 120 s. No se acredita
ninguna mejora por salir más tarde que la wallet. Comisión 1 % e impacto 2 % por 1.000 USD son supuestos sin verificar.
Lógica en `radar/copysim.py` y en `dashboard/copy.html`; `tests/test_parity_js.py` comprueba que dan lo mismo.

## Qué cuenta como prueba
- El tramo de 60 días es **dentro de muestra**: las wallets se eligieron mirando ese pasado (sesgo del ganador). Es un techo.
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
- Las cifras de Expected R de esas wallets son de los 60 días en que se eligieron: techo, no expectativa. Varias tienen historial parcial
  (límite de 4.000 transacciones).
- El lote de 130 sale de mi cribado previo, no de las mejores listas de GMGN/Axiom; es una muestra pequeña y con sesgo.
