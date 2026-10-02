# ADR 0024: El ciclo de vida de una acción externa — y un resultado desconocido nunca se resuelve a ciegas

- **Estado:** Aceptada
- **Fecha:** 2026-10-01
- **Depende de:** [ADR 0011](adr-0011-action-gate.md), [ADR 0022](adr-0022-idempotent-pipeline-run-creation.md), [ADR 0023](adr-0023-single-budget-source-and-absence-is-not-permission.md)
- **Milestone:** hardening pre-M44, fase 2 (reservas huérfanas, clave de idempotencia hacia el proveedor, `UNKNOWN_OUTCOME`)
- **Enmendada por:** [ADR 0028](adr-0028-orders-payments-fulfilment-core.md) (Milestone 44: observadores de transición y tres espacios de referencias; ver «Enmienda (Milestone 44)» al final)

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

**La respuesta tardía de la llamada original también cierra.** Otro ejecutor puede ver una llamada en vuelo (`CALLING`),
no saber si su dueño sigue vivo y marcarla `UNKNOWN_OUTCOME`; si la llamada original responde **después**, esa respuesta es
autoritativa y cierra la operación (`SUCCEEDED` compromete, `FAILED_CONFIRMED` libera) dejando `late_response` en la
auditoría. Descartarla perdería lo único que de verdad se sabe. Lo que **nunca** cierra un `UNKNOWN_OUTCOME` es una
suposición: ni el barrido, ni un reintento, ni volver a mirar, ni el paso del tiempo.

### 7. Un efecto sin resolver veta el siguiente

El `ActionGate` recibe `unresolved_outcome` y lo trata como un **veto**, de los que ganan a cualquier aprobación
humana: ni una firma permite volver a ejecutar un efecto que quizá ya ocurrió. El paso queda `DENIED` con el
motivo; si el resultado se descubre durante la ejecución, el paso queda `FAILED` (`UNKNOWN_OUTCOME: …`). En los dos casos la
ejecución queda `BLOCKED` —**nunca** `COMPLETED` con dinero en el aire— y el trabajo `BLOCKED` **sin gastar intentos**,
también al reanudarla sin haber resuelto nada. No hay estado nuevo de paso.

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

## Contrato de un adaptador con efecto (lo que M44 tendrá que cumplir)

Un adaptador que **escribe** en un proveedor implementa `ExternalActionAdapter` y pasa la batería de conformidad
(`tests/integration/adapter_contract_test_support.py`) con su transporte falso **antes** de que el pipeline lo use:

1. **Declara** su `name` y `supports_idempotency`; las capacidades no se infieren.
2. Si declara `True`, repetir `execute` con la misma clave **no repite el efecto** y devuelve la misma respuesta; otra clave es
   otra operación. Un adaptador que dice `True` y repite el efecto es peor que uno que dice `False`: la batería lo detecta.
3. Si declara `False`, el servicio **no le manda clave** y nunca le repite una petición: su `UNKNOWN_OUTCOME` solo se cierra por
   `lookup` o por una persona.
4. Si sabe consultar, implementa `LookupCapableAdapter.lookup(clave)`: devuelve la respuesta de lo que ejecutó y `None`
   **solo** de lo que el proveedor asegura que no existe. No poder alcanzar al proveedor es un `ProviderError`, nunca un `None`.
5. Lanza `ProviderRejectedError` o `ProviderUnreachableError` **solo** cuando sabe que no hubo efecto; un timeout es
   `ProviderTimeoutError`. Todo lo demás se trata como desconocido, así que equivocarse hacia «no sé» es siempre seguro.
6. No lee configuración ni credenciales por su cuenta, y no decide si puede ejecutarse: eso es del `ActionGate`.

Los adaptadores de los tests son falsos y cuentan los efectos que habrían tenido en el mundo real
(`tests/integration/action_test_support.py`); ninguna prueba habla con un proveedor de verdad.

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

## Enmienda (Milestone 44): el dominio se refleja en la misma transacción

Una acción dice **qué se hizo hacia fuera**; un cobro, un reembolso o un envío dicen **qué significa eso para el
negocio**. Si el dominio se actualiza después, en otra transacción, queda una ventana en la que la acción dice
«posiblemente enviada» y el dominio sigue diciendo «nada enviado»: la ambigüedad que este ADR quitó de la acción
volvería a entrar por el dominio, y `reconcile-actions` o `resolve-action` (que no saben nada de pedidos) la
dejarían sin cerrar.

`ExternalActionService` admite ahora **observadores por prefijo de referencia** (`app/actions/observers.py`). Se
llaman **dentro de la transacción de cada transición**, antes del `commit`, en todos los caminos que mueven una
acción: `begin_call`, `finish` (incluida la respuesta tardía), `mark_interrupted`, el barrido de huérfanas,
`finish_unstarted`, `reconcile` (con la respuesta de la consulta) y `resolve`. Si un observador falla, la excepción
sube antes del commit y la transición no se confirma: una acción nunca queda movida con su dominio sin mover.
El pipeline no registra ninguno y su comportamiento no cambia.

### Qué añadió el cierre del Milestone 44

Tres observadores, y solo tres, están registrados (`app/actions/observers.py`; una guarda de arquitectura lo comprueba):
cada uno es dueño de un prefijo de referencia y de la parte del dominio que la acción mueve.

| Prefijo de la referencia | Observador | Operación |
|---|---|---|
| `order_payment:{payment_id}` | `PaymentOpenObserver` | `payment.open` |
| `order_refund:{refund_id}` | `RefundActionObserver` | `payment.refund` |
| `order_fulfilment:{fulfillment_id}:purchase` y `…:ship` | `FulfilmentActionObserver` | `fulfillment.purchase`, `fulfillment.ship` |

Cada «sitio» es una referencia propia, así que una compra y un envío del mismo fulfillment son acciones distintas, cada una
con su clave estable hacia el proveedor `(referencia, sequence)`. Lo que el cierre del milestone precisó, con el detalle en
la [ADR 0028](adr-0028-orders-payments-fulfilment-core.md) (E1 a E3):

- Un observador que falla **aborta** la transición: nada sale y la acción no queda movida con su dominio sin mover.
- **Perder una carrera por una acción es un 409**, nunca un error interno. Esa traducción vive hoy solo en el servicio de
  fulfillment; los de cobros y reembolsos no atrapan `ExternalActionStateError` (**P2-1**, abierto: inalcanzable con el
  umbral del barrido por encima del arriendo que este ADR exige, un 500 si se configura por debajo).
- La reconciliación y `resolve-action` no toman el bloqueo del pedido, y por eso un evento verificado puede coincidir con
  ellos: el evento se conserva como evidencia (E3).
- Sigue sin existir un reconciliador programado: `reconcile-actions`, `reconcile-payment-events` y `resolve-action` son
  comandos manuales de la consola (**P1-1**, a resolver en M45 antes de conectar nada real).
