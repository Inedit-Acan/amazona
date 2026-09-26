# Milestone 32 — Async Pipeline

**Fecha:** 26-09-2026 · **ADR:** [0010](../architecture/adr-0010-async-resumable-pipeline.md)
· **Anterior:** [Milestone 31](milestone-31-demo.md)

Segunda fase P1 del plan maestro (§6, §21 y §32). El `PipelineOrchestrator` deja
de correr dentro de la petición HTTP y pasa al runtime de trabajos del Milestone
31, con **cada paso persistido** y con tres controles que antes no existían:
reintentar, reanudar y cancelar.

---

## Qué cambia

### La ejecución deja de ser un resultado y pasa a ser un proceso

Antes: `POST /api/pipeline/runs` ejecutaba nueve pasos y devolvía el resultado.
Si el quinto fallaba, los cuatro anteriores ya estaban escritos en la base de
datos y **nadie podía encontrarlos**: la fila de la ejecución se escribía al
final, y sin final no había fila.

Ahora: esa llamada crea la ejecución en `QUEUED`, sus nueve pasos en `PENDING` y
un trabajo `pipeline.run`, y responde **202** en milisegundos. Un worker lo
reclama y recorre los pasos, escribiendo cada uno al empezar y al terminar.

### Los pasos son filas

Dos tablas nuevas:

- **`pipeline_steps`** — un paso por fila: estado de ejecución, su
  `correlation_id` propio, la fila que produjo, lo que expone del negocio, el
  intento en el que va y su error.
- **`pipeline_step_attempts`** — cada pasada por un paso, con el trabajo que lo
  intentó y qué error dio. Es el `PipelineAttempt` del plan maestro §21: sin
  esto, reanudar borraría la historia del intento anterior, que es justo lo que
  explica por qué hubo que reanudar.

Y una columna que **desaparece**: `pipeline_runs.steps` (el JSON). Las filas son
la única verdad; la API sigue devolviendo el mismo `steps` de siempre,
reconstruido desde ellas. `pipeline_runs` gana `job_id` y `request` (los
parámetros de negocio, sin los cuales no se puede continuar lo que alguien
empezó).

### Cuatro maneras de pararse, y no significan lo mismo

| Estado | Qué pasó | Quién lo mueve |
|---|---|---|
| `PARTIAL` | Un paso no pudo entregar nada al siguiente (research sin candidatos) | Nadie: es un resultado de negocio. Va a la bandeja de revisión (ADR 0006) |
| `FAILED` | Un paso reventó | El runtime lo reintenta con espera; si agota intentos, una persona |
| `BLOCKED` | El kill switch estaba apagado cuando le tocó | Una persona: reactivar y reanudar |
| `CANCELLED` | Alguien la paró | Una persona: reanudar |

La distinción `PARTIAL`/`FAILED` es nueva y es la que evita dos errores
simétricos: reintentar tres veces una categoría que no tiene productos, y dar
por resultado de negocio lo que fue un proveedor caído.

### Reanudar conserva el trabajo válido

`POST /api/pipeline/runs/{correlation_id}/resume` continúa por el primer paso que
no esté `COMPLETED`. Los anteriores no se repiten: mismas filas, mismos
`correlation_id`, mismo producto elegido. Con `{"from_step": "economics"}` se
fuerza rehacer ese paso y los siguientes —el «retry step» del plan maestro—, y
eso sí vale también sobre una ejecución que terminó bien.

Reanudar **reencola el mismo trabajo**, así que la historia completa de la
ejecución (sus intentos, su bitácora) sigue en una sola fila de `jobs`.

`POST /api/pipeline/runs/{correlation_id}/cancel` para una ejecución. Si un
worker la tiene entre manos se entera en su siguiente latido —entre dos pasos—,
deja el paso en curso en `CANCELLED` y no toca los que no habían empezado.

Ambas rutas usan la acción `pipeline.run` que ya existía: quien puede poner al
sistema a trabajar puede continuar y parar lo que ya empezó. No hay ningún rol
nuevo ni ninguna acción RBAC nueva.

### El kill switch apagado bloquea, no falla

Se sigue consultando al encolar (423 en el acto, ADR 0006 §3) y ahora también al
ejecutar, porque entre lo uno y lo otro puede pasar tiempo. Si está apagado
cuando le toca el turno, el trabajo queda en **`BLOCKED`**: el runtime no lo
reclama, no gasta intentos, y vuelve cuando el switch se reactiva y alguien lo
reencola.

Eso es un uso de `JobStatus.BLOCKED`, que el Milestone 31 dejó reservado para el
33. Está hecho a propósito y consultado: la ADR 0009 ya nombraba el kill switch
como motivo de ese estado, y el 33 lo usará para los suyos (veto legal,
presupuesto agotado). El runtime gana una transición —`JobQueue.block()`— y una
excepción que cualquier manejador puede lanzar, `JobBlockedError`.

### El panel Estado

Tarjeta «Pipeline» junto a la del runtime de trabajos: contadores, las
ejecuciones recientes con su progreso (`4/9 pasos`), el paso en el que van o por
el que se pararon, su error y si están en la bandeja de revisión.

Es la segunda tarjeta de esa pantalla **sin datos de demostración**: o el backend
responde las ejecuciones, o no se enseña nada. Una ejecución inventada diría que
el sistema está descubriendo productos cuando no lo está.

El veredicto de una línea ordena por lo que de verdad importa: una ejecución
bloqueada pesa más que una fallida —esa el runtime la reintenta sola— y que una
en cola.

## Las desviaciones respecto al plan maestro

1. **`WAITING_APPROVAL` y `BLOCKED` estaban reservados al Milestone 33.** Se usa
   `BLOCKED`, por el motivo de arriba. `WAITING_APPROVAL` sigue sin usarse.
2. **El §21 pide «retry step» y «resume run» como capacidades distintas.** Son
   una sola ruta con un parámetro, porque el punto por el que se reanuda **es**
   el paso que falló. Dos rutas para eso habrían sido dos nombres para lo mismo.
3. **Rotura de contrato**: `POST /api/pipeline/runs` devolvía 201 con la
   ejecución terminada y ahora devuelve 202 con una en `QUEUED`. No había ningún
   consumidor (el Control Center nunca llamó a esa ruta), pero es una rotura.

## Probarlo

```bash
cd backend && alembic upgrade head

# En una terminal
python -m app.jobs.worker

# En otra: encolar y mirar
curl -X POST localhost:8000/api/pipeline/runs -H 'Content-Type: application/json' \
  -d '{"category":"electronics","sale_price":45.0,"destination_region":"mexico"}'
curl -s localhost:8000/api/pipeline/runs/<correlation_id> | python -m json.tool

# El ciclo completo de bloqueo y reanudación
curl -X POST localhost:8000/api/pipeline/kill-switch -H 'Content-Type: application/json' \
  -d '{"enabled":false,"reason":"simulacro","actor":"owner@amazona.local"}'
# ... encola una ejecución: su trabajo queda en BLOCKED
curl -X POST localhost:8000/api/pipeline/kill-switch -H 'Content-Type: application/json' \
  -d '{"enabled":true,"actor":"owner@amazona.local"}'
curl -X POST localhost:8000/api/pipeline/runs/<correlation_id>/resume -d '{}' \
  -H 'Content-Type: application/json'
```

(En `development` no hace falta token; en `staging`/`production`, sí.)

## Verificación

- Backend: `ruff` y `mypy` limpios · **991 tests** (927 antes, +64).
- Frontend: `tsc` y `eslint` limpios · **262 tests** (249 antes, +13).
- `next build --webpack` en una copia del proyecto, sin tocar el `.next` de
  desarrollo. Las 20 rutas compilan.
- **Humo de extremo a extremo con el backend y el worker de verdad** (uvicorn +
  `python -m app.jobs.worker`, base SQLite temporal): encolado → 202 en `QUEUED`
  → el worker lo lleva a `COMPLETED` con los nueve pasos y sus nueve intentos ·
  categoría sin candidatos → `PARTIAL` con el resto `SKIPPED` y una revisión
  pendiente · kill switch apagado → trabajo en `BLOCKED` que el worker no vuelve
  a reclamar, y 423 para lo que se intente encolar mientras tanto · reactivar +
  reanudar → `COMPLETED`, con la bitácora del trabajo enseñando
  `blocked → requeued → claimed → completed` · cancelar → `CANCELLED` sin tocar
  ningún paso · auditoría con `pipeline.enqueue` y `pipeline.cancel`.
- **La migración se ejecuta de verdad en los tests, arriba y abajo, y con datos
  dentro**: un `steps` JSON de una ejecución completa y otro de una `PARTIAL` se
  convierten en filas y el `downgrade` reconstruye exactamente el mismo JSON. Es
  la prueba que una migración destructiva necesita para no ser una apuesta.
- El panel se comprobó en el navegador con un backend falso: el caso poblado
  (una ejecución de cada estado) y el caso sin respuesta, a 1280 px, sin errores
  de consola y sin desbordamiento horizontal.
- Los tests de inventario del Milestone 29 hicieron su trabajo: las dos rutas
  nuevas fallaron hasta darles su acción.

## No verificado

- **`alembic upgrade head` completo**: la cadena no se puede aplicar sobre SQLite
  porque la migración de RLS del Milestone 3 emite `DO $$` de PostgreSQL sin
  guardia de dialecto (es anterior a este milestone). La migración del 32 sí se
  ejecuta de verdad, aislada y con datos, en `tests/unit/test_migration_async_pipeline.py`,
  y la cadena entera la cubre CI sobre PostgreSQL limpio.
- La conversión del JSON a filas **sobre datos reales de Supabase**: no se toca
  esa base desde aquí. Sobre SQLite es ida y vuelta sin pérdida.
- Varios workers a la vez sobre la misma ejecución: `SKIP LOCKED` solo actúa en
  PostgreSQL (herencia del Milestone 31).
- Un paso que tarde más que el arriendo de 60 s. Hoy los nueve son simulados y
  tardan milisegundos.

## Lo que queda abierto

1. **Milestone 33**: `ActionGate`, que pondrá trabajos en `WAITING_APPROVAL` y
   usará `BLOCKED` para sus propias condiciones.
2. **Arriendo por tipo de trabajo.** El latido solo ocurre entre pasos; cuando un
   paso sea una llamada externa lenta, 60 s no bastarán.
3. **Ejecuciones anteriores al Milestone 32**: no guardaron sus parámetros de
   negocio, así que no se pueden reanudar. La API lo dice nombrando lo que falta.
4. **Una ejecución que agota sus intentos no genera revisión** (ADR 0010,
   consecuencias): se ve en el panel como trabajo agotado y se reanuda.
5. **Sin paralelismo entre pasos**, que tampoco lo permitiría la cadena: cada
   paso necesita el id del anterior.
