# Milestone 35 — Product Intelligence Real v1

**Fecha:** 27-09-2026 · **ADR:** [0013](../architecture/adr-0013-signal-evidence-and-comparison.md)
· **Anterior:** [Milestone 34](milestone-34-demo.md)

El plan maestro §32 pide aquí: «Primera investigación real […] Comparar
resultados contra mock. No eliminar mock». Cinco de los seis requisitos que
enumera —fuente real, fecha, mercado, procedencia, confianza, referencias
crudas— los cerró el Milestone 34. Lo que faltaba era **la comparación**, y
diseñarla obligó a mirar de frente algo que solo se sabía de oídas.

---

## Lo que se midió antes de decidir nada

Se le preguntó a Wikimedia por los nueve nombres de producto del mock.
**Ninguno existe como artículo.** «Wireless earbuds pro», «Silicone kitchen
organizer», «Travel cable organizer» son nombres inventados para una demo, no
conceptos del mundo.

Así que una comparación candidato a candidato daría un informe vacío **que
pasaría en verde sin enseñar nada**. Peor que no tenerlo: parecería que se
comparó algo.

## Qué cambia

### La comparación mide qué sabe cada uno

`POST /api/research/comparisons` ejecuta los dos proveedores para la misma
pregunta y guarda qué produjo cada uno: candidatos, solapamiento, cobertura por
tipo de señal, confianza media, señales medidas frente a inventadas y cuántos
candidatos quedan puntuables. Con datos reales, hoy:

| | Fixtures | Wikimedia |
|---|---|---|
| Candidatos | 3 | 4 |
| Con señal de demanda | 3 | 4 |
| **Con señal de competencia** | **3** | **0** |
| **Puntuables** | **3** | **0** |
| Confianza media | 0,30 | **0,71** |
| Señales medidas | 0 | 8 |

Lo medido es más fiable y **no alcanza para puntuar**. Eso era una frase en la
ADR 0012; ahora es una medida.

Cuando sí haya candidatos compartidos, el informe incluye el delta por señal
—el código ya lo hace—. Y un delta solo se calcula donde los dos hablaron:
restar contra una ausencia sería tratarla como un cero.

### El veredicto impide la lectura equivocada

«Cero en común» se lee como fallo si nadie lo explica. El informe lleva la
explicación dentro:

> Ningún candidato en común: fixtures propone 3 nombres inventados y
> wikimedia-pageviews mide 4 términos reales. No se pueden restar sus cifras; lo
> comparable es qué sabe medir cada uno.

Y si la fuente real no mide nada, el veredicto dice que **eso no significa que
no haya demanda**.

### Comparar no se hace donde los fixtures están prohibidos

Comparar exige ejecutar el mock, y la ADR 0008 no lo admite en `staging` ni
`production`. Una excepción «solo para un informe» vaciaría la regla, así que
allí la ruta responde 409 diciendo por qué.

### La evidencia mensual se guarda

El adaptador descargaba doce meses de visitas y **tiraba once**. Ahora cada
señal guarda las observaciones que la componen, con el valor **crudo** de la
fuente: la normalización a 0-1 vive en la señal, y aquí queda lo que de verdad
contestó la API. En filas —consultables— y no en un blob, por el mismo motivo
que los pasos del pipeline en el Milestone 32.

Una señal sin observaciones no es una señal con cero: es una que no se midió
así. El mock no tiene serie y no se le inventa una.

### El gráfico deja de ser una ilustración

«Tendencia de interés por fuente» enseñaba cuatro series inventadas pasara lo
que pasara. Ahora: si hay observaciones medidas enseña **esas**, con su insignia
de verificado y avisando de que son un proxy de interés; si no, enseña las de
demostración diciendo que lo son. **Nunca las dos mezcladas**: una leyenda no
arregla un gráfico mitad medido y mitad inventado.

### Y un informe en la pantalla

Tarjeta «Qué dice cada proveedor» en Investigación, con el veredicto y la tabla
de arriba.

## Lo que NO cambia, a propósito

- **`opportunity_score` sigue intacto** (plan maestro §9).
- **El mock sigue entero**: mismas cifras, mismo ganador, sus tests de
  regresión en verde. El plan lo pide explícitamente.
- **Una señal ausente sigue ausente.** Ni ceros, ni medias, ni imputaciones.
- **No hay resolución de entidades**, y el informe es la prueba de por qué hará
  falta (ADR 0013 §5).
- **No se ha contratado ninguna fuente comercial.**

## Candidatas comerciales para el Milestone 36

`docs/design/fuentes-comerciales-product-intelligence.md`: siete funciones
—discovery, intención comercial, ventas, competencia, precios, reseñas y
tendencias, y datos de marketplace— con qué evidencia aporta cada fuente, sus
limitaciones, cobertura, credenciales y coste **verificado en origen cuando se
pudo comprobar** y marcado como no verificado cuando no.

Tres lecturas, según el objetivo: **Keepa** (49 €/mes verificados) si lo que se
quiere es poder puntuar; **DataForSEO** (50 USD de saldo, sin cuota) si lo que
se quiere es intención comercial; **Reddit** si lo que se quiere es no gastar
todavía, aceptando que no cierra el hueco.

## Probarlo

```bash
cd backend && alembic upgrade head

curl -X POST localhost:8000/api/research/comparisons \
  -H 'Content-Type: application/json' -d '{"category":"home","market":"us"}'
curl -s localhost:8000/api/research/comparisons | python -m json.tool
```

## Verificación

- Backend: `ruff` y `mypy` limpios · **1190 tests** (1143 antes, +47).
- Frontend: `tsc` y `eslint` limpios · **288 tests** (280 antes, +8).
- `next build --webpack` en una copia, sin tocar el `.next` de desarrollo.
- **Humo contra Wikimedia de verdad**: «Air fryer» con sus doce meses
  persistidos (2025-09: 2.354 visitas … 2026-08: 2.194), 72 observaciones en
  total, valores crudos guardados y la señal normalizada en 0,7483 · el informe
  de comparación real con los números de la tabla de arriba · la comparación
  rechazada en `staging` y en `production` · y el mock intacto (0,82 de demanda
  para «Wireless earbuds pro», todo marcado como simulado).
- Migración ejecutada arriba y abajo, comparada columna a columna contra los dos
  modelos nuevos.
- Los tests de inventario del Milestone 29 hicieron su trabajo: las tres rutas
  nuevas fallaron hasta darles su acción y su categoría de lectura.

## No verificado

- Los **cinco pendientes de integración** siguen igual (ver
  [system-overview §17](../architecture/system-overview.md#17-pendientes-de-integración));
  ninguno bloqueaba este milestone.
- **La comparación en producción**: por diseño no existe allí.
- **La evolución del informe en el tiempo**: cada ejecución es una foto y nada
  vigila la deriva entre ellas.
- **Los costes marcados «sin verificar»** en el documento de fuentes
  comerciales.

## Lo que queda abierto

1. **Resolución de entidades entre proveedores** — prerrequisito de la segunda
   fuente real, no una mejora posterior (ADR 0013 §5).
2. **Segunda fuente real** de competencia o demanda comercial: sin ella, un
   candidato real sigue sin score. Decisión de gasto tuya, con el documento de
   candidatas encima de la mesa.
3. **Discovery real**: el catálogo de términos sigue siendo un arranque.
4. **El `opportunity_score` v2** del §9, cuando haya fuentes para sus ejes.
5. **Los otros cuatro dominios** siguen solo con mock.
