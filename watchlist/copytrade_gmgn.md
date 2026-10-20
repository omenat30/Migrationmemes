# Copy trading en GMGN con 0,4 SOL fijos (lo activas tú)

> Esto NO lo ejecuta el proyecto: activar copy trading exige firmar con tu clave privada de GMGN y mover dinero real, y ni la API de solo lectura ni yo tocamos eso.
> Cifras en dólares a SOL = 105 USD (0,4 SOL ≈ 42 USD por compra), copiando con 30 s de retraso, comisión 1 % e impacto 2 % por 1.000 USD. Son de HISTORIAL (dentro de muestra): no son una promesa.

## Ajustes que pides (compruébalos en la pantalla de GMGN; los nombres pueden variar)

- Compra: importe fijo 0,4 SOL por operación.
- Venta: automática, siguiendo las ventas de la wallet.
- Mi recomendación, si GMGN lo permite: límite de pérdida por posición del 60 % (el de las simulaciones) y deslizamiento máximo moderado.
- Empieza con 3-4 wallets, no con las 11.

## Wallets, de más a menos robustas copiando (columna «sin 2 mejores» = resultado si se quitan sus 2 mejores operaciones)

| Wallet | Ops/día | Tenencia | Expected R | Sin 2 mejores ($) | Peor caída ($) | Abiertas a la vez |
|---|---|---|---|---|---|---|
| `5LLTYLm8seMVkqyte1dF7eQLSCdMFhzVLbKJJ6369QiX` | 3.3 | 24.2 h | +2.44 | 2126 | 84 | 3.3 |
| `AcGLjWVZKRyELgmBbNmEx4DU6TqNDoMj8UM3yTix9yte` | 6.1 | 22 min | +0.52 | 1077 | 26 | 0.1 |
| `BcKqw3ZNH84jZjeLvYSq49twoMBbWSkujXw9k49f4vz4` | 3.3 | 24 min | +0.88 | 1625 | 106 | 0.1 |
| `6HJetMbdHBuk3mLUainxAPpBpWzDgYbHGTS2TqDAUSX2` | 2.4 | 48 min | +2.14 | 3281 | 265 | 0.1 |
| `DxM1hfY8FQ8dNGrucuJzhJcF8KRbjk8WBwrgKvQ9spPv` | 2.5 | 4.0 h | +0.76 | 651 | 367 | 0.4 |
| `2GtmuqG31LuuWQmKzeK72YjH5iALPkJycuQaEQGsFzLw` | 0.9 | 9.9 h | +2.45 | 871 | 165 | 0.4 |
| `AqSUfx6Y2e8eKYtkvx9AoRr8AvmRMGeoVUKFMcGyRcsN` | 12.0 | 12 min | +0.33 | 742 | 228 | 0.1 |
| `GAsnqm4XkNkPVgrAofNQ65jWf8f3tKCLHhE9ZqSy2AP1` | 1.5 | 48 min | +0.90 | 150 | 57 | 0.0 |
| `DMTgKsvm44d76mrY7sWUEvr9Tx7fsVc3XiadiwZBUAig` | 0.3 | 16 min | +2.56 | 94 | 136 | 0.0 |
| `GDpqhJgwzg8zcoEmVvGDiVRVnaa797ryvPnNqQVBjQrN` | 3.6 | 14 min | +0.39 | 23 | 133 | 0.0 |
| `3bzaJd5yZG73EVDz8xosQb7gfZm2LN5auFGh6wnP1n1f` | 2.9 | 61 min | +12.00 | 702 | 704 | 0.1 |

## Avisos

- 3bzaJd5yZG es la más frágil: su resultado lo dominan unas pocas operaciones enormes. GDpqhJgwzg casi no gana sin sus 2 mejores. DMTgKsvm44 apenas opera (0,3 al día).
- 6HJetMbdHB lleva desde el 1 de octubre sin vender y con compras abiertas: copiarla ahora es entrar en su racha de compras.
- 5LLTYLm8se aguanta ~24 h: con 0,4 SOL por posición y 3 abiertas a la vez son ~1,3 SOL parados.
- El panel marca la actividad reciente de cada una; revisa que sigan operando antes de activar.
- Revisa su saldo y movimientos de capital en el panel: varias tienen saldos bajos en SOL (2GtmuqG31L 0,16 SOL).
- Todo el historial es dentro de muestra. La prueba real es la columna «Desde que entró» del panel, que se llena sola con los días.
