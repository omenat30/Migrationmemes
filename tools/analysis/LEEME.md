# Scripts de análisis puntual (usados el 20-21 oct 2026)

Son los scripts ad hoc con los que se obtuvieron los números de `HIPOTESIS_v7.md` y de `AUDITORIA_REGLAS.md` que no salen del código principal
(`radar/`). Tienen **rutas del directorio temporal de esa sesión** (variable `S` al principio de cada uno): hay que ajustarlas para reproducirlos.
No forman parte del barrido diario.

| Script | Qué calcula |
|---|---|
| `poll_live.py` | sondeo repetido de `/v1/user/smartmoney` y `/v1/user/kol`; guarda cada operación con su mcap |
| `bands.py` | franjas de mcap de entrada por wallet y R copiando (ventas de ≤ 30 s sin ventaja) |
| `mcap.py` | análisis por tramo de mcap de una wallet, umbral mínimo y comprobación en dos mitades |
| `near_verify.py` | criterio «cerca de migrar»: ≥ 15 entradas, R ≥ 0,3, positivo sin las 2 mejores y en las dos mitades, ≤ 35 % de ventas en 30 s |
| `clusters.py` | clusters por co-entrada: ≤ 10 s en ≥ 10 tokens y ≥ 20 % de los de la menor |
| `pattern3.py` | patrones en `migrants`: repetidoras en la franja 24k-120k USD, lanzamientos en paquete, pares que entran a la vez |
| `mig2_docs.py` | resumen por franjas (`mig`) y etiquetas (`cluster`, `excluded`) que se escribieron en la base de datos del panel |
