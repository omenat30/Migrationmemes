# Hipótesis v6: wallets rentables que NO viven de venderte a ti (escrita ANTES de ver resultados)

Fecha: 2026-10-14. Objetivo del usuario: encontrar **wallets rentables** para seguirlas, no las que ganan dumpeando sobre
quienes las siguen. Se prueba en dos escenarios: **tokens ya migrados** y **tokens cerca de migrar**.

## Qué distingue «rentable» de «extractora»
Una wallet puede tener ganancia propia y ser inseguible: bots, insiders, snipers y bundlers ganan porque compran antes y
venden sobre el resto. Quien los sigue entra después y sale peor. La prueba decisiva no es la ganancia de la wallet sino lo
que **ganaría un seguidor** que copia sus compras con retraso.

## Clasificación (reglas fijas, sin ajustar a los resultados)
Con las últimas 100 transacciones de cada wallet (Helius):
- **BOT**: más de 300 operaciones por día.
- **EXTRACTORA**: ≥ 5 posiciones vendidas y ≥ 50 % cerradas en menos de 120 s.
- **SIN HISTORIAL**: menos de 5 posiciones cerradas.
- **PIERDE**: ganancia realizada ≤ 0.
- **CANDIDATA**: ≥ 5 posiciones cerradas, ganancia realizada > 0, mediana de tenencia ≥ 300 s, salidas rápidas ≤ 30 %, no bot.
Solo se estudian wallets que compraron ≥ 1 SOL en los tokens vigilados (las diminutas no importan).

## Prueba de seguimiento (copiabilidad)
Para cada compra de una wallet en un token vigilado, un seguidor compra `D` ∈ {30, 60, 120} s después al precio de la
primera operación posterior, y vende `D` s después de que la wallet venda (o, si sigue dentro, al último precio conocido,
marcado como no resuelto). Se descuenta 1 % por lado. Se informa por grupo (candidatas, extractoras, bots) con **n**.
Si la candidata gana pero el seguidor pierde, no es seguible.

## Lo que se afirma y lo que no
Con la muestra actual (~20 tokens, horas de datos) esto es un **cribado**, no un veredicto. Una wallet candidata solo
pasa a «de fiar» tras sobrevivir en tokens y días que no se usaron para elegirla (marcha adelante). Ninguna wallet se
declara rentable por su historial reciente de 100 operaciones.

## Fuente de datos
Helius (cadena). GMGN daría PnL de 30 días y etiquetas de wallets ya calculados, lo que mejoraría mucho esto, pero exige
100 USD de saldo. Axiom no tiene API pública confirmada; las librerías de terceros imitan su aplicación con tu sesión y no
se usan.
