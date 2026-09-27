# ADR 0012: Señales con procedencia y el primer adaptador real

- **Estado:** Aceptada
- **Fecha:** 2026-09-26
- **Depende de:** [ADR 0003](adr-0003-rls-deny-by-default.md), [ADR 0008](adr-0008-demo-production-isolation.md), [ADR 0009](adr-0009-async-job-runtime.md), [ADR 0011](adr-0011-action-gate.md)
- **Milestone:** 34

## Contexto

El plan maestro §32 pide para este milestone cuatro cosas: crear primero el
contrato, implementar un adaptador mock y un **adaptador real #1**, y persistir
procedencia. El §8 añade los nueve campos que hay que conservar por señal
—`provider, source, query, timestamp, market, value, confidence, raw_reference,
method`— y una frase que manda sobre el resto: **«nunca almacenar solo un número
final sin procedencia»**. El §9 prohíbe tocar todavía la fórmula del
`opportunity_score`: primero fuentes reales, después el score.

Lo que había: `ProductSignalProvider` existía desde la ADR 0008, pero su
contrato estaba moldeado sobre el mock. `get_candidates()` devolvía candidatos ya
cocinados con cinco señales inventadas y una explicación escrita a mano, y
`product_analyses.data` guardaba ese diccionario tal cual. Un 0,82 de demanda
inventado y un 0,82 medido eran **la misma fila**.

Y el problema de fondo: una fuente real no responde «aquí tienes cuatro
productos con su nivel de competencia». Responde «este término tuvo este interés
en este mercado en estas fechas». El contrato de la ADR 0008 no se puede
implementar con datos reales sin inventar la mitad.

## Decisión

### 1. El contrato son señales, no candidatos cocinados

`ProductSignalProvider.discover()` devuelve `CandidateSignals`, y cada señal es
un `Signal` con los nueve campos del §8 más `kind` (qué se midió) y `simulated`
(si es relleno). Un proveedor declara además `supports()`: qué señales sabe dar.

`supports()` no es adorno: es lo que permite componer sin adivinar. Un proveedor
real que solo sabe de demanda lo dice, y quien compone sabe qué hueco queda por
rellenar en vez de descubrirlo por la ausencia de una clave.

### 2. `method` es donde se dice la verdad incómoda

El número viaja lejos del sitio donde se produjo: de un adaptador a un agente, de
ahí a una fila, de ahí a una pantalla y quizá a una decisión. `method` viaja con
él y dice **qué es y qué no es**. Para el adaptador real, literalmente:

> monthly Wikipedia pageviews …, log-normalised … **PROXY FOR INTEREST — not
> purchase demand, not sales, not intent to spend.**

### 3. Adaptador real #1: Wikimedia Pageviews, y es un proxy

Mide cuánta gente consultó un artículo de una enciclopedia. **No es demanda de
compra ni ventas**, y no se va a presentar nunca como tal.

Se eligió sobre una API comercial con clave por una razón práctica que pesa más
de lo que parece: es pública, documentada, sin clave y sin coste, así que se pudo
**probar de verdad contra la fuente real** en este mismo milestone en vez de
quedar pendiente de dar de alta unas credenciales. El proyecto ya arrastra cinco
verificaciones que solo cierra un entorno real; añadir una sexta para estrenar un
adaptador habría sido empezar la casa por el tejado.

Sus límites son parte de la decisión: los términos de nicho tienen volúmenes
bajos (un artículo puede tener trece visitas al mes), una enciclopedia no es un
marketplace, y el proyecto lingüístico es una aproximación al mercado. Por eso la
confianza que emite está acotada a 0,75 y **nunca llega a 1**.

### 4. Ante un fallo, ausencia — nunca un cero

Si la API no responde, si el artículo no existe, si llega un 429 o si el cuerpo
no es el esperado, **no hay señal** para ese término. Un cero se leería como «no
hay demanda» cuando lo cierto es «no lo sabemos», y esa diferencia es justo la
que este milestone existe para sostener. Un término que falla tampoco se lleva
por delante a los demás: cada consulta vive su propia suerte.

### 5. Los candidatos salen de un catálogo de términos, y eso es un arranque

Una API de interés responde sobre términos que le des; no inventa productos. Los
términos viven en `terms.py`, versionados, y los `keywords` de la petición van
primero. **Esto es la pregunta, no la respuesta**: ninguna cifra sale de ahí.

Y es explícitamente **provisional**. Un catálogo escrito a mano no descubre
productos: solo mide los que alguien ya pensó. El descubrimiento de verdad
—marketplaces, minería de reseñas y problemas, señales sociales, distribución de
precios, persistencia de tendencia: los ocho ejes del §8— necesita fuentes y
mecanismos que este milestone no construye. Mientras esa lista sea el único
origen de candidatos, el sistema encuentra lo que ya sabíamos buscar.

### 6. Composición: lo real primero, el relleno después y marcado

`CompositeProductSignalProvider` recorre sus proveedores en orden y cada uno
aporta **solo las señales que ninguno anterior dio**. Nada se promedia: cada
señal sigue siendo de quien la produjo.

Con una consecuencia que conviene mirar de frente: hoy el relleno **no puede
completar a un candidato real**, porque descubre por término («Air fryer») y el
mock solo sabe de los suyos («Silicone kitchen organizer»). Así que un candidato
real se queda con su demanda medida, sin competencia y **sin score**. Es
correcto: la alternativa sería inventarle un nivel de competencia a un producto
real. Lo que hace falta no es rellenar mejor, sino una segunda fuente real de
competencia, que es Milestone 35 en adelante.

El relleno tampoco aporta candidatos propios cuando la fuente real encontró
alguno: eso convertiría un fallo de red en un descubrimiento.

**Y hay un problema debajo que este milestone no resuelve: identificar la misma
entidad entre proveedores.** Hoy dos señales se juntan si sus nombres coinciden
ignorando mayúsculas y espacios. Eso basta para un mock y una fuente, y **no
basta para dos fuentes reales**: «Air fryer», «Airfryer», «Freidora de aire» y un
ASIN de Amazon son el mismo producto para una persona y cuatro candidatos
distintos para este código. Sin resolución de entidades, añadir la segunda fuente
real no compone señales: duplica candidatos. Es un requisito del Milestone 35 en
adelante, no una mejora opcional.

### 7. `composite` cuenta como simulado donde no se admite lo simulado

Un despliegue en `staging` o `production` no puede usar `composite`, porque
**puede** servir fixtures. Ahí se usa `real`, y lo que la fuente real no sabe
queda ausente en vez de inventado. La ADR 0008 no se debilita: se aplica también
a la mezcla.

### 8. El score no cambia, pero dice de qué está hecho

La fórmula sigue siendo `demanda × factor de competencia` (§9). Lo nuevo es
`provenance`: `real`, `mixed`, `simulated` o `unknown`, y que un conjunto mixto
baja la confianza del agente a 0,6. Un número medio real no merece la misma fe
que uno medido, y darle el mismo 0,85 los igualaría.

Si faltan las señales que el score necesita, el score es `None`. No se sustituye
por un valor por defecto.

## Consecuencias

**A favor**

- De la base de datos se puede volver a responder «¿esto es real o inventado?»,
  que es exactamente lo que no se podía antes.
- El contrato está probado contra una fuente real, no solo contra el mock: se
  midió «Air fryer» de verdad (0,7483 de demanda, confianza 0,6939, trayectoria
  0,4271) con su URL cruda guardada.
- El mock sigue dando exactamente las mismas cifras que daba: este milestone
  cambia de dónde viene el dato, no el dato.
- La pantalla de Investigación distingue real, mixto, fixture y relleno de la
  propia pantalla — cuatro cosas que antes se veían igual.

**En contra**

- **Un candidato real hoy no tiene score.** Sin señal de competencia no hay
  fórmula, y la fórmula no se toca en este milestone (§9).
- **El catálogo de términos limita el descubrimiento** a lo ya pensado. Está
  escrito en el propio fichero y en el milestone; el riesgo es que dentro de tres
  milestones alguien lo tome por un buscador.
- **Una dependencia de red en el camino de un trabajo.** Hay timeout, un tope de
  peticiones por ejecución y ningún reintento propio: el runtime ya reintenta
  (ADR 0009), y reintentar dos veces en dos capas multiplica la espera.
- **`httpx` pasa a dependencia de ejecución.**
- **La señal es un proxy.** Se dice en todas partes, y aun así alguien la leerá
  algún día como demanda. La comparación mock/real del Milestone 35 existe en
  parte para poner ese límite a la vista con números.
- **La coincidencia por nombre no escala a dos fuentes reales.** Ver arriba: sin
  resolución de entidades, componer se convierte en duplicar.

## Alternativas descartadas

- **Una API comercial con clave** (Keepa, SerpAPI, SP-API). Mejor señal, más
  cerca de la compra; a cambio, credenciales y coste del propietario, y
  verificación aplazada. Entra cuando haya decisión de gasto, sobre este mismo
  contrato y sin tocarlo.
- **Añadir el adaptador real al contrato antiguo.** Habría obligado a inventar
  competencia, escalabilidad y riesgo regulatorio para cada término medido: lo
  contrario de lo que pide el §8.
- **Guardar la procedencia dentro de `product_analyses.data`.** Cero
  migraciones, y repite el error que el Milestone 32 acababa de corregir en el
  pipeline: lo consultable metido en un blob.
- **Que el mock aporte candidatos cuando lo real no encuentra nada**, para que la
  pantalla nunca se vea vacía. Rechazada: convertiría una avería en un
  descubrimiento.
- **Cambiar ya el `opportunity_score`** para que aproveche las señales nuevas.
  Prohibido explícitamente por el §9, y con razón: sin fuentes reales para todos
  los ejes, cualquier fórmula nueva sería una opinión con decimales.
