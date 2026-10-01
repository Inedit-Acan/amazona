# ADR 0024: El ciclo de vida de una acción externa — y un resultado desconocido nunca se resuelve a ciegas

- **Estado:** Aceptada
- **Fecha:** 2026-10-01
- **Depende de:** [ADR 0011](adr-0011-action-gate.md), [ADR 0022](adr-0022-idempotent-pipeline-run-creation.md), [ADR 0023](adr-0023-single-budget-source-and-absence-is-not-permission.md)
- **Milestone:** hardening pre-M44, fase 2 (reservas huérfanas, clave de idempotencia hacia el proveedor, `UNKNOWN_OUTCOME`)

## Contexto

Hasta ahora todos los adaptadores de proveedor eran de **solo lectura**, así que el sistema nunca tuvo
que responder a la pregunta que importa en cuanto uno escriba (publicar, activar publicidad, gastar):

> El proceso murió, o la petición se agotó, **¿llegó a salir?**

Con el código anterior las respuestas eran, según el caso, incorrectas en las dos direcciones:

- una reserva del libro (ADR 0023) que nadie compromete ni libera se quedaba **para siempre**, y reintentar
  el paso la reutilizaba sin saber si el efecto ya había ocurrido;
- un fallo al registrar localmente un efecto que sí ocurrió llevaba a **repetirlo** en el reintento;
- ante un timeout, lo único honesto es «no sé»; el sistema solo conocía «ok» y «excepción», y una excepción
  liberaba o mantenía la reserva sin distinguir si el proveedor pudo ejecutar.

Liberar una reserva cuyo efecto sí ocurrió permite gastar **dos veces el mismo presupuesto**. Mantenerla
cuando no ocurrió solo cuesta dinero inmovilizado, hasta que alguien lo mire. Las dos cosas no son
simétricas: ante la duda, se mantiene.

## Decisión

### 1. Una fila por operación con efecto: `external_actions`

Cada operación con efecto fuera del sistema es una fila con su propio estado, identificada por
`(reference, sequence)`: `reference` es el «sitio» (`pipeline_step:{correlation_id}:{paso}`) y `sequence`
cuenta las operaciones que ha habido ahí.

    PENDING ──reserve──▶ begin_call (COMMIT) ──▶ CALLING ──adaptador──▶ SUCCEEDED
                                                                  ├────▶ FAILED_CONFIRMED
                                                                  └────▶ UNKNOWN_OUTCOME
    UNKNOWN_OUTCOME ──lookup / misma clave / persona──▶ SUCCEEDED | FAILED_CONFIRMED

| Estado | Significa | Reserva del libro |
|---|---|---|
| `PENDING` | abierta y reservada; la petición **no ha salido** | viva |
| `CALLING` | se confirmó en la base que va a salir o ha salido | viva |
| `SUCCEEDED` | el proveedor lo confirmó (o una persona lo comprobó) | comprometida |
| `FAILED_CONFIRMED` | se **sabe** que no hubo efecto: rechazo, petición que no salió, consulta negativa | liberada |
| `UNKNOWN_OUTCOME` | pudo ejecutarse y no se sabe | **se queda** |

### 2. Una sola frontera de durabilidad: `begin_call`

`PENDING → CALLING` es un compare-and-set seguido de **commit**, justo antes de que la petición salga.
Es lo único que la base puede saber con certeza:

- si el proceso muere **antes** de ese commit, no salió nada: la operación sigue `PENDING` y el barrido
  puede liberar la reserva con seguridad;
- si muere **después**, no se sabe: `CALLING` pasa a `UNKNOWN_OUTCOME`, y **no se libera nada**.

`begin_call` vuelve a mirar el kill switch: es el último punto antes del efecto irreversible.

### 3. Los seis casos

| Caso | Qué pasó | Resultado |
|---|---|---|
| A | cae antes de confirmar la reserva | no queda nada |
| B | reservado y confirmado, la petición no salió | el barrido libera y cierra `FAILED_CONFIRMED` |
| C | cae a mitad de la llamada | `CALLING` → `UNKNOWN_OUTCOME`, la reserva se queda |
| D | el proveedor ejecutó y la respuesta se perdió | `UNKNOWN_OUTCOME`, la reserva se queda |
| E | no ejecutó y se agota el tiempo | **indistinguible de D desde fuera**: `UNKNOWN_OUTCOME` |
| F | el proveedor rechaza o no es alcanzable | `FAILED_CONFIRMED`, se libera |

Un timeout **nunca** es un fallo confirmado. Solo `ProviderRejectedError` y `ProviderUnreachableError`
(la petición no llegó a salir) cierran como fallo seguro.

### 4. La clave hacia el proveedor es estable por operación

`derive_idempotency_key(reference, sequence)` es determinista: depende del sitio y de qué operación es, **no**
del intento. Reintentar tras una caída reutiliza la misma operación y la misma clave; **rehacer un paso a
propósito** (o reintentarlo tras un fallo confirmado) abre una operación nueva con clave nueva.

Cada adaptador declara `supports_idempotency`. La clave solo se envía a quien la declara; un proveedor sin
idempotencia **no** recibe un reintento ciego jamás (ver §6).

### 5. «Hecho en el proveedor» no es «hecho aquí»: `applied_at`

El paso registra localmente el resultado después de la llamada. Si el proceso cae entre las dos cosas, el
efecto existe y el registro no. `SUCCEEDED` sin `applied_at` significa exactamente eso: el reintento
**reutiliza** la operación, no pide autorización de nuevo y **no repite el efecto**; solo registra. Una operación
solo libera el sitio cuando está cerrada del todo (`applied_at`) o ha fallado confirmada.

### 6. Salir de `UNKNOWN_OUTCOME`: solo con información, nunca con una suposición

`reconcile` intenta saber qué pasó, en este orden:

1. si el adaptador sabe consultar (`lookup`), se le pregunta por la clave: existe → `SUCCEEDED`; no existe →
   `FAILED_CONFIRMED`;
2. si no, pero declara idempotencia, se repite **la misma petición con la misma clave**: el proveedor se
   compromete a no repetir el efecto, así que una respuesta es la de la operación original → `SUCCEEDED`;
3. en cualquier otro caso —sin idempotencia ni consulta, o si la repetición se rechaza, no es alcanzable o se
   agota— **sigue desconocido**. Un rechazo al repetir la clave no prueba que el original no se ejecutara.

Y siempre queda la persona: `resolve` (CLI) compromete o libera la reserva tras una comprobación manual, exige
**un motivo** y deja quién, cuándo y por qué en la fila y en la auditoría. Es de un solo uso (compare-and-set).

### 7. Un efecto sin resolver veta el siguiente

El `ActionGate` recibe `unresolved_outcome` y lo trata como un **veto**, de los que ganan a cualquier aprobación
humana: ni una firma permite volver a ejecutar un efecto que quizá ya ocurrió. El paso queda `DENIED` con el
motivo, y si el resultado se descubre durante la ejecución, el paso queda `FAILED` (`UNKNOWN_OUTCOME: …`), la
ejecución `BLOCKED` y el trabajo `BLOCKED` **sin gastar intentos**. No hay estado nuevo de paso.

### 8. Lo que respalda la base de datos

- `idempotency_key` única;
- `(reference, sequence)` única;
- **a lo sumo una operación abierta por `reference`**: índice único parcial
  `uq_external_actions_one_open_per_reference` (`status IN ('PENDING','CALLING','UNKNOWN_OUTCOME')`);
- `open` se serializa por `reference` con un lock de transacción en PostgreSQL;
- todo cambio de estado es `UPDATE … WHERE status IN (…)` con comprobación de `rowcount`;
- el libro solo se mueve **por lo que esa operación tiene reservado** (`outstanding`): sin reserva viva propia
  no hay nada que liberar, y liberar a ciegas restaría de la reserva de otra operación.

RLS desde su propia migración (ADR 0003), sin `FORCE`.

### 9. Operación

    python -m app.cli show-actions [--open]
    AMAZONA_BOOTSTRAP=1 python -m app.cli reconcile-actions [--older-than-minutes 60]
    AMAZONA_BOOTSTRAP=1 python -m app.cli resolve-action --id ID (--succeeded | --failed) --reason "…"

`reconcile-actions` es el barrido de huérfanas; su umbral tiene que **superar el arriendo de un trabajo**: es la
prueba de que su ejecutor ya no está. Tras `resolve-action`, la ejecución se reanuda con `resume`: si el efecto
ocurrió, el paso solo lo registra; si no, abre una operación nueva.

## Consecuencias

- Ningún camino libera una reserva sin saber que no hubo efecto, ni repite un efecto sin la misma clave.
- Hay un coste deliberado: tras un timeout el dinero queda **inmovilizado** hasta reconciliar o resolver. Es el
  lado seguro de la asimetría.
- El pipeline ejecuta hoy `SimulatedAdapter` (idempotente, sin efecto real). Conectar un proveedor real es
  implementar `ExternalActionAdapter` con su `supports_idempotency` honesto; el ciclo de vida no cambia.
- El barrido **no está programado**: es una orden del operador. Programarlo (y fijar su cadencia respecto del
  arriendo) es una decisión de despliegue pendiente.
- Las rutas HTTP síncronas con efecto (que no pasan por el pipeline) quedan para la idempotencia genérica de la
  fase 2 (B).

## Alternativas descartadas

- **Liberar tras un timeout** («el proveedor no respondió, no habrá hecho nada»): es exactamente el caso D.
- **Reintentar siempre con la misma clave** sin declarar capacidad: un proveedor que ignora la clave ejecuta dos
  veces; por eso la capacidad es explícita y su ausencia nunca se reintenta.
- **Un estado nuevo de paso (`UNKNOWN`)**: el paso solo necesita saber que falló; quien sabe qué pasó con el efecto
  es la acción, y el veto del gate lo impide sin tocar la máquina de estados del pipeline.
- **TTL que libera reservas viejas**: confunde «hace mucho» con «no ocurrió».
