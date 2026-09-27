# ADR 0013: La evidencia detrás de cada señal, y qué significa comparar

- **Estado:** Aceptada
- **Fecha:** 2026-09-27
- **Depende de:** [ADR 0003](adr-0003-rls-deny-by-default.md), [ADR 0008](adr-0008-demo-production-isolation.md), [ADR 0012](adr-0012-product-intelligence-adapters.md)
- **Milestone:** 35

## Contexto

El plan maestro §32 pide para este milestone: «Primera investigación real.
Requisitos: fuente real, fecha, mercado, signal provenance, confidence, raw
references. **Comparar resultados contra mock. No eliminar mock**».

Cinco de los seis requisitos los cerró el Milestone 34 y están verificados
contra la API real. Lo que quedaba era la comparación — y al diseñarla apareció
un problema que obliga a decidir qué significa comparar.

**Medido antes de decidir nada**: se le preguntó a Wikimedia por los nueve
nombres de producto del mock. **Ninguno existe como artículo.** «Wireless
earbuds pro», «Silicone kitchen organizer», «Travel cable organizer»… son
nombres inventados para una demo, no conceptos del mundo. La intersección entre
lo que mide una fuente real y lo que se inventa el mock es **vacía**.

## Decisión

### 1. La comparación es estructural, no candidato a candidato

Restar valores exige que los dos proveedores hablen del mismo producto, y hoy no
hay ninguno en común. Un informe de deltas saldría vacío y **pasaría en verde
sin enseñar nada**, que es peor que no tenerlo: daría la impresión de que se
comparó algo.

Lo que se compara es **qué sabe cada uno**: cuántos candidatos produce, cuántos
comparten, qué señales cubre, cómo se reparte la confianza y cuántos candidatos
quedan puntuables. Cuando haya candidatos compartidos —y algún día los habrá—
el informe incluye además el delta por señal; el código ya lo hace, simplemente
hoy esa lista sale vacía **y el veredicto explica por qué**.

Un delta solo se calcula donde los dos hablaron. Donde uno calla no hay
diferencia que medir: restar contra una ausencia sería tratarla como un cero, y
eso es exactamente lo que el Milestone 34 prohibió.

### 2. El veredicto tiene que impedir la lectura equivocada

«Cero en común» se lee como fallo. El informe lleva una frase escrita para que
no se lea así: *«Ningún candidato en común: fixtures propone N nombres
inventados y wikimedia-pageviews mide M términos reales. No se pueden restar sus
cifras; lo comparable es qué sabe medir cada uno.»*

Y cuando la fuente real no mide nada, el veredicto dice que **eso no significa
que no haya demanda**. Un informe que se malinterpreta es un informe que hace
daño.

### 3. Comparar no se hace donde los datos simulados están prohibidos

Comparar exige ejecutar el mock. La ADR 0008 prohíbe los datos simulados en
`staging` y `production`, y una excepción «solo para un informe» es exactamente
la clase de excepción que vacía una regla. Así que allí la comparación se
rechaza diciendo por qué.

### 4. La evidencia mensual se persiste, en filas

El adaptador ya descargaba doce meses de visitas y **tiraba once**: guardaba el
agregado. Ahora cada señal guarda las observaciones que la componen
(`product_signal_observations`), con el valor **crudo** de la fuente — la
normalización a 0-1 vive en la señal, y aquí queda lo que de verdad contestó la
API.

En filas y no en un JSON por el mismo motivo que los pasos del pipeline en el
Milestone 32: es consultable —«¿cómo se movió el interés el último trimestre?»—
y un blob lo escondería. El informe de comparación, en cambio, **sí** va en
JSON: un informe se lee entero, y nadie va a filtrar comparaciones por cobertura
de competencia. Si algún día esa pregunta existe, tendrá su tabla.

Una señal sin observaciones no es una señal con cero observaciones: es una que
no se midió así. El mock no tiene serie y no se le inventa una.

### 5. La resolución de entidades todavía no

El emparejamiento por nombre normalizado es deliberadamente ingenuo: «Air fryer»
y «Airfryer» no se juntan. Resolver eso ahora sería resolver un conjunto vacío.

Este informe existe, entre otras cosas, **para demostrar con números que hará
falta**: cuando entre la segunda fuente real, componer sin resolver duplicará
candidatos en vez de enriquecerlos. Es un prerrequisito de ese trabajo, no una
mejora encima.

### 6. El gráfico enseña una cosa o la otra, nunca las dos mezcladas

La pantalla de Investigación tenía un gráfico de «interés por fuente» con cuatro
series inventadas. Ahora, si hay observaciones medidas, enseña **esas** y dice
que son un proxy de interés; si no las hay, enseña las de demostración y dice
que lo son. Mezclar series medidas e inventadas en unos mismos ejes produce un
gráfico que no se puede leer, y una leyenda no arregla eso.

## Consecuencias

**A favor**

- Los límites del Milestone 34 pasan de ser una frase en una ADR a ser números
  medidos: el mock puntúa el 100 % de sus candidatos con confianza 0,30, y lo
  real puntúa el 0 % con confianza 0,71.
- La evidencia está guardada: un número agregado se puede auditar contra las
  doce medidas que lo componen sin volver a llamar a la API.
- El gráfico de la pantalla deja de ser una ilustración cuando hay datos.
- El mock sigue intacto, como pide el plan: mismas cifras, mismo ganador.

**En contra**

- **El informe es una foto**, no una serie: cada ejecución guarda su
  comparación, pero nada vigila la evolución entre ellas.
- **Volumen**: doce filas de observación por señal real. Acotado por el tope de
  peticiones del adaptador, pero crece con cada investigación.
- **La comparación no se puede hacer donde más querría verse.** En producción no
  hay informe, por diseño.
- **Sigue sin haber score para candidatos reales.** Este milestone mide el
  problema; resolverlo necesita una segunda fuente y una decisión de gasto
  (`docs/design/fuentes-comerciales-product-intelligence.md`).

## Alternativas descartadas

- **Comparar candidato a candidato y ya.** Daría un informe vacío que parece
  correcto.
- **Preguntarle a la fuente real por los nombres del mock** para forzar un
  solapamiento. Se probó: cero de nueve. Y aunque alguno existiera, mediría el
  interés por un nombre de fantasía, no por el producto.
- **Añadir los términos semilla al mock** para que ambos hablen de lo mismo.
  Sería inventar cifras de competencia y escalabilidad para productos reales:
  justo lo prohibido.
- **Sombra automática**: comparar en cada investigación real sin que nadie lo
  pida. Duplica trabajo en cada ejecución y no se puede hacer donde el mock está
  prohibido, así que el histórico tendría agujeros justo donde importa.
- **Guardar las observaciones en un JSON dentro de la señal.** Una migración
  menos y el mismo error que el Milestone 32 corrigió en el pipeline.
