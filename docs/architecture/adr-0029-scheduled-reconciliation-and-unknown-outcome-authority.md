# ADR 0029: Reconciliación programada — quién puede cerrar qué, y un resultado desconocido solo lo cierra información

- **Estado:** Aceptada (decisiones del propietario del 2026-10-03). **Implementada en el Commit 5 de M45**: el propietario fusionó en un solo commit lo que el plan repartía entre los commits 5, 6 y 7 (servicios, disparador y pruebas).
- **Fecha:** 2026-10-03
- **Depende de:** [ADR 0003](adr-0003-rls-deny-by-default.md), [ADR 0009](adr-0009-async-job-runtime.md), [ADR 0010](adr-0010-async-resumable-pipeline.md), [ADR 0011](adr-0011-action-gate.md), [ADR 0023](adr-0023-single-budget-source-and-absence-is-not-permission.md), [ADR 0024](adr-0024-external-actions-lifecycle-and-unknown-outcome.md), [ADR 0025](adr-0025-generic-idempotency-for-synchronous-routes.md), [ADR 0028](adr-0028-orders-payments-fulfilment-core.md)
- **Enmienda a:** [ADR 0009](adr-0009-async-job-runtime.md) (trabajos recurrentes dentro del mantenimiento del worker), [ADR 0024](adr-0024-external-actions-lifecycle-and-unknown-outcome.md) (el barrido deja de ser solo una orden del operador; `reconcile` solo con consulta autoritativa) y [ADR 0028](adr-0028-orders-payments-fulfilment-core.md) (campos de proceso de `PaymentEvent`)
- **Milestone:** 45 (cierra P1-1)

## Contexto

M44 construyó el núcleo de pedidos, cobros, reembolsos y fulfillment sobre una regla que no admite excepciones: **un
resultado desconocido no se repite a ciegas, no libera reservas, no se declara fallido y solo sale por información**
(ADR 0024 y 0028 §3). Lo que M44 no construyó es quién mira esos estados cuando nadie está mirando. Hoy los estados que
pueden bloquear un pedido solo avanzan si una persona ejecuta a mano `reconcile-actions`, `reconcile-payment-events` o
`resolve-action` (P1-1). Un cobro `OPENING` o `UNKNOWN_OUTCOME` bloquea los intentos nuevos de su pedido, un reembolso
`UNKNOWN_OUTCOME` bloquea los suyos y mantiene una reserva, y un evento `RECEIVED` es dinero verificado sin aplicar.

Lo que se comprobó en el código antes de decidir (ninguna de estas cuatro cosas estaba en el handoff de M44):

1. **No existe ningún disparador periódico.** El runtime de trabajos (ADR 0009) solo ejecuta lo que alguien encola. Ni siquiera
   `fx.refresh` se programa: se encola a mano o desde su ruta HTTP. Hay que construir el disparador, y el ADR 0009 ya dice
   dónde: «el mantenimiento va dentro del bucle del worker, así que no hay un proceso aparte que alguien pueda olvidar arrancar».
2. **Nada acota cuánto puede tardar una llamada externa.** `ExternalActionAdapter.execute` no declara una duración máxima y
   `ExternalActionService.execute` no la aplica. Solo los adaptadores de *lectura* tienen un timeout (`httpx`, 6–10 s). Una petición
   HTTP no tiene arriendo (el arriendo del ADR 0009 existe solo para los trabajos, 60 s por defecto). No hay adaptador real de
   escritura todavía, así que hoy no hay nada que medir; en cuanto lo haya, el umbral del barrido tendrá que compararse con algo.
3. **`ExternalActionService.reconcile()` no lo llama ningún código de producción**, solo pruebas, y el `lookup` de los proveedores
   simulados es **memoria de proceso** (`_shared_operations`, un `dict` de clase): un worker es otro proceso que la API y su
   `lookup(clave)` devolvería `None` para una operación que la API sí «ejecutó». `reconcile()` lo leería como «el proveedor no tiene esa
   operación», cerraría la acción como `FAILED_CONFIRMED` y **liberaría la reserva**: justo lo que el ADR 0024 prohíbe.
4. **La reconciliación de eventos vive dentro de `cli.py`** y **se detiene con el primer evento que falla**; un evento que lanza
   siempre bloquearía a los demás en cada pasada y se reintentaría para siempre. `PaymentEvent` no tiene dónde contar intentos.

## Decisión

### 1. Qué estados se miran, quién puede cerrarlos y qué hace el programador

Todos los estados de dominio que pueden bloquear algo **derivan de una `ExternalAction`** (los tres observadores del ADR 0024/0028
los mueven en la misma transacción): cobro `REQUESTED/OPENING/UNKNOWN_OUTCOME`, reembolso `REQUESTED/SENDING/UNKNOWN_OUTCOME` y fulfillment
`PURCHASING/SHIPPING/UNKNOWN_OUTCOME`. Por eso un reconciliador sobre `ExternalAction` más otro sobre `PaymentEvent.RECEIVED` cubre toda la lista.

| Estado | Quién lo puede cerrar | Qué hace el reconciliador programado |
|---|---|---|
| `ExternalAction.PENDING` (nada salió) más viejo que el umbral | el barrido (compare-and-set) | `finish_unstarted`: cierra `FAILED_CONFIRMED` y libera la reserva (los observadores devuelven el dominio a «nada enviado», `not_sent`) |
| `ExternalAction.CALLING` (pudo salir) más viejo que el umbral | el barrido, **solo hacia** `UNKNOWN_OUTCOME` | lo marca `UNKNOWN_OUTCOME`; **la reserva se queda** |
| `ExternalAction.UNKNOWN_OUTCOME` | la respuesta tardía de la llamada original, una consulta autoritativa (§7) o una persona (`resolve-action`) | **nada**: no lo cierra, no lo repite, no libera. Lo hace **visible** (edad, número, motivo) |
| `PaymentEvent.RECEIVED` más viejo que el umbral | `PaymentService.apply` (la única puerta que mueve dinero) | lo reanuda llamando a `apply`, con tope de intentos (§6) |
| `Payment.OPEN`, `Refund.SENDING` sin confirmar | un hecho verificado del proveedor | **nada**: no hay consulta de estado al proveedor (P2-3, P2-4; fuera de M45). `refund_unconfirmed` ya aparece en la atención |

### 2. Un disparador dentro del runtime existente

Se añade un paso de mantenimiento a `Worker.run_once` (junto a `release_due_retries` y `reap_expired_leases`): **encolar los trabajos
recurrentes que toquen**. No hay tabla de horarios, ni proceso aparte, ni n8n, ni Redis.

- Cada tipo recurrente tiene un intervalo. El disparador encola con `idempotency_key = "{tipo}:{cubo}"`, donde
  `cubo = floor(ahora / intervalo)`. Con N workers encolando a la vez la misma clave, la columna única `jobs.idempotency_key` deja
  **un solo trabajo** (el camino ya probado de `JobQueue.enqueue`, incluido el `SAVEPOINT` que evita perder la transacción del que pierde la carrera).
- Tipos nuevos, registrados como cualquier otro manejador: `reconcile.actions` (barrido de acciones huérfanas), `reconcile.payment_events`
  (reanudar eventos `RECEIVED`) y `reconcile.report` (solo lectura: cuenta y envejece lo desconocido y los eventos topados; nunca cierra nada).
- **Exclusión y recuperación.** El reclamo del trabajo es `SKIP LOCKED` con arriendo (ADR 0009 §1 y §4). Si el worker muere, el segador
  devuelve el trabajo a la cola. Sobre cada fila actúa un compare-and-set, así que dos reconciliadores que coincidan (dos workers, un trabajo
  reencolado, un humano con la consola) **no pueden ganar los dos**: el que pierde ve `rowcount = 0` y sigue con la siguiente fila.
  Un tick perdido no es un problema: el siguiente cubo encola otro.
- **Cada elemento va en su propia transacción.** Una fila que falla (un observador que lanza, un evento venenoso) se registra y **no
  aborta el lote**: hoy `reconcile_interrupted` confirma una sola vez al final para las filas `CALLING` y `reconcile_payment_events`
  se detiene con la primera excepción.
- **Retención.** Un tick por minuto y tipo son miles de filas al día; el mantenimiento purga los trabajos recurrentes `COMPLETED` de más de
  `reconcile_tick_retention_days` días (con sus intentos y eventos). Nada más se purga.
- **Interruptor.** `reconciliation_enabled` apaga el disparador sin tocar código (ver Rollback). Apagado, el sistema vuelve a ser el de M44:
  lo manual sigue funcionando.

### 3. Umbrales, cadencias y el techo de una llamada externa

Valores de reconciliación aprobados por el propietario como **configuración inicial**, **todos configurables** (`Settings`); ninguno es una constante arquitectónica:

| Ajuste | Valor inicial | Qué es |
|---|---|---|
| `reconcile_actions_interval_seconds` | 300 | cada cuánto se barren las acciones |
| `reconcile_actions_older_than_minutes` | 15 | antigüedad mínima de una acción `PENDING`/`CALLING` para considerarla abandonada |
| `reconcile_events_interval_seconds` | 120 | cada cuánto se reanudan los eventos |
| `reconcile_events_older_than_minutes` | 5 | antigüedad mínima de un evento `RECEIVED` |
| `reconcile_event_max_attempts` | 5 | intentos automáticos por evento (§6) |
| `external_call_max_seconds` | **sin valor contractual** (abajo) | el techo declarado de la duración de una llamada externa de escritura |
| `reconcile_tick_retention_days` | 7 | retención de los trabajos recurrentes completados |

**`external_call_max_seconds`: propósito, restricciones y de dónde sale su valor.** Este ADR **no fija una cifra de producción**: no hay ningún proveedor real del que sacarla y una cifra elegida sin evidencia sería una
constante arquitectónica disfrazada. Define para qué sirve y qué tiene que cumplir:

- **Propósito.** Es el techo que el operador **declara** para cuánto puede durar una llamada externa de *escritura*, y lo usa el barrido para no tomar por abandonada una llamada que aún puede estar legítimamente en curso.
  No es una propiedad del sistema ni de ningún proveedor: es una configuración que debe ser coherente con ellos.
- **Es configurable.** Cambiarlo es cambiar un ajuste, no código.
- **Valor provisional de simulación y desarrollo.** Solo mientras todo es simulado (`operating_in_simulation`) puede existir un valor por defecto, **provisional y no contractual**, para poder implementar y probar el mecanismo: **120 s**.
  No es una cifra de producción, no se deriva de ningún proveedor y no se aplica fuera de la simulación: en `staging` y `production` **no hay valor por defecto**.
- **En `staging` y `production`, antes de conectar un proveedor real, el valor se define a partir de:** (1) el timeout documentado por el proveedor para esa operación; (2) el timeout efectivo del cliente HTTP del adaptador; (3) un margen operacional;
  y (4) la política de `UNKNOWN_OUTCOME` (cuánto dinero y cuánto tiempo se acepta tener inmovilizado mientras se resuelve). La derivación queda escrita junto al adaptador.
- **El arranque falla (cerrado), fuera de la simulación, si la configuración es incoherente con el timeout efectivo del adaptador o del proveedor:** (a) hay un adaptador de escritura no simulado y `external_call_max_seconds` no se ha configurado
  explícitamente; (b) el adaptador no declara su timeout efectivo (`max_call_seconds`) o lo declara mayor que `external_call_max_seconds`; (c) el umbral del barrido no supera el techo con margen:
  `reconcile_actions_older_than_minutes × 60 ≥ 2 × external_call_max_seconds + arriendo del trabajo (60 s)`. En simulación solo se comprueba (c), con el valor provisional (con él y los valores iniciales: 900 ≥ 2 × 120 + 60 = 300).
- **Superar el umbral no es un fallo confirmado.** Una acción `CALLING` que lo supera pasa a `UNKNOWN_OUTCOME`, **nunca** a `FAILED_CONFIRMED`; si no puede conocerse el resultado de una llamada que pudo haber salido, **sigue siendo
  desconocida**. Solo una acción `PENDING` (para la que la frontera de durabilidad de `begin_call` prueba que no salió nada) se cierra como `FAILED_CONFIRMED`. `CALLING` se mide desde `call_started_at` (el instante en que empezó
  la llamada), no desde `updated_at`.

**Lo que el código actual no puede garantizar, dicho con claridad.** Ninguna capa *aplica* hoy ese techo: el contrato del adaptador no lo declara
y `ExternalActionService.execute` no puede interrumpir una llamada síncrona. Mientras no exista un adaptador real, no hay llamada que supere nada; el día
que exista, tiene que **declarar** `max_call_seconds` y aplicarlo, y la batería de conformidad lo comprobará (condición antes del primer proveedor real, §Consecuencias).
No se improvisa una garantía que no existe. Se usa el comportamiento conservador, que es seguro aunque el techo falle, porque **la seguridad no depende del umbral**:

- Si el barrido cierra una acción `PENDING` mientras su petición sigue viva, la petición pierde el compare-and-set de `begin_call` y recibe un 409 **sin enviar nada**
  (P2-1, Commit 1). El coste es una petición lenta rechazada, no un efecto.
- Si marca `UNKNOWN_OUTCOME` una llamada `CALLING` que seguía en vuelo, **conserva la reserva** y no repite nada; cuando la llamada original responda,
  su respuesta es autoritativa y cierra la operación (`late_response`, ADR 0024 §6). El coste es disponibilidad: el intento queda bloqueado hasta entonces o hasta que una persona lo resuelva.

El umbral, por tanto, elige entre ruido (un umbral corto marca antes como desconocido lo que aún podía responder) y latencia (uno largo tarda más en liberar lo que nunca salió). Nunca elige entre seguro e inseguro.

### 4. Cada acción externa sigue gobernada

El reconciliador programado **no ejecuta efectos externos**. No llama a `execute`, no repite una petición con la misma clave y no consulta permisos ni presupuesto porque no gasta:
solo libera lo que nunca salió o marca como desconocido lo que pudo salir. La repetición de una petición con la misma clave (`reconcile` por *key replay*, ADR 0024 §6.2) es **un efecto**: se haría fuera del contexto
de quien lo pidió, sin volver a pasar por el ActionGate, el kill switch ni la política operativa. **El programador no la hace nunca.** Sigue disponible solo como acción humana explícita.

### 5. Barrido de acciones: lo que cambia respecto a hoy

El criterio de `reconcile_interrupted` no cambia (`PENDING` libera, `CALLING` pasa a desconocido, ambos por compare-and-set). Cambia lo que lo rodea:

- el servicio se invoca **por elemento**, cada uno en su transacción, y devuelve qué hizo con cada fila (liberada, desconocida, perdida la carrera, fallida con su causa);
- se audita cada transición con las entradas que ya existen (`external_action.release_unstarted`, `external_action.unknown_outcome`; el actor de auditoría es el actual `external-actions` y lo que libera queda con `resolved_by = reconciler`);
- el trabajo registra en `job_events` cuántas filas hubo de cada clase, y la lista de acciones `UNKNOWN_OUTCOME` más viejas queda en el resumen de estado (§8).

### 6. Eventos `RECEIVED`: un tope de intentos que no inventa estados

`PaymentEvent` es un hecho inmutable salvo su estado de proceso (ADR 0028 §1). Se añaden **tres campos de proceso**, no del hecho: `reconcile_attempts` (entero, 0 por defecto), `last_reconcile_error`
(texto corto y **sin cuerpo ni datos del evento**: tipo de excepción y mensaje truncado) y `last_reconcile_at`.

- **Reclamo de intento.** Antes de llamar a `apply`, una sentencia única `UPDATE … SET reconcile_attempts = reconcile_attempts + 1, last_reconcile_at = :ahora WHERE id = :id AND processing_status = 'RECEIVED' AND reconcile_attempts < :tope`
  (en su propia transacción). Si no toca fila, el evento ya no está pendiente o ya agotó los intentos: se salta. Contar **antes** significa que una caída en mitad de `apply` también cuenta.
- **Éxito o resultado definitivo** (`APPLIED`, `STALE`, `CONFLICT`, `UNMATCHED`): nada que hacer, el evento sale de `RECEIVED` por la puerta de siempre. **Fallo:** se guarda `last_reconcile_error` y se pasa al siguiente evento.
- **Al superar el tope** (`reconcile_attempts ≥ reconcile_event_max_attempts`) se **dejan de reintentar automáticamente**. El evento **sigue `RECEIVED`**: no se crea ningún estado nuevo (cambiar la máquina de estados exigiría una decisión del propietario),
  no se declara `FAILED`, no se libera ninguna reserva y **no se pierde**. Queda **visible para una persona** con sus intentos, su edad y su último error (§8).
- **Las reentregas del proveedor no cuentan.** Un webhook repetido sigue reanudando el evento por `PaymentIngress` como hasta ahora; el tope limita al programador, no al proveedor.
- **Salida humana: `retry-payment-event --id ID --reason …`.** Es una **acción humana y operativa** (consola, con `AMAZONA_BOOTSTRAP=1`, motivo obligatorio), como `resolve-action`; no hay ruta HTTP. Su contrato exacto:
  1. **Reintenta el *procesamiento* de un `PaymentEvent` ya guardado, nada más.** Llama a `PaymentService.apply(event_id)` (la puerta de siempre, con su reclamo compare-and-set). **No vuelve a efectuar el cobro**, **no llama al proveedor de pago**
     ni repite ninguna operación económica, no crea eventos y no pasa por `execute`.
  2. **Solo actúa sobre un evento `RECEIVED`** (atascado o topado). Reinicia `reconcile_attempts` a 0 y `last_reconcile_error` a nulo (el valor anterior queda en la auditoría) y aplica el evento **una vez**.
  3. **Si el evento ya está `APPLIED`, `STALE`, `CONFLICT`, `REJECTED` o `UNMATCHED`, no hace nada**: informa del estado, sale y **no genera ningún efecto económico** (aplicar un evento ya aplicado no mueve dinero: ya probado en M44).
  4. **Respeta la unicidad:** `provider_event_id` y `payload_hash` no se tocan (siguen únicos por `(provider, provider_event_id)` y el mismo id con otro contenido sigue siendo un conflicto); el reintento procesa el evento tal como se guardó, no uno nuevo.
  5. **Queda auditado**, **sin cuerpo ni datos del evento**: `payment_event.reprocess_requested` (quién lo pidió —el actor de la consola—, cuándo, el motivo, el estado y los intentos de antes, y si se llegó a intentar; también cuando no hizo nada) y, si se aplicó o falló, `payment_event.reprocess_result` con el resultado. Son dos entradas para que la petición quede registrada aunque el proceso caiga a mitad.
  6. Es el único camino que vuelve a poner un evento topado en manos del programador (su contador queda a 0).

### 7. `UNKNOWN_OUTCOME`: solo información autoritativa lo cierra

Se mantiene íntegra la regla del ADR 0024. Se precisa quién puede aportar «información»:

- **Respuesta tardía** de la llamada original (`finish` desde `UNKNOWN_OUTCOME`): autoritativa. Ya existe.
- **Persona** (`resolve-action`, con motivo y actor): autoritativa. Ya existe.
- **Consulta (`lookup`) autoritativa**: un adaptador que sabe consultar **debe declarar, además, `lookup_is_authoritative`** (por defecto `False`; la ausencia del atributo es `False`) y, si lo es, `lookup_settle_seconds`: pasado ese tiempo
  desde `call_started_at`, un `None` significa de verdad «el proveedor asegura que no existe». Antes de eso un `None` es «todavía no se sabe» (consistencia eventual del proveedor), no «no existe». `ExternalActionService.reconcile()` **se niega** a cerrar nada con un `lookup` que no sea autoritativo y devuelve `UNKNOWN_OUTCOME`.
- **Los adaptadores simulados declaran `lookup_is_authoritative = False`**: su `lookup` es la memoria de este proceso y **no vale entre procesos**. Un worker nunca cerrará con ella una acción de la API.
- **El programador no llama a `reconcile()` en M45.** No hay ningún adaptador autoritativo (no hay proveedor real), así que no hay nada que consultar; lo que M45 construye es la **puerta cerrada por defecto** (la capacidad explícita y el rechazo), no su uso programado. Cuando exista un adaptador autoritativo, que un trabajo programado
  cierre con su consulta será una decisión posterior con su propia prueba de conformidad. Aun entonces **solo la consulta**, nunca la repetición de la petición (§4).
- **Visibilidad.** Lo desconocido se **hace visible**, no se resuelve: `reconcile.report` y el resumen de estado muestran cuántas acciones están `UNKNOWN_OUTCOME`, desde cuándo y de qué operación; el pedido ya muestra `payment_outcome_unknown`, `refund_outcome_unknown` o `fulfilment_outcome_unknown` en su atención.

### 8. Observabilidad y auditoría

No hay infraestructura de métricas en el repositorio y no se introduce una (ni Prometheus ni nada parecido). Se usa lo que existe:

- `audit_log`: cada transición que haga el programador (las entradas ya existentes de §5); un fallo de un elemento con su causa, sin cuerpos.
- `job_events` y el resultado de cada trabajo: contadores por clase (liberadas, desconocidas, aplicadas, falladas, saltadas por tope, perdidas por carrera).
- Una ruta de **solo lectura** de estado de reconciliación (la usará la pantalla Estado): acciones abiertas por estado con su edad máxima; `UNKNOWN_OUTCOME` más antiguo; eventos `RECEIVED` pendientes y **eventos topados** con intentos, edad y último error; cuándo corrió cada tipo por última vez y si el disparador está encendido.
  Un `GET` no escribe nada (invariante I10 de M44).

### 9. Configuración y validación al arrancar

Los ajustes de §3 son `Settings` con validación de arranque que **falla cerrado**: intervalos de al menos 30 s, umbrales de al menos el arriendo de un trabajo (60 s), `reconcile_event_max_attempts ≥ 1`, y las condiciones de §3 sobre el techo de una llamada externa (que fuera de la simulación incluyen no tener valor por defecto y ser coherente con el timeout efectivo del adaptador).
Un valor fuera de rango impide arrancar con un mensaje claro; no se corrige en silencio ni se ignora.

## Invariantes

Las comprueban las pruebas del Commit 5 (PostgreSQL real para todo lo que sea carrera, bloqueo o compare-and-set):

1. **I1.** Ningún camino programado repite a ciegas una petición externa: el programador no llama a `execute` ni a `reconcile()` por repetición de clave.
2. **I2.** Un `UNKNOWN_OUTCOME` solo sale por respuesta tardía, consulta autoritativa o persona; ningún barrido, tick, reintento ni paso del tiempo lo cierra, y mientras lo es **la reserva se mantiene**.
3. **I3.** Solo una acción `PENDING` (nunca salió) se libera automáticamente, por compare-and-set; una `CALLING` solo pasa a `UNKNOWN_OUTCOME`: **superar un umbral jamás produce `FAILED_CONFIRMED`** de algo que pudo haber salido.
4. **I4.** Dos reconciliadores sobre la misma fila no pueden ganar los dos; dos workers que encolan el mismo tick producen **un** trabajo.
5. **I5.** Un elemento que falla no impide procesar los demás ni deja nada a medias (una transacción por elemento).
6. **I6.** Un evento `RECEIVED` no se pierde: tras el tope sigue `RECEIVED`, visible, con intentos, edad y último error; ninguna máquina de estados cambia.
7. **I7.** `reconcile()` rechaza un `lookup` que no declare ser autoritativo; los adaptadores simulados no lo declaran.
8. **I8.** Fuera de la simulación, el arranque falla si `external_call_max_seconds` no está configurado explícitamente, si el adaptador no declara su timeout efectivo o lo declara mayor que el techo, o si el umbral del barrido no supera el techo con margen; en simulación, solo la última comprobación, con el valor provisional.
9. **I9.** Con el disparador apagado el sistema se comporta como M44 y las órdenes manuales siguen funcionando.
10. **I10.** Ningún `GET` de estado escribe; ningún mensaje, auditoría ni error lleva cuerpos de webhook ni datos personales.
11. **I11.** Todo importe sigue siendo `Money`/`Decimal` y la reserva solo se mueve por `outstanding` de la propia operación (ADR 0024 §8).

## Failure modes

| Fallo | Qué pasa | Por qué es seguro |
|---|---|---|
| El worker muere a mitad de un tick | el arriendo vence y el segador reencola el trabajo; el siguiente tick llegaría igualmente | cada transición es compare-and-set e idempotente |
| Dos workers (o un worker y la consola) reconcilian lo mismo | uno gana por fila, el otro ve `rowcount = 0` y sigue | I4 |
| Una llamada lenta supera el umbral | la petición pierde `begin_call` (409, nada enviado) o la acción pasa a desconocida y su respuesta tardía la cierra | §3: la seguridad no depende del umbral; el coste es disponibilidad |
| Un proveedor deja de responder | la acción queda `UNKNOWN_OUTCOME`; reserva mantenida; visible en el resumen y en la atención del pedido | I2 |
| Un evento lanza siempre | cuenta intentos; al 5.º deja de reintentarse y queda visible; el resto del lote sigue | I5, I6 |
| El reloj de un worker se desajusta | una antigüedad mal medida adelanta o retrasa un barrido; el compare-and-set sigue protegiendo; el margen de §3 absorbe desajustes de segundos | todos los instantes son UTC; la comprobación de §9 deja margen |
| La base de datos no responde | el tick falla y se reintenta con espera (ADR 0009); no se escribe nada a medias | transacción por elemento |
| La configuración del techo de llamada es incoherente con el timeout del adaptador (fuera de la simulación) | el sistema no arranca, con un mensaje claro | I8: no se opera con un umbral que no se sostiene |
| Un adaptador declara un `lookup` autoritativo que no lo es | podría cerrar mal una acción | exige además `lookup_settle_seconds` y pasar la conformidad; **fuera de M45** (no hay adaptadores reales) |
| Los ticks llenan `jobs` | purga de los completados antiguos | retención configurable |

## Alternativas descartadas

- **Un programador aparte (cron, n8n, Celery beat).** Una pieza más que puede olvidarse o caerse, con su propio estado, cuando el runtime ya tiene reclamo, arriendo, reintentos e idempotencia (ADR 0009 §3).
- **Una tabla de horarios con «próxima ejecución».** Otro estado que sincronizar; la clave idempotente por cubo temporal basta y no puede desincronizarse.
- **Cerrar `UNKNOWN_OUTCOME` por antigüedad** («hace mucho que no responde, no ocurrió»). Confunde «hace mucho» con «no ocurrió» (ADR 0024, alternativas descartadas).
- **Que el programador llame a `reconcile()` con repetición de clave.** Es un efecto externo sin ActionGate ni kill switch ni política: se haría sin quien lo pidió.
- **Confiar en `lookup` de los simulados.** Es memoria de proceso: un worker liberaría reservas de operaciones que la API sí hizo.
- **Un estado nuevo para «evento topado».** Cambia una máquina de estados sin que el propietario lo haya decidido; el recuento y la visibilidad bastan.
- **Reintentar los eventos sin tope.** Un evento venenoso se reintentaría para siempre y taparía los logs.
- **Fijar ahora un `external_call_max_seconds` de producción** (por ejemplo 120 s) como cifra del ADR. Sin un proveedor real no hay evidencia (timeout documentado, timeout del cliente, política de desconocidos) de la que derivarla; una cifra sin evidencia sería una constante arquitectónica elegida a ciegas. Se define su propósito y sus restricciones, y el valor lo fija el operador cuando haya proveedor.
- **Exigir que el código garantice `external_call_max_seconds`.** Hoy no se puede (no hay adaptador real y el servicio no interrumpe una llamada síncrona); se declara, se valida lo que sí se puede y se usa el comportamiento conservador.

## Consecuencias

- Ningún estado que pueda bloquear un pedido queda **sin que un reconciliador lo mire**: se libera lo que nunca salió, se marca lo que pudo salir y se hace visible lo desconocido. Lo desconocido sigue necesitando información o una persona: el coste (dinero inmovilizado) es deliberado, el lado seguro de la asimetría del ADR 0024.
- **Antes del primer proveedor real** (añadidas a las condiciones del handoff de M44): `external_call_max_seconds` se **define** a partir del timeout documentado del proveedor, el timeout efectivo del cliente HTTP, un margen operacional y la política de `UNKNOWN_OUTCOME`, y el arranque lo comprueba; el adaptador declara y aplica `max_call_seconds ≤ external_call_max_seconds`; declara `lookup_is_authoritative` y `lookup_settle_seconds` con honestidad y pasa la batería de conformidad; y se decide por separado si algo programado puede cerrar con su consulta.
- `Payment.OPEN` sin cierre y `Refund.SENDING` sin confirmar siguen sin reconciliador (necesitan consulta de estado al proveedor: P2-3 y P2-4).
- Sin infraestructura de métricas, la observabilidad es la auditoría, los eventos de trabajo y una ruta de estado; si hace falta más, será otra decisión.
- El runtime gana un paso de mantenimiento y tres tipos de trabajo; la base gana tres columnas de proceso en `payment_events` (una migración, `d7e2a9c4f1b8`) y ninguna tabla.

## Rollback

- **Apagar:** `reconciliation_enabled = false` detiene el disparador sin tocar código ni datos; las órdenes manuales siguen igual (I9).
- **Revertir:** cada commit de M45 se revierte por separado (`git revert`, nunca `reset`). La migración de las tres columnas tiene `downgrade` y solo quita metadatos de proceso: ningún hecho financiero.
- **Datos:** los trabajos recurrentes ya encolados se purgan o se ignoran; los eventos con intentos contados vuelven a `reconcile_attempts = 0` al revertir la migración y siguen `RECEIVED`.

## Compatibilidad con los ADR existentes

- **ADR 0009 (runtime de trabajos):** se usa tal cual (reclamo `SKIP LOCKED`, arriendo, reintentos, `idempotency_key` única). Se añade un paso al mantenimiento del worker y tres tipos registrados; nada cambia en los estados del trabajo.
- **ADR 0010 / pipeline:** sin cambios. El pipeline no registra observadores y sus acciones siguen el mismo ciclo; el barrido ya las trataba (`pipeline_step:…`) y sigue tratándolas.
- **ADR 0011 (ActionGate):** el programador no ejecuta efectos, así que no pasa por el gate; el veto por resultado desconocido sigue ahí y se levanta por las mismas vías.
- **ADR 0023 (libro de presupuesto):** la reserva solo se libera ante un `PENDING` que nunca salió o una resolución con información; un desconocido la mantiene. Sin cambios.
- **ADR 0024 (acciones externas):** se mantienen la frontera `begin_call`, el compare-and-set, la respuesta tardía y la regla de `UNKNOWN_OUTCOME`. **Se enmienda:** el barrido deja de ser solo una orden del operador y `reconcile` exige un `lookup` autoritativo declarado.
- **ADR 0025 (idempotencia):** sin cambios; un 409 de dominio libera la clave (confirmado en el Commit 1).
- **ADR 0028 (pedidos y pagos):** sin cambios de modelo ni de estados. **Se enmienda:** `PaymentEvent` sigue siendo un hecho inmutable; gana tres campos de **proceso** (intentos, último error, última reconciliación) junto a `processing_status`, `processed_at`, `note` y los enlaces.

## Qué no resuelve este ADR

Consulta de estado de cobros y reembolsos al proveedor, `payment.cancel` y caducidad de un cobro abierto (P2-3, P2-4); limitación de frecuencia del webhook (P2-5); bandeja de aprobación de pedidos; cualquier proveedor, pasarela o transportista real; y aplicar las migraciones de M44 y M45 a Supabase (trabajo aparte con inventario de revisiones, copia, ensayo local, procedimiento y autorización expresa).

## Qué se implementó (Commit 5 de M45)

- `app/reconciliation/` (`actions`, `events`, `report`, `config_check`); `app/jobs/recurring.py` (cubos, claves estables, purga) y el paso de mantenimiento en `Worker.run_once`; los tres manejadores `reconcile.actions`,
  `reconcile.payment_events` y `reconcile.report`; `GET /api/reconciliation/status` (solo lectura); `retry-payment-event` y la consola sobre los servicios.
- `ExternalActionService`: `stale_candidates`, `sweep_one` y `mark_calling_unknown` por elemento; `reconcile()` exige un `lookup` autoritativo declarado (`has_authoritative_lookup`); los adaptadores simulados declaran `lookup_is_authoritative = False`.
- Ajustes (`reconciliation_enabled`, intervalos, umbrales, `reconcile_event_max_attempts`, retención y `external_call_max_seconds` sin valor por defecto fuera de la simulación) con validación de arranque en la API y en cada worker.
- Migración `d7e2a9c4f1b8` (tres campos de proceso en `payment_events`).
- Pruebas: `test_reconciliation_actions`, `test_reconciliation_events`, `test_recurring_scheduler`, `test_lookup_authority`, `test_reconciliation_config`, `test_reconciliation_status` y `test_migration_payment_event_reconcile`, sobre SQLite y PostgreSQL real, con mutaciones.
