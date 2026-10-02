# ADR 0025: Idempotencia genérica para las rutas síncronas con efecto

- **Estado:** Aceptada
- **Fecha:** 2026-10-01
- **Depende de:** [ADR 0022](adr-0022-idempotent-pipeline-run-creation.md), [ADR 0023](adr-0023-single-budget-source-and-absence-is-not-permission.md), [ADR 0024](adr-0024-external-actions-lifecycle-and-unknown-outcome.md)
- **Milestone:** hardening pre-M44, fase 2 (idempotencia de las rutas síncronas)
- **Enmendada por:** [ADR 0028](adr-0028-orders-payments-fulfilment-core.md) (Milestone 44: clave siempre obligatoria en las rutas de pedidos, el `code` de sus errores, las claves por intención del frontend y las rutas de M44 en la clasificación; ver «Enmienda (Milestone 44)» al final)

## Contexto

La [ADR 0022](adr-0022-idempotent-pipeline-run-creation.md) resolvió `POST /api/pipeline/runs`, y lo hizo apoyándose en una
propiedad que **solo esa ruta tiene**: encola un trabajo, y el trabajo tiene una clave única. Las demás rutas con efecto
responden en la misma petición, no crean un recurso con clave y, ante un timeout o un doble clic, **se ejecutan dos veces**:

- `POST /api/objectives/{id}/run` decide un objetivo: **reserva presupuesto** y abre aprobaciones. Hecho dos veces, reserva
  dos veces (medido: dos `RESERVE` en el libro).
- Las consultas a una fuente externa —tipos de cambio (BCE), verificación regulatoria (EUR-Lex, BOE)— **gastan cuota** y se
  anotan en el contador de coste; un reintento las repite.
- Los análisis (`research`, `legal`) escriben filas nuevas cada vez.

Y no basta con «una consulta previa por si ya existe»: dos peticiones a la vez la hacen las dos antes de que ninguna escriba.

## Decisión

### 1. Una pieza común, con la garantía en la base de datos

`idempotency_records`, con un índice único `(scope, actor_hash, key)`:

- `scope`: la operación (`objectives.run`, `research.run`, `research.comparison`, `legal.run`, `fx.refresh`, `fx.backfill`,
  `regulatory.verify`, `national.verify`). **Los ámbitos no chocan**: la misma clave en dos operaciones son dos peticiones.
- `actor_hash`: una huella de quien pide. La clave de una persona no choca con la de otra.
- `key`: la clave del cliente (`Idempotency-Key`, 1–128 caracteres `[A-Za-z0-9._:-]`).
- `request_hash`: la huella del contenido (JSON canónico, sin importar el orden de los campos; incluye los parámetros de
  ruta, así que la misma clave sobre otro recurso es otra petición).

`run_idempotent(...)` hace, en este orden: **reclamar** (INSERT + COMMIT, antes de ejecutar nada) → ejecutar → **completar**
con el estado y el cuerpo que se devolvieron.

| La petición… | Resultado |
|---|---|
| es la primera con esa clave | se ejecuta una vez y se guarda su respuesta |
| repite clave **y** contenido de una completada | se devuelve la respuesta original (`Idempotency-Replayed: true`) sin ejecutar |
| repite la clave con **otro** contenido | 409: es otra petición escondida tras la misma clave |
| repite la clave de una que **sigue en curso**, o cuyo proceso cayó a medias | 409: no se vuelve a ejecutar |
| repite la clave de una que falló **sin decir si hubo efecto** (`UNKNOWN_OUTCOME`) | 409: hay que mirar qué pasó y usar otra clave |
| llega **a la vez** que otra igual | la base de datos deja insertar a una; las demás reciben la respuesta o un 409 |

### 2. Qué libera una clave y qué la bloquea

- Una **negativa del dominio** (`AmazonaError`, `HTTPException`: no existe, no es válido, la fuente no está configurada, la
  cuota se agotó, la fuente no contestó y no se guardó nada) **no hizo nada**: la clave se libera y vuelve a servir.
- Cualquier **otra** excepción no dice si hubo efecto: la fila queda `UNKNOWN_OUTCOME` y la clave **no** vuelve a servir.
- Si el efecto ocurrió y no se pudo guardar su respuesta, ocurre lo mismo. Es el mismo principio que la
  [ADR 0024](adr-0024-external-actions-lifecycle-and-unknown-outcome.md): ante la duda, no se repite.

### 3. Sin caducidad

**No hay TTL.** Una clave sin terminar no vuelve a estar disponible con el tiempo: un TTL confundiría «hace mucho» con «no
ocurrió» y repetiría un efecto que quizá sí ocurrió. Las filas se conservan; borrar las completadas antiguas sería una acción
explícita del operador, nunca un efecto del reloj. Es un coste deliberado: un proceso que cae entre la reclamación y la
respuesta deja una clave inservible, y el cliente usa otra tras comprobar qué pasó.

### 4. Cuándo es obligatoria

Con la misma regla de la [ADR 0023](adr-0023-single-budget-source-and-absence-is-not-permission.md) y la
[ADR 0022](adr-0022-idempotent-pipeline-run-creation.md): `Settings.idempotency_key_required`, es decir, siempre que el
despliegue **pueda tocar algo fuera del sistema** (no es una simulación). Falta → **428**. En una simulación es opcional y,
sin clave, la ruta se ejecuta como siempre: no se inventa una.

El Control Center envía una clave nueva en cada `POST` (`lib/idempotency.ts`). Eso cubre la exigencia del backend y cualquier
reintento de la misma llamada; **no** cubre un segundo clic, que es otra llamada con otra clave. Un formulario a prueba de
doble clic tiene que conservar su clave hasta que la operación termine; no se ha hecho aquí.

### 5. Dos mecanismos, a propósito

`POST /api/pipeline/runs` conserva el suyo (la clave única del trabajo, ADR 0022): su recurso ya tiene una clave y encola, no
ejecuta. Comparten el formato de clave y la huella de quien pide (`app/idempotency/service.py`), no la tabla. Y
`ExternalAction` (ADR 0024) es otra cosa: la clave que se manda **al proveedor** y se deriva de la operación, no del cliente.

### 6. Clasificación de todas las rutas `POST`

Qué se hizo con cada una y por qué. **«Idempotencia genérica»** es esta ADR; **«por estado»** es que repetir la petición ya
no tiene efecto porque el estado cambió (un segundo `approve` es un 409).

| Clase | Rutas | Tratamiento |
|---|---|---|
| `EXTERNAL_READ` (sale a una fuente, gasta cuota) | `exchange-rates/refresh`, `exchange-rates/backfill`, `regulatory-requirements/{id}/verify`, `national-transpositions/{id}/verify`, `research/runs`, `research/comparisons` | idempotencia genérica |
| `SPEND` (reserva presupuesto) | `objectives/{id}/run` | idempotencia genérica; el gasto del pipeline va por `ExternalAction` (ADR 0024) |
| `LOCAL_WRITE` con análisis nuevo | `legal/runs` | idempotencia genérica (barata y evita filas duplicadas) |
| `EXTERNAL_WRITE` | ninguna hoy: todos los adaptadores son de lectura o simulados | `ExternalAction` desde el primer proveedor real (M44+) |
| `LOCAL_WRITE`, borrador sin efecto fuera | `cfo/runs`, `economics/runs`, `ecommerce/runs`, `marketplace/runs`, `marketing/runs`, `operations/runs`, `sourcing/runs`, altas manuales (`exchange-rates`, `suppliers` y sus `quotes` y `capabilities`, `regulatory-requirements` y sus `national-transpositions`, `compliance-evidence`, `incidents`, `objectives`) | **sin idempotencia genérica**: un duplicado es un registro más, no un efecto. Cuando alguno pase a tocar un proveedor real, se convierte en `EXTERNAL_WRITE` y deja de ser un borrador |
| `LOCAL_WRITE`, transición de estado | `approvals/*`, `pipeline/reviews/*`, `pipeline/runs/{id}/resume\|cancel`, `jobs/{id}/cancel\|requeue`, `incidents/{id}/resolve`, `*/withdraw`, `regulatory-requirements/{id}/supersede` | por estado (compare-and-set; repetir es 409) |
| `LOCAL_WRITE`, idempotente por valor | `pipeline/kill-switch` (poner el mismo valor dos veces deja el mismo estado) | — |
| `PURE` / `UNKNOWN` | ninguna: `tests/unit/test_post_route_classification.py` falla si aparece una `POST` sin clasificar | — |

`marketing/runs` merece una nota: genera un borrador de campaña con un `daily_budget`, **no** activa publicidad ni reserva
presupuesto. La activación (la acción que gasta) es el paso `marketing` del pipeline, que sí pasa por el gate y por
`ExternalAction`.

## Consecuencias

- Reintentar tras un timeout o un doble clic en una ruta con efecto **no lo repite**, y veinte peticiones iguales a la vez
  producen un solo efecto (comprobado en PostgreSQL con barrera).
- La tabla crece con cada petición con clave y no se purga sola. Es el lado seguro; el volumen es el de las acciones
  humanas, no el del tráfico.
- Una clave bloqueada (`UNKNOWN_OUTCOME` o en curso tras una caída) exige que una persona compruebe y use otra: no hay comando
  para listarlas todavía.
- Las rutas `LOCAL_WRITE` de creación siguen sin protección contra duplicados. Es una decisión, no un olvido: ver §6.

## Alternativas descartadas

- **Una consulta previa («¿ya existe?») y luego ejecutar**: dos peticiones a la vez pasan las dos la consulta.
- **TTL de las claves**: ver §3.
- **Guardar solo una referencia al recurso creado y reconstruir la respuesta**: no sirve para las rutas que no crean un recurso
  con identificador (refrescar tipos de cambio) y obliga a una función de reconstrucción por ruta.
- **Esperar a que termine la petición en curso en lugar de responder 409**: bloquea una conexión indefinidamente si el proceso
  de la primera cayó. El 409 es inmediato y honesto.
- **Aplicarla a todos los `POST`**: es indiscriminada. Un duplicado de una fila de borrador no es un efecto, y una clave
  bloqueada por un fallo imprevisto sí tiene coste.

## Enmienda (Milestone 44): lo que cambió con los pedidos

La [ADR 0028](adr-0028-orders-payments-fulfilment-core.md) aplica esta ADR a las rutas de pedidos, cobros, reembolsos y fulfillment, y precisa cuatro cosas.

1. **La clave es siempre obligatoria en esas rutas**, también en simulación. El §4 la hacía obligatoria solo si el
   despliegue puede tocar algo fuera del sistema; en M44 un pedido simulado se trata como uno real (`always_required`):
   sin `Idempotency-Key` la respuesta es 428.
2. **Los errores de idempotencia llevan un `code`** legible por máquina, para que un cliente no clasifique por el texto del
   mensaje:

   | Estado | `code` |
   |---|---|
   | 428 | `idempotency_key_required` |
   | 409 | `idempotency_conflict` (misma clave, otro contenido) |
   | 409 | `idempotency_in_progress` |
   | 409 | `idempotency_outcome_unknown` |

   Un 409 de **negocio** (otra petición ya hizo la operación, el estado no la permite) no lleva `code`: es una respuesta
   definitiva, no un problema de la clave.
3. **Lo que el §4 dejaba pendiente en el frontend está hecho** (`lib/intent-key.ts`, `lib/use-intent.ts`): una clave por
   **intención** (operación, objetivo y parámetros canónicos), conservada ante timeout, red, 5xx, un 409 «en curso» y un
   resultado desconocido, y nueva tras un éxito, con otros parámetros o con un `discard` humano. Sin caducidad por tiempo,
   igual que aquí (§3), y persistida solo en `sessionStorage`. Está cableada en legal, investigación, CEO y la comprobación de
   requisitos y de transposiciones; **todavía no hay formularios de M44** (las funciones de `api.ts` esperan la clave como
   parámetro obligatorio). Detalle en la [ADR 0028](adr-0028-orders-payments-fulfilment-core.md), E4.
4. **La clasificación del §6 cambia.** `EXTERNAL_WRITE` ya no está vacía: son `POST /api/orders/{id}/payments`,
   `POST /api/orders/{id}/refunds`, `POST /api/fulfillments/{id}/purchase` y `POST /api/fulfillments/{id}/ship`
   (idempotencia genérica **y** `ExternalAction`). `POST /api/orders`, `POST /api/orders/{id}/fulfillments` son idempotencia
   genérica; las decisiones de una persona (`cancel` de pedido y de fulfillment, `complete`, `fail`) son por estado; y el
   webhook de pagos es una clase propia (`WEBHOOK`), que se deduplica por `(proveedor, id del evento)` y se autentica por firma, no por clave.
   `tests/unit/test_post_route_classification.py` sigue fallando si aparece una `POST` sin clasificar.

Lo demás de esta ADR sigue como estaba. En particular, **no hay comando para listar las claves bloqueadas** ni retención de
`idempotency_records` (P3-6).
