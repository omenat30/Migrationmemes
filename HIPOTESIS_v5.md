# Hipótesis v5: ¿antes o después de migrar? ¿Se puede apuntar a x3? (escrita ANTES de ver resultados)

Fecha: 2026-10-14. Alcance acordado: **solo tokens de pump.fun** (mint terminado en `pump`, cotizados en SOL), 100 USD
por operación, stop del −60 % desde tu entrada, y objetivo de **x3 o más** (+200 %).

## La pregunta
¿Es más rentable entrar **antes de migrar** (en la curva) o **después** (en el pool de PumpSwap)? ¿Con qué frecuencia
se alcanza x3 sin tocar antes el stop?

## Estudio A: entrar DESPUÉS de migrar (se puede medir ya, con una cautela)
Entrada a `D` segundos de la migración, con D en {30, 60, 120, 300} (retraso humano realista). Salidas:
- **R1**: vender si el precio llega a x3; si no, mantener hasta 2 h. Stop del −60 % siempre activo.
- **R2**: mantener 1 h con stop del −60 %, sin objetivo.
Se informa de: % que llega a x3 antes del stop, % que toca el stop, retorno neto medio y mediano por operación de 100 USD
(con comisiones y deslizamiento del pool), y la distribución del múltiplo máximo (≥ x2, ≥ x3, ≥ x5).
**Cautela de sesgo:** los tokens salen del listado de pump.fun, que favorece a los que siguen activos tras migrar. Eso
**infla** el resultado. Por tanto este estudio solo da una **cota superior**: si aun así sale mal, la conclusión es sólida;
si sale bien, no es prueba.

## Estudio B: entrar ANTES de migrar (necesita el grabador en vivo)
Solo el grabador en vivo ve también a los tokens que llegan al 90 % y NO completan, así que es el único sin sesgo. Se
juzga con las 12 variantes de `HIPOTESIS_v4.md`, más el criterio x3: con el stop −60 % y vendiendo al migrar, el máximo
mecánico entre el 93 % y el 100 % es ~+42 %, así que **x3 solo es posible entrando mucho antes en la curva** (por debajo
de ~65 % de avance) o después de migrar con un pump posterior. Ningún dato real permite aún estimar entradas tempranas.

## Regla para decidir «qué es más rentable»
Se compara el **retorno neto medio por operación de 100 USD** con intervalo al 90 % (bootstrap). No se declara ganador
si los intervalos se solapan o si la muestra es menor de 30 operaciones por rama. Con muestra menor, la respuesta es
«no se sabe todavía», no una elección.

## Lo que puede invalidar esta versión
1. Sesgo de supervivientes en el listado (ya declarado). 2. Una sola racha de mercado. 3. Precio por operación del pool
calculado como SOL/tokens de la mayor transferencia de cada tipo, contrastado con DexScreener en un caso (error ~3 %).
4. Comisión y deslizamiento reales distintos de los supuestos. 5. Tokens con pools enormes o muy antiguos que no se
pueden reconstruir se excluyen y se cuentan aparte, lo que también puede sesgar.
