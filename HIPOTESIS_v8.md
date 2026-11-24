# Hipótesis v8: «cazar» tokens nuevos de baja cap con un bot (prueba en papel)

Escrito el 24-nov-2026 ANTES de ver ningún resultado de estrategia. Solo se habían mirado la forma de los datos y el tamaño de la muestra.
Prior de quien lo escribe: **no dará dinero** tras costes. Si es así, se documenta como descartada.

## Qué se pregunta
¿Un bot que compre en pump.fun tokens recién lanzados, con el retraso y las comisiones reales de operar desde GMGN (no con un nodo propio),
tiene valor esperado positivo por operación, medido fuera de muestra y sobre TODOS los tokens nuevos (también los muertos)?

## Datos
- Recolector `tools/paper_collect.py`: lista los ~1.000 tokens más nuevos de pump.fun cada 2 min (todos, sin filtro) y, a los 45 min de vida,
  baja todos sus trades (hasta 25.000) con precio, lado, wallet e importe. API pública de pump.fun, solo lectura.
- Un token entra en la muestra por existir, no por haber subido. Los que nunca tuvieron un trade posterior a la creación quedan sin fill (se cuentan).
- Límite: la lista solo llega ~50 min atrás, así que no hay histórico de semanas; se acumula hacia delante (horas de recogida). Es una prueba de
  un régimen de mercado concreto, no de «las últimas semanas».

## Modelo de ejecución (supuestos, fijados antes)
- Tamaño: 0,05 SOL por operación (≈ 7 USD).
- Retraso señal → fill: **5 s** (principal). Sensibilidad: 3 s y 10 s. El fill es el precio del PRIMER trade real a partir de señal + retraso (no el de la señal).
- Comisiones por lado: pump.fun 1,25 % + GMGN 1 % = **2,25 %**. Propina/prioridad: **0,003 SOL por operación**. Sensibilidad: 0,001 y 0,006.
- Impacto propio: tamaño / (30 + SOL netos ya metidos en la curva) por lado.
- Salida sin trades posteriores (token muerto): precio del último trade × 0,5 (penalización), marcada.
- Entradas: una por token. Sin límite de capital simultáneo (optimista).

## Estrategias (todas fijadas aquí; nada se añade después de mirar)
- **S0 francotirador ciego**: compra en creación + retraso. Salidas: (TP +100 % / SL −30 % / tiempo 5 min) y (tiempo 60 s).
- **S1 confirmación por flujo**: señal en el primer trade de los primeros 180 s en que haya ≥ K compradores distintos y ≥ 3 SOL netos de entrada.
  K ∈ {10, 20, 40}; TP ∈ {+50 %, +100 %, +200 %}; SL ∈ {−25 %, −40 %}; salida por tiempo 10 min. 18 variantes.
- **Referencia aleatoria**: S1 con la señal movida a un instante aleatorio del token (mide si la señal aporta algo o es solo la salida).
Total: 21 variantes (se suman a las más de 2.900 del inventario y cuentan para el Deflated Sharpe).

## Cómo se juzga
- Tokens ordenados por hora de creación: el 60 % más antiguo = **selección**, el 40 % más reciente = **prueba**. La variante se elige solo en selección
  (mayor retorno medio neto con ≥ 30 operaciones) y se congela en un archivo antes de tocar la prueba. La prueba se corre UNA vez.
- Métricas por variante: operaciones, acierto, retorno medio neto por operación, mediana, retorno total con 0,05 SOL, bootstrap del retorno medio (IC 95 %),
  % de operaciones que pierden más del 80 %, y resultado sin sus 2 mejores operaciones.
- Se adopta (como idea a seguir probando, nunca como bot con dinero) solo si en prueba el IC 95 % del retorno medio queda por encima de 0 Y sobrevive a
  retraso 10 s y propina 0,006 SOL.
- Si no, se descarta y se dice así.

## Límites que se declaran de antemano
- Pocas horas de datos de un solo régimen. Un resultado positivo pediría días de recogida adicional antes de creerlo.
- Modelo de fill simplificado (sin competencia de bots por el mismo bloque ni fallos de transacción: ambos empeoran el resultado real).
- Los tokens sin trades suficientes no se pueden simular y se informan aparte.
