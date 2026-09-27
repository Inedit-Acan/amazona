# ADR 0014: Cuándo dos nombres son el mismo producto

- **Estado:** Aceptada
- **Fecha:** 2026-09-27
- **Depende de:** [ADR 0008](adr-0008-demo-production-isolation.md), [ADR 0012](adr-0012-product-intelligence-adapters.md), [ADR 0013](adr-0013-signal-evidence-and-comparison.md)
- **Milestone:** 36

## Contexto

La [ADR 0012 §6](adr-0012-product-intelligence-adapters.md) y la
[ADR 0013 §5](adr-0013-signal-evidence-and-comparison.md) dejaron escrito que la
identificación de entidades era un prerrequisito de la segunda fuente real: «Air
fryer», «Airfryer», «Freidora de aire» y un ASIN son el mismo producto para una
persona y cuatro candidatos distintos para este código. Y la 0013 añadía que
hacerlo entonces «sería resolver un conjunto vacío», porque mock y fuente real no
comparten ni un candidato.

**Lo primero que se midió al abrir este milestone fue eso, y era falso para el
caso que ya existe hoy con una sola fuente.**

El catálogo de términos deduplicaba con `term not in asked`, igualdad exacta de
cadena. Así que `terms_for("home", ["air fryer"])` devolvía `air fryer` **y** `Air
fryer`. Y la API de Wikimedia no normaliza la primera letra del título. Medido el
27-09-2026 contra la fuente real:

| artículo | HTTP | meses | visitas | demanda | confianza |
|---|---|---|---|---|---|
| `Air_fryer` | 200 | 12 | 30.897 | **0,7483** | 0,6939 |
| `air_fryer` | 200 | 4 | 5 | **0,1297** | 0,2285 |

Son dos páginas distintas: la segunda es una redirección con visitas propias. El
resultado, con un solo proveedor real y sin tocar nada: quien pasaba el keyword
`air fryer` en minúsculas —lo natural— gastaba **dos** de sus ocho peticiones en
lo mismo y persistía **dos productos** para un solo objeto. Uno con el 0,7483 que
la ADR 0012 cita como su medición verificada, y un gemelo con 0,1297 que parece un
producto que no le interesa a nadie. Ninguno marcado como duplicado, los dos
reales, los dos auditables.

Y un segundo caso, también presente: `products` no tenía unicidad ni búsqueda
previa, y `ResearchService` creaba una fila por candidato **en cada ejecución**.
Dos investigaciones sobre `home` dejaban dos «Air fryer» sin relación entre sí, y
las doce observaciones mensuales que el Milestone 35 empezó a guardar quedaban
repartidas entre ellas. La pregunta que justificó aquella tabla —«¿cómo se movió
el interés el último trimestre?»— no se podía contestar por producto.

## Decisión

### 1. Determinista o declarado. Nunca por parecido

Dos nombres son el mismo producto por **normalización** —una transformación
determinista: sin diacríticos, en minúsculas, sin puntuación, sin el paréntesis de
desambiguación de Wikipedia— o por **alias escrito a mano** en `aliases.py`. Por
nada más. Lo que no case por una de esas dos vías **se queda separado**.

No hay distancia de edición, ni similitud, ni umbral, y no es una simplificación
temporal: es la decisión. Un 0,85 de parecido uniría «Air fryer» con «Air dryer»
algún día y nadie sabría qué día empezó a hacerlo. Es el equivalente en identidad
al cero inventado que el Milestone 34 prohibió.

Los dos errores posibles no son simétricos, y por eso se prefiere quedarse corto:
**dos candidatos que eran uno son un duplicado visible; un candidato que eran dos
es una medición contaminada que nadie puede deshacer.** Un `False` de
`same_entity` no dice que sean productos distintos: dice que nadie ha establecido
que sean el mismo, igual que una señal ausente no es un cero.

### 2. Partir palabras compuestas es una opinión, y se firma

`airfryer` no se convierte en `air fryer` por normalización, porque hacerlo
necesita un léxico y un léxico es una opinión sobre qué palabras existen. Esos
casos viven en un catálogo versionado donde cada entrada tiene autor y fecha en
git, y donde una revisión puede discutirla.

El catálogo tiene versión (`v1`) y **la versión viaja en el motivo de cada
fusión** (`alias:v1`), para que una identidad resuelta hace tres meses se pueda
atribuir a la lista que estaba escrita entonces y no a la de hoy.

Lo que **no** entra en el catálogo importa tanto como lo que entra: `coffee
machine` no apunta a `Espresso machine` —una cafetera de goteo no es una de
espresso— ni `Mini projector` a `Video projector`. Y no entran los nombres del
mock: mapear `Portable phone charger` a `Power bank` fabricaría un solapamiento
falso entre fixtures y fuente real, que es exactamente lo que la ADR 0013 rechazó
al descartar «añadir los términos semilla al mock». El informe de comparación
sigue diciendo cero candidatos en común porque sigue siendo verdad.

### 3. Las traducciones quedan fuera, y no por descuido

Aliasar `Freidora de aire` a `Air fryer` era el ejemplo que las ADR 0012 y 0013
usaban para motivar este trabajo. **Medido antes de escribirlo, resulta que sería
una regresión.** Contra la API real, el 27-09-2026:

| proyecto | artículo | HTTP | visitas (12 meses) |
|---|---|---|---|
| `es.wikipedia` | `Air fryer` | **404** | — |
| `es.wikipedia` | `Freidora de aire` | 200 | **12.099** |

`PROJECT_FOR_MARKET` manda `market=es` a `es.wikipedia`. Canonicalizar al inglés
cambiaría una medición que funciona por un 404. Resolver idiomas no necesita un
nombre canónico único: necesita **un nombre por mercado**, y rellenar títulos de
artículo en alemán o francés a ojo sería inventar, que es lo que esta ADR prohíbe
en su primer punto.

Así que hoy «Air fryer» y «Freidora de aire» son dos candidatos, y el sistema no
finge saber que son uno. El mecanismo que lo cerraría honestamente está
identificado y es gratuito: los *langlinks* de Wikimedia dan la equivalencia entre
artículos de distintos idiomas **desde una fuente**, no desde una suposición. Es
trabajo de otro milestone.

### 4. Un producto se busca antes de crearse, por identidad y categoría

`ResearchService` resuelve la identidad del candidato y busca un producto con esa
clave **en esa categoría** antes de crear una fila. Si existe, las señales y las
observaciones se acumulan sobre él; cada ejecución sigue dejando su propio
`ProductAnalysis` con su `correlation_id`, así que la historia por ejecución no se
pierde.

La categoría entra en la búsqueda porque viene de la petición y no de la fuente:
el mismo término pedido bajo dos categorías son dos afirmaciones distintas, y
unirlas reescribiría en silencio la primera. Es un límite conocido, escrito aquí y
con su test.

`identity_key` **no es única** en la tabla. Aquí también viven productos dados de
alta a mano, y una restricción única impediría crear dos cosas que la
normalización colapse: decidir que son la misma es del catálogo de alias, no de un
índice de la base de datos.

### 5. Cada fusión guarda su motivo, en filas

`product_identity_aliases` anota con qué nombre llegó algo, a qué identidad se
resolvió, por qué vía y en qué ejecución. Una fusión sin motivo escrito es
indistinguible de un error, y «¿por qué estos dos son uno?» tiene que poder
contestarse desde la base de datos meses después.

En filas y no en un JSON por el mismo motivo que los pasos del pipeline en el
Milestone 32 y las observaciones en el 35: es consultable y en un blob estaría
escondido. Solo se anota lo que **difiere**: una fila por cada coincidencia trivial
escondería las que importan.

Y se anota también **la palabra que escribió quien pidió la investigación**. El
catálogo canonicaliza antes de llamar a la fuente, así que un `AIRFRYER` nunca
llega a la API y el `query` de la señal dice `Air fryer` —que es la verdad sobre la
medición—. Sin esta fila, la pregunta original se perdería justo cuando alguien la
busque.

### 6. La misma clave en los cuatro sitios donde se comparan nombres

`terms_for` (para no preguntar dos veces), `CompositeProductSignalProvider` (para
componer en vez de duplicar), `comparison.normalise` (para que el informe no diga
«cero en común» por una mayúscula) y `ResearchService` (para no duplicar filas).
Cuatro comparaciones que antes eran tres implementaciones distintas de «casi lo
mismo».

Cuando el término de quien pregunta y uno del catálogo son el mismo producto, se
manda **el del catálogo**: está revisado y versionado, y el de quien pregunta es
texto libre. No es estética — es la diferencia entre medir 30.897 visitas y medir
5.

### 7. La plaza de `real` sigue siendo una, y se decide cuando haga falta

`Settings.product_intelligence_provider` es un solo `ProviderKind` y
`BUILDERS[(PRODUCT_INTELLIGENCE, REAL)]` apunta a Wikimedia: hay **una** plaza de
`real` por dominio. Con dos fuentes reales hay que decidir qué significa `real`: un
compuesto de reales que —a diferencia de `composite`— no sea simulado, o una
configuración en lista.

**No se decide aquí.** Sin un segundo adaptador escrito sería infraestructura por
la infraestructura, exactamente el motivo por el que la
[ADR 0008 §1](adr-0008-demo-production-isolation.md) no creó los cinco paquetes de
dominio antes de tiempo. Queda registrado como decisión pendiente del milestone
que traiga la fuente.

## Consecuencias

**A favor**

- El duplicado medido desaparece: `terms_for("home", ["air fryer"])` pregunta una
  vez, por el artículo que tiene 30.897 visitas, y persiste un candidato con 0,7483
  en vez de dos.
- Las observaciones mensuales se acumulan sobre un producto, así que la serie que
  el Milestone 35 empezó a guardar por fin se puede leer como serie.
- La segunda fuente real deja de arrastrar este trabajo: el día que haya clave, el
  milestone es «escribir el adaptador», no «escribir el adaptador y además esto».
- El informe de comparación del Milestone 35 llega a **la misma conclusión**: cero
  candidatos en común, el mock puntúa el 100 % de los suyos con confianza 0,30 y lo
  real el 0 % con confianza alta. Y pregunta **exactamente los mismos términos**
  que antes del milestone: se reprodujo la función anterior y su lista es idéntica
  en las tres categorías y en los dos límites.
  Lo que no coincide son los recuentos exactos: hoy se miden **5 candidatos con
  confianza 0,7063 y 10 señales**, donde el Milestone 35 anotó 4 con 0,71 y 8. La
  fuente contestó hoy a los cinco términos y aquel día contestó a cuatro; no se le
  atribuye causa, porque cualquiera sería una conjetura. Es la misma advertencia que
  la [ADR 0013](adr-0013-signal-evidence-and-comparison.md) dejó escrita: **el
  informe es una foto**, y una foto de una fuente viva no se repite.

**En contra**

- **El catálogo de alias es trabajo manual y no escala.** Once entradas hoy; un
  discovery real que proponga cientos de términos lo desbordará, y entonces habrá
  que decidir de dónde sale la equivalencia sin dejar de ser declarada.
- **Los idiomas siguen sin resolverse**, y era el ejemplo que motivaba esto.
- **Dos categorías siguen duplicando** el mismo producto.
- **El relleno de la migración no aplica el catálogo de alias**: una fila anterior
  al milestone llamada `airfryer` conserva su propia clave y su duplicado
  preexistente no se resuelve solo. Congelar una lista que cambia daría la ilusión
  de estar al día.
- **Reutilizar el producto cambia lo que ven las pantallas**: un producto acumula
  varios análisis, y dos ejecuciones del pipeline sobre la misma categoría
  convergen en el mismo producto y en el mismo `store_slug`. Se comprobó que todos
  los lectores de `ProductAnalysis` ya tomaban el último o filtraban por
  ejecución; dos tests que codificaban el supuesto contrario se reescribieron.
- **`opportunity_score` sigue intacto** y un candidato real sigue sin score: esto
  no era el hueco de competencia y no lo cierra.

## Alternativas descartadas

- **Similitud con umbral** (Levenshtein, trigramas, *embeddings*). Uniría «Air
  fryer» con «Air dryer» algún día sin que nadie pudiera decir cuándo empezó. Es
  el cero inventado con otro disfraz.
- **Hacerlo cuando entre la segunda fuente**, como decían las ADR 0012 y 0013.
  Descartado porque lo medido demuestra que el conjunto no está vacío hoy: el
  duplicado ya existe, ya persiste números y ya engaña.
- **No tocar `ResearchService`** y limitarse a deduplicar dentro de una ejecución.
  Habría dejado la duplicación entre ejecuciones, que es la que rompe la serie
  mensual que el Milestone 35 acababa de construir.
- **Hacer `identity_key` única.** Impediría dar de alta a mano dos productos que la
  normalización colapse, y convertiría una decisión de catálogo en una restricción
  de esquema.
- **Traducciones en el catálogo.** Medido: cambiaría 12.099 visitas reales por un
  404.
- **Un alias por cada nombre que llega, aunque coincida.** Una fila por cada
  coincidencia trivial escondería las fusiones que importan.
