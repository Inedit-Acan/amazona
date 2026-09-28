# Milestone 36 — Resolución de entidades

**Fecha:** 27-09-2026 · **ADR:** [0014](../architecture/adr-0014-entity-resolution.md)
· **Depende de:** [0012](../architecture/adr-0012-product-intelligence-adapters.md)
· [0013](../architecture/adr-0013-signal-evidence-and-comparison.md)

El plan maestro §32 termina en el Milestone 35, así que el alcance de éste se
decidió antes de escribir código, entre tres candidatos: resolución de entidades,
una segunda fuente real o discovery real. Se eligió el primero por cuatro razones,
y la primera apareció al medir.

## Lo que se midió antes de decidir nada

Las ADR 0012 §6 y 0013 §5 daban la resolución de entidades por **prerrequisito de
la segunda fuente**, y la 0013 añadía que hacerla antes «sería resolver un conjunto
vacío». Eso era cierto para el caso mock↔fuente real, y **falso para el caso que ya
existía con una sola fuente**.

`terms_for` deduplicaba con igualdad exacta de cadena, así que
`terms_for("home", ["air fryer"])` devolvía `air fryer` **y** `Air fryer`. Y la API
de Wikimedia no normaliza la primera letra del título:

| artículo | HTTP | meses | visitas | demanda | confianza |
|---|---|---|---|---|---|
| `Air_fryer` | 200 | 12 | 30.897 | **0,7483** | 0,6939 |
| `air_fryer` | 200 | 4 | 5 | **0,1297** | 0,2285 |

Dos páginas distintas: la segunda es una redirección con visitas propias. Quien
pasaba el keyword en minúsculas —lo natural— gastaba **dos** de sus ocho peticiones
en lo mismo y persistía **dos productos** para un solo objeto: uno con el 0,7483
que la ADR 0012 cita como su medición verificada, y un gemelo con 0,1297 que parece
un producto que no le interesa a nadie. Ninguno marcado como duplicado, los dos
reales.

Y un segundo duplicado, también presente: `products` no tenía ni unicidad ni
búsqueda previa, y `ResearchService` creaba una fila por candidato **en cada
ejecución**. Dos investigaciones sobre `home` dejaban dos «Air fryer» sin relación,
y las doce observaciones mensuales del Milestone 35 quedaban repartidas entre
ellas: la serie que justificó aquella tabla no se podía leer por producto.

## Qué cambia

### La identidad es determinista o declarada, nunca por parecido

`identity.py` (función pura) resuelve un nombre a una clave: sin diacríticos, en
minúsculas, sin puntuación y sin el paréntesis de desambiguación de Wikipedia
—`Belt (clothing)` y `Belt` son el mismo cinturón—. Lo que la normalización no
puede unir —`airfryer` con `Air fryer`— vive en `aliases.py`, un catálogo escrito a
mano, versionado en git y con once entradas.

**No hay umbral de similitud, y no es una simplificación temporal**: un 0,85 de
parecido uniría «Air fryer» con «Air dryer» algún día y nadie sabría qué día
empezó. Los dos errores no son simétricos: dos candidatos que eran uno son un
duplicado visible, y un candidato que eran dos es una medición contaminada que
nadie puede deshacer.

La mitad de los tests de identidad comprueban que algo **no** se une.

### Se pregunta una vez, y con la forma del catálogo

`terms_for` deduplica por identidad y recorta **después** de resolver, para que el
tope sean ocho productos distintos y no ocho casillas con duplicados dentro. Cuando
el término de quien pregunta y uno del catálogo son el mismo producto, se manda el
del catálogo: está revisado y versionado, y el de quien pregunta es texto libre.
No es estética — es la diferencia entre medir 30.897 visitas y medir 5.

Verificado: con la lista de términos vacía, la selección es **idéntica** a la de
antes del milestone en las tres categorías y en los dos límites. Este cambio no
mueve lo que ya se preguntaba.

### Un producto se busca antes de crearse

`ResearchService` resuelve la identidad y busca por clave **y categoría** antes de
crear la fila. Si el producto existe, las señales y observaciones se acumulan sobre
él, y cada ejecución sigue dejando su propio `ProductAnalysis` con su
`correlation_id`: la historia por ejecución no se pierde.

La categoría entra en la búsqueda porque viene de la petición y no de la fuente: el
mismo término bajo dos categorías son dos afirmaciones distintas y unirlas
reescribiría la primera en silencio. Límite conocido, escrito y con test.

### Cada fusión guarda su motivo

`product_identity_aliases` anota con qué nombre llegó algo, a qué identidad se
resolvió, por qué vía (`normalised` o `alias:v1`, con la versión del catálogo
dentro) y en qué ejecución. Una fusión sin motivo escrito es indistinguible de un
error.

Incluye **la palabra que escribió quien pidió la investigación**. El catálogo
canonicaliza antes de llamar a la fuente, así que un `AIRFRYER` nunca llega a la API
y el `query` de la señal dice `Air fryer` —que es la verdad sobre la medición—. Sin
esta fila, la pregunta original se perdería justo cuando alguien la busque. Esto se
descubrió ejecutando el humo real: la tabla salía vacía en el camino que más se usa.

### La misma clave en los cuatro sitios donde se comparan nombres

`terms_for`, `CompositeProductSignalProvider`, `comparison.normalise` y
`ResearchService`. Antes eran tres implementaciones distintas de «casi lo mismo».

### Y la pantalla lo dice

`/api/products` publica `identity_key` y `also_known_as` (nombre + motivo), y la
tarjeta de cada candidato en Investigación enseña «También llegó como «airfryer»
(alias declarado (catálogo v1))». Una fusión que no se ve es indistinguible de un
error. La lógica va en `lib/research-view.ts` con sus tests; la tarjeta solo
presenta.

## Lo que NO cambia, a propósito

- **`opportunity_score` sigue intacto** (plan maestro §9). Esto no era el hueco de
  competencia y no lo cierra: un candidato real sigue sin score.
- **No se ha contratado nada.** Ninguna fuente de pago, ninguna credencial nueva.
- **El mock sigue entero**, con sus mismas cifras y sus tests de regresión.
- **Ningún alias apunta a un nombre del mock.** Mapear `Portable phone charger` a
  `Power bank` fabricaría un solapamiento falso entre fixtures y fuente real, que
  es lo que la ADR 0013 rechazó al descartar «añadir los términos semilla al mock».
- **Las traducciones se quedan fuera**, y no por descuido: ver abajo.
- **La plaza de `real` sigue siendo una.** Con dos fuentes reales habrá que decidir
  qué significa `real`; hacerlo hoy, sin un segundo adaptador escrito, sería
  infraestructura por la infraestructura (ADR 0014 §7).

## La desviación respecto a lo aprobado: las traducciones

El alcance aprobado incluía este criterio: «`Air fryer` / `Airfryer` / `Freidora de
aire` resuelven a la misma identidad por alias declarado». **Se cumplen los dos
primeros y el tercero se retiró, medido:**

| proyecto | artículo | HTTP | visitas (12 meses) |
|---|---|---|---|
| `es.wikipedia` | `Air fryer` | **404** | — |
| `es.wikipedia` | `Freidora de aire` | 200 | **12.099** |

`PROJECT_FOR_MARKET` manda `market=es` a `es.wikipedia`. Aliasar al inglés
cambiaría una medición que funciona por un 404. Resolver idiomas no necesita un
nombre canónico único: necesita **un nombre por mercado**, y rellenar títulos de
artículo en alemán o francés a ojo sería inventar — lo que esta ADR prohíbe en su
primer punto.

El mecanismo honesto está identificado y es gratuito: los *langlinks* de Wikimedia
dan la equivalencia entre idiomas **desde una fuente**. Queda para otro milestone.

## Límites que hay que tener presentes

Cuatro cosas que este milestone **no** resuelve y que conviene no descubrir por
sorpresa. Las cuatro tienen su test o su comprobación, y ninguna es un descuido.

### 1. Los alias no cruzan idiomas

«Air fryer» y «Airfryer» son un producto; «Freidora de aire» **sigue siendo otro
candidato**. El motivo está medido arriba: aliasar al inglés cambiaría 12.099
visitas reales de `es.wikipedia` por un 404. Hace falta un nombre **por mercado**,
no un nombre canónico único, y rellenar títulos de artículo a ojo sería inventar.
Lo cerrarían los *langlinks* de Wikimedia, que dan la equivalencia desde una
fuente.

### 2. Los datos anteriores al milestone conservan su clave, y su duplicado

La migración rellena `identity_key` con **solo la normalización**, sin el catálogo
de alias. La copia de `fold()` va congelada dentro de la migración —tiene que
poder ejecutarse dentro de tres años— y congelar además una lista que cambia daría
la ilusión de estar al día.

Consecuencia concreta: una fila anterior al milestone llamada `airfryer` recibe la
clave `airfryer`, no `air fryer`, y la primera investigación que mida `Air fryer`
creará su propia fila. **Ese duplicado preexistente no se resuelve solo.** Hay un
test que lo fija como comportamiento esperado en vez de dejarlo a la sorpresa, y
otro que avisa el día que la copia congelada y la de la aplicación divergan.

Quien quiera limpiarlos tendrá que hacerlo a mano o con un milestone que lo haga
explícito; no se hace en silencio al pasar.

### 3. `identity_key` es nulable y **no** es única

Nulable porque las filas anteriores al milestone que nadie ha vuelto a investigar
existen y su clave se rellenó a partir del nombre; `/api/products` la publica como
`null` cuando falta, y eso significa «no resuelta», no «sin identidad».

No única a propósito: en `products` también viven productos dados de alta a mano, y
una restricción única impediría crear dos cosas que la normalización colapse.
**Decidir que dos nombres son el mismo producto es del catálogo de alias, no de un
índice de la base de datos.** El índice que sí existe es de búsqueda
(`identity_key` + `category`). Hay un test que fija que dos filas pueden compartir
clave.

### 4. Las ejecuciones convergen, y eso se ve en otras pantallas

Dos investigaciones —o dos ejecuciones del pipeline— sobre la misma categoría
**aterrizan en el mismo producto**. Es lo correcto: es el mismo producto. Lo que
cambia respecto a antes:

- Un producto acumula **varios** `ProductAnalysis`. Se comprobó antes de tocar nada
  que todos los lectores ya tomaban el último (`order_by(created_at.desc()).first()`)
  o filtraban por `correlation_id`.
- Dos ejecuciones del pipeline comparten `store_slug`, porque el slug sigue al
  producto — que es lo que `generate_store_slug` promete desde siempre. Lo que no
  puede colisionar es el slug de dos productos distintos con el mismo nombre, y eso
  sigue cubierto en `tests/unit/test_ecommerce_content.py`.
- Sus tiendas, listados y campañas se acumulan sobre esa fila, así que **Tienda y
  Marketing lo ven distinto a antes** del milestone.

Y el mismo término bajo **dos categorías** sigue siendo dos productos: la categoría
viene de la petición y no de la fuente, y unirlas reescribiría la primera en
silencio.

## Probarlo

```bash
cd backend && alembic upgrade head
```

```bash
curl -X POST localhost:8000/api/research/runs \
  -H 'Content-Type: application/json' \
  -d '{"category":"home","keywords":["air fryer"],"max_results":3}'
```

```bash
curl -s localhost:8000/api/products | python -m json.tool
```

## Verificación

- Backend: `ruff` y `mypy` limpios · **1256 tests** (1190 antes, +66).
- Frontend: `tsc` y `eslint` limpios · **293 tests** (288 antes, +5).
- `next build --webpack` en una copia, sin tocar el `.next` de desarrollo.
- Migración ejecutada **arriba y abajo con datos dentro**: tres filas de
  `products` reciben su clave (`Air fryer` y `  AIR   FRYER ` la misma,
  `Belt (clothing)` la de `belt`), el `downgrade` deja la tabla como estaba y la
  fila sigue ahí — la migración no es destructiva en ningún sentido. Un test
  compara la copia congelada de `fold()` de la migración contra la de la
  aplicación, para que el día que divergan se sepa.
- **Humo contra Wikimedia de verdad**, sobre una base de datos temporal y sin
  tocar `backend/.env`:
  - keyword `air fryer` → se pregunta **una vez**, por `Air fryer`: demanda
    **0,7483**, confianza 0,6939, 12 observaciones. El gemelo de 0,1297 no existe.
  - segunda investigación con keyword `AIRFRYER` → **los mismos 3 productos**, 3
    filas en `products`, y cada ejecución con su propio análisis.
  - 144 observaciones mensuales acumuladas sobre 12 señales, ahora sobre los mismos
    productos.
  - dos fusiones registradas: `air fryer` por `normalised` y `AIRFRYER` por
    `alias:v1`, las dos hacia `air fryer`.
- **El informe de comparación del Milestone 35**: misma conclusión —cero candidatos
  en común, el mock puntúa 3/3 con confianza 0,30, lo real 0 de los suyos— y los
  mismos términos preguntados. Los recuentos exactos **no** coinciden: hoy la fuente
  contestó a los cinco términos (5 candidatos, confianza 0,7063, 10 señales) y el
  día del Milestone 35 contestó a cuatro (4, 0,71, 8). No se le atribuye causa:
  cualquiera sería una conjetura. Es la advertencia que la ADR 0013 ya dejó escrita
  —el informe es una foto— comprobada en la práctica.
- Dos tests que codificaban el supuesto anterior se reescribieron para decir la
  verdad nueva, no para pasar:
  `test_two_runs_for_the_same_category_land_on_the_same_product_and_slug` (el slug
  sigue al producto, como `generate_store_slug` promete desde siempre) y el flujo
  del CFO, que necesitaba tres productos distintos y ahora los pide a tres
  categorías en vez de a tres ejecuciones.

## No verificado

- **Migraciones contra PostgreSQL real**: como siempre, las aplica CI. Aquí se
  probó aislada con el contexto de Alembic sobre SQLite (la cadena entera no se
  puede aplicar en local: la migración de RLS del Milestone 3 emite `DO $$`).
- **La pantalla no se ha visto con fusiones dentro en un navegador**: los datos que
  la alimentan están cubiertos por tests de `lib` y del endpoint, pero el render con
  un `also_known_as` no vacío no se ha mirado a ojo.
- **Los cinco pendientes de integración** siguen igual
  ([system-overview §18](../architecture/system-overview.md#18-pendientes-de-integración)).
- **La incidencia del test intermitente del Milestone 35 no ha vuelto a aparecer**
  en las pasadas completas de este milestone. Sigue sin explicación y sigue anotada.

## Lo que queda abierto

1. **Segunda fuente real** de competencia o demanda comercial: sin ella un
   candidato real sigue sin score. Decisión de gasto del propietario, con
   `docs/design/fuentes-comerciales-product-intelligence.md` encima de la mesa.
   Este milestone era su prerrequisito y ya está pagado.
2. **Qué significa `real` con dos fuentes reales** (ADR 0014 §7).
3. **Los idiomas**: un nombre por mercado, o *langlinks* de Wikimedia.
4. **El mismo producto en dos categorías** sigue siendo dos filas.
5. **El catálogo de alias no escala**: once entradas a mano se quedan cortas el día
   que un discovery real proponga cientos de términos.
6. **Discovery real**: el catálogo de términos sigue siendo un arranque.
7. **`WAITING_APPROVAL` no caduca** y **los otros cuatro dominios** siguen con mock.
