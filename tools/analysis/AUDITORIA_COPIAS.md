# Auditoría de las copias reales (wallet de trading en GMGN, 19–23 oct)

Datos: 81 posiciones (72 cerradas, 9 abiertas) leídas de la wallet pública del usuario. Scripts: `audit_copias.py`, `audit_copias2.py`.

## Resultado
- Cerradas: 3.897 USD invertidos, +68 USD por precios; GMGN da -143 USD realizado a 30 d (la diferencia, ~210 USD, son comisiones, propinas y deslizamiento que no están en los precios). Acierto 32%, mediana x0,89.
- Abiertas: 9 posiciones, restos valorados a precio de mercado 280 USD frente a 294 de coste (-14 USD). No son el problema.
- Curva por día de salida: 21-oct +253 USD, 22-oct -129, 23-oct -35.

## Dónde se pierde
1. **Tamaño doble o triple**: 12 operaciones de más de 60 USD (2×–6× la unidad de 40) suman -124 USD; las 60 de tamaño normal suman +192. Casi seguro varias wallets copiadas compraron el mismo token y se apilaron las entradas.
2. **Salidas en menos de 2 minutos**: 12 operaciones, -165 USD, 8% de acierto. Cinco perdieron del 42% al 74% con menos de un minuto de tenencia (el líder vende y el precio ya se ha hundido cuando llega la copia).
3. **Perfil de lotería**: las 5 mejores suman +598 USD y las 5 peores -232. Sin la mejor, el resultado es negativo.
4. **Retrasos de entrada de 3 a 30 min** en las wallets del panel que se pudieron atribuir (9 de 10 en negativo). 59 de las 72 operaciones cerradas no vienen de wallets del panel: hay que conocer la lista real de wallets copiadas.
5. Comisiones y deslizamiento: ~4–5% por ida y vuelta sobre 40 USD, que se come el margen cuando la mediana es x0,89.

## Hipótesis "sin esos errores" (retrospectiva, no es una prueba)
Quitando salidas <2 min: +233 USD; quitando además las entradas de más de 60 USD: +286 USD (sobre ~3.400 USD invertidos, antes de comisiones).

## Atribución a wallets del panel (26-oct, tras bajar 9 días de las 91 wallets)
`atribuir_copias.py`: cada compra del usuario se atribuye a la wallet del panel que compró el mismo token entre 2 min después y 30 min antes (la más cercana). Cubre 46 de 75 cerradas; las 29 restantes (-119 USD) no vienen de wallets del panel.
- **AqSUfx6Y**: 12 operaciones, 2 ganadoras, -227 USD, retraso 0 s. Sus propias posiciones en esos tokens hicieron lo mismo (x0,55 mediano), así que la pérdida es de la wallet, no de la copia. Últimos 9 días: ROI 4 %, 26 % de acierto. Marcada como descartada en el panel.
- Con 1–2 operaciones (BTAKK8cx, 2GqMs4yi, 3eGj9qx6, HxAu7MEN) no hay evidencia suficiente. 2GqMs4yi ganó en el líder (x1,98) y perdió en la copia por retraso de 52 s a 25 min.
- Aportan: DxM1hfY8 +294 USD (una x9,6), BcKqw3ZN +76, 3bzaJd5y +29, 5LLTYLm8 +14.
