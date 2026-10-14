# Hipótesis v4: backtest de tu operación (escrita ANTES de tener datos suficientes)

Fecha: 2026-10-14. El grabador acaba de arrancar; todavía no hay histórico para juzgar nada. Este archivo no se edita
una vez que el backtest tenga datos suficientes para dar veredicto.

## Tu operación (parámetros fijos, no se optimizan)
- **100 USD por operación.**
- **Stop del −60 % desde tu entrada**, con cierre manual: se modela un tiempo de reacción de 30 s, así que en un
  desplome sales peor que −60 % (el precio sigue cayendo mientras reaccionas).
- Retraso hasta que compras: 30 s desde la señal. Si para entonces el token ya migró, compras en el pool: así se cuenta
  llegar tarde.
- Comisión 1 % por lado en la curva (valor sin verificar contra la tarifa actual), 0,30 % en el pool (sin verificar),
  deslizamiento calculado con las reservas reales o la liquidez del pool, y comisión de red.

## Hipótesis
Comprar un token de pump.fun que cotiza en SOL cuando llega al ~93 % de la curva (≥ 30.000 USD) y vender tras migrar
tiene **expectativa positiva neta de costes**. Motivo mecánico: entre el 93 % y el 100 % la capitalización sube ~42 % por
construcción (va con las reservas al cuadrado) y el stop del −60 % queda lejos. Hace falta que la mayoría de los
tokens que llegan al 93 % completen y que tú llegues sin que el precio se haya movido.

Hipótesis nula: sale negativa. Razones plausibles: los bots ya compraron, muchos tokens se hunden antes de completar o
justo al migrar, y las comisiones y el deslizamiento comen el 42 %.

## Datos
Histórico GRABADO por `python -m radar record` (precio cada 15 s de cada token con avance ≥ 75 %, momento exacto de
migración, precio y liquidez en el pool después, y características al cruzar el 90 %). No hay histórico largo
disponible: el listado de pump.fun solo alcanza ~1.000 tokens recientes y no existe endpoint de velas.

Límites del histórico: es de una sola racha de mercado (los días que se grabe). Solo tokens que cotizan en SOL.

## Variantes: lista cerrada de 12 (`bt_variants.json`)
B01 entrar al 90 % · B02 93 % (base) · B03 96 % · B04 93 % con objetivo +30 % · B05 93 % vender a los 30 min ·
B06–B08 93 % con un filtro (concentración top 10 < 35 %, creador sin rugs, 15+ compradores y wash < 25 %) ·
B09 los tres filtros · B10/B11 los tres filtros al 90 % y al 96 % · B12 objetivo +30 % con los tres filtros.

## Reglas sin mirar el futuro
- Una entrada por token y variante: la primera muestra con avance ≥ entrada y capitalización ≥ 30.000 USD.
- Un filtro solo puede usar características grabadas **antes o en** el momento de la entrada, y un dato que falte no
  deja pasar. Hay pruebas automáticas de ello.
- Una operación cuya salida aún no se conoce se **excluye** y se cuenta aparte, no se adivina.

## Partición y decisión
Operaciones ordenadas por hora de entrada. **Primera mitad** para elegir la variante con mayor retorno neto medio (con
≥ 15 operaciones). **Segunda mitad** para probar solo la elegida, con ≥ 30 operaciones:
- **RENTABLE (provisional)**: media neta > 0, intervalo al 90 % (bootstrap) con límite inferior > 0 y factor de beneficio
  > 1,2.
- **DESCARTAR**: media ≤ 0 o límite superior del intervalo ≤ 0.
- **INCONCLUSO**: positivo pero el intervalo incluye el cero. Hace falta más muestra.
- **SIN DATOS SUFICIENTES** si faltan operaciones.
Se informa también del retraso: la elegida con 30, 60, 120 y 300 s hasta comprar, solo sobre la segunda mitad.

«RENTABLE (provisional)» autoriza a seguir midiendo con otra racha de mercado, nunca a poner dinero por sí solo. Con 12
variantes una «ganadora» puede aparecer por azar; por eso se prueba solo la elegida y solo en la segunda mitad.

## Lo que puede invalidar esta versión
1. Una sola racha de mercado: un buen día de memecoins engaña.
2. Comisión y deslizamiento reales distintos de los supuestos, sobre todo tras migrar.
3. Que el precio de la muestra no sea el que habrías obtenido (los bots mueven el precio en milisegundos y se muestrea
   cada 15 s).
4. El listado deja de mostrar tokens muy activos entre muestras: se compensa leyendo la curva en la cadena, pero puede
   haber huecos.
