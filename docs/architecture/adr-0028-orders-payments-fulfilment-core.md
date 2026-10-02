# ADR 0028: Núcleo de pedido, pago y fulfillment — el dinero lo confirma un evento verificado, y la evidencia financiera nunca se descarta

- **Estado:** Aceptada
- **Fecha:** 2026-10-02
- **Depende de:** [ADR 0003](adr-0003-rls-deny-by-default.md), [ADR 0011](adr-0011-action-gate.md), [ADR 0015](adr-0015-multiple-real-sources-cost-and-usage-rights.md), [ADR 0018](adr-0018-money-conversion-and-not-evaluable.md), [ADR 0022](adr-0022-idempotent-pipeline-run-creation.md), [ADR 0023](adr-0023-single-budget-source-and-absence-is-not-permission.md), [ADR 0024](adr-0024-external-actions-lifecycle-and-unknown-outcome.md), [ADR 0025](adr-0025-generic-idempotency-for-synchronous-routes.md), [ADR 0026](adr-0026-database-identity-guards.md), [ADR 0027](adr-0027-approval-boundary-and-budget-authorisation.md)
- **Enmienda a:** [ADR 0011](adr-0011-action-gate.md) (coste por operación, permiso por acción, `COLLECT_PAYMENT`, `REFUND` fuera del presupuesto), [ADR 0024](adr-0024-external-actions-lifecycle-and-unknown-outcome.md) (observadores de transición) y [ADR 0027](adr-0027-approval-boundary-and-budget-authorisation.md) (nuevos espacios de nombres de referencias del libro y de las acciones externas)
- **Milestone:** 44

## Contexto

Hasta aquí AMAZONA analiza y decide, pero no tiene dónde ocurre una venta: no existe un pedido, un cobro,
un reembolso ni un envío. El panel Operaciones los inventa (`ORDERS_PER_DAY`, `DEMO_CUSTOMERS`). El
hardening pre-M44 dejó lo que hacía falta para construirlos sin repetir un efecto: acciones externas con
resultado desconocido explícito (ADR 0024), idempotencia genérica (ADR 0025) e identidades garantizadas por la
base de datos (ADR 0026).

Este milestone construye **el núcleo de dominio**, 100 % simulado y sin ninguna pasarela, proveedor ni
transportista real. Lo que se construye ahora es lo que un proveedor real tendrá que cumplir después.

## Decisión

### 1. Una sola puerta para los eventos de pago

```
CLI simulate-payment ───────┐
                            ├─► PaymentIngress.receive(provider, headers, raw_body)
POST /api/payments/         │      1. provider.verify_webhook()      ← única vía de crear un VerifiedPaymentEvent
   webhooks/{provider} ─────┘      2. transacción 1: INSERT PaymentEvent(RECEIVED) + COMMIT
                                   3. transacción 2: PaymentService.apply(): reclamo del evento + Payment + Order
```

- **El pago solo se confirma con un evento autenticado.** Ninguna ruta acepta un campo «pagado»; el CLI no
  toca `Order` ni `Payment`; el navegador no confirma nada.
- **El simulador no es otra lógica.** Genera un evento firmado con una clave **efímera por proceso**
  (`secrets.token_bytes`, nunca persistida, registrada ni versionada), lo verifica con el mismo
  `verify_webhook` y lo entrega a la misma puerta. Un webhook real futuro recorre el mismo camino.
- **Dos transacciones.** Se registra primero (`RECEIVED`) y se aplica después. Si el proceso cae entre medias,
  la reentrega del proveedor —o `reconcile-payment-events`— encuentra el evento `RECEIVED` y lo **reanuda**.
  El reclamo (`UPDATE … WHERE processing_status = 'RECEIVED'`) y todos los efectos viajan en la misma
  transacción: no existe «medio aplicado».
- **El cuerpo bruto solo vive durante la verificación.** Se guarda su `payload_hash` (SHA-256) y los campos
  de una lista blanca; un cuerpo real contendría datos personales.
- **Seguridad del webhook:** firma HMAC sobre el cuerpo bruto, comparada en tiempo constante, tolerancia de
  tiempo (anti-replay), `provider_event_id` obligatorio, verificación antes de interpretar el JSON y antes
  de cualquier escritura funcional, rechazo con mensaje fijo y auditoría del rechazo sin el cuerpo. Los
  webhooks **registran hechos aunque el kill switch esté apagado**: no se puede ignorar dinero ya movido.

### 2. Un pedido, varios intentos de cobro (`Order 1:N Payment`)

Un `Payment` es **un intento de cobro**: un objeto de cobro en el proveedor. Se eligió esto frente a
`Order 1:1 Payment` + `PaymentAttempt` porque:

1. `ExternalAction` ya distingue «misma operación reintentada» de «operación nueva» con `(reference,
   sequence)`: un `PaymentAttempt` duplicaría esa maquinaria;
2. un `Payment` único por pedido volvería a imponer la limitación artificial cuando un cobro caduca o se
   cancela;
3. las invariantes se expresan como restricciones de base de datos;
4. cada fila es un «sitio» (`order_payment:{payment_id}`) con su propia clave hacia el proveedor.

**Misma intención frente a intento nuevo.** La `Idempotency-Key` identifica la intención: misma clave, mismo
`Payment`. Una clave nueva con otro intento activo es un 409 que nombra al activo. Una clave nueva con todos los
intentos anteriores terminados abre `attempt_number + 1`. Hacia el proveedor, la clave sale de
`(order_payment:{payment_id}, sequence)`.

**Intentos activos.** `REQUESTED`, `OPENING`, `UNKNOWN_OUTCOME` y `OPEN`. Un pedido tiene como máximo uno
(índice único parcial). Un intento `UNKNOWN_OUTCOME` **bloquea nuevos intentos** hasta que se reconcilia, llega
la respuesta tardía o una persona lo resuelve con `resolve-action`.

**Los PSP con reintentos internos** normalizan un fallo no terminal al evento informativo
`payment.attempt_failed`. Solo `payment.failed` es terminal para el objeto de cobro.

### 3. Estados explícitos, y la frontera de lo enviado

Cada entidad con una operación externa distingue **nada enviado**, **posiblemente enviado** y **resultado
desconocido**:

| Entidad | Nada enviado | Posiblemente enviado | Desconocido |
|---|---|---|---|
| `Payment` | `REQUESTED` | `OPENING` | `UNKNOWN_OUTCOME` |
| `Refund` | `REQUESTED` | `SENDING` | `UNKNOWN_OUTCOME` |
| `Fulfillment` | `READY` (antes de comprar), `PURCHASED` (antes de enviar) | `PURCHASING`, `SHIPPING` | `UNKNOWN_OUTCOME` (con `unknown_phase`) |

El estado «posiblemente enviado» se escribe **en la misma transacción que `begin_call`** (la frontera de
durabilidad de la ADR 0024). Por eso `REQUESTED` garantiza que no salió nada. El mecanismo es una enmienda de
`ExternalActionService`: **observadores por prefijo de referencia**, llamados dentro de la transacción de cada
transición de la acción (`begin_call`, `finish`, `reconcile_interrupted`, `finish_unstarted`, `reconcile`,
`resolve`). Así `reconcile-actions` y `resolve-action` dejan el dominio consistente aunque no sepan nada de
pedidos. El pipeline no registra observadores y no cambia.

**Regla universal.** `UNKNOWN_OUTCOME` no se repite a ciegas, no libera reservas, no se declara `FAILED` y solo
sale por reconciliación, respuesta tardía o resolución humana.

### 4. La evidencia financiera nunca se descarta

> **El hecho financiero prevalece: el dinero existe aunque el pedido esté cancelado o ya cobrado.**
> La base de datos impide que **nuestra aplicación** provoque dos cobros normales; no impide almacenar la
> evidencia de que un proveedor cobró dos veces.

- **Pago canónico.** El índice único parcial `(order_id) WHERE status = 'SUCCEEDED'` es la defensa contra
  nuestro propio código: como mucho un pago `SUCCEEDED` por pedido. **No** impide registrar un segundo cobro
  real, porque ese segundo cobro no se guarda como `SUCCEEDED` sino como `DUPLICATE_CAPTURE`. Si dos capturas
  se aplican a la vez y chocan con el índice, la perdedora se reintenta como `DUPLICATE_CAPTURE` dentro de un
  `SAVEPOINT`: **nunca se descarta**.
- **`DUPLICATE_CAPTURE`** significa: *se ha recibido una captura real válida adicional para un pedido que ya
  tenía otra captura válida.* Registra el importe real (`captured_amount`), enlaza al pago canónico
  (`duplicate_of_payment_id`), exige `attention_required`, impide nuevos cobros, **no modifica el pedido** y
  permite el reembolso posterior. Nunca es un «conflicto técnico».
- **Captura tardía.** Un evento de captura se registra en cualquier estado salvo `REQUESTED` (de ahí no pudo
  salir nada): `OPENING`, `UNKNOWN_OUTCOME`, `OPEN`, `FAILED` y `EXPIRED` incluidos. Un éxito tardío tras un
  `FAILED` o `EXPIRED` no se descarta.
- **Captura sobre un pedido `CANCELLED`.** El dinero se registra (el pago pasa a `SUCCEEDED`), el pedido **no
  vuelve** a `PAID`, queda `attention_required`, se audita la anomalía (`payment.late_capture_on_cancelled_order`),
  se bloquea cualquier cobro nuevo y se puede iniciar el reembolso. El sistema no «arregla» el pedido por su
  cuenta.
- **Captura de un importe distinto** del esperado (`CAPTURE_MISMATCH`): el dinero real se registra tal cual,
  el pedido no cambia, queda `attention_required` y el pago es reembolsable hasta lo capturado. Por esto la base
  de datos **no** exige `captured_amount ≤ amount`: sí exige `refunded ≤ refund_committed ≤ captured` (lo que
  nuestro código no puede incumplir).
- **Un reembolso iniciado por el proveedor** que no cabe en lo cobrado no se aplica a los totales, pero su
  evidencia se conserva íntegra en `payment_events` (`CONFLICT`, con importe y moneda) y se marca la atención.
- **`attention_required` se calcula al leer** (nunca se escribe en un `GET`) a partir del estado: pago
  duplicado, captura sobre pedido cancelado, captura distinta, intento abierto con el pedido ya cobrado,
  resultados desconocidos, evidencia en conflicto o un envío reintentado sin éxito.
- **La suma del dinero realmente capturado es auditable**: `SUM(payments.captured_amount)`, enlazada a los
  `payment_events` inmutables que la causaron.

### 5. Reembolso: entidad propia

Un reembolso es una operación **que iniciamos nosotros** (identidad, importe fijado, reintentos), mientras que
un `PaymentEvent` es un hecho entrante e inmutable. Además, garantizar `Σ reembolsos ≤ cobrado` exige contar los
reembolsos **en vuelo**: hace falta una fila por reembolso.

- La reserva es aritmética de base de datos, como el libro de presupuesto:
  `UPDATE payments SET refund_committed_amount = refund_committed_amount + :a WHERE captured_amount - refund_committed_amount >= :a`,
  con `CHECK (0 ≤ refunded ≤ refund_committed ≤ captured)`.
- `UNKNOWN_OUTCOME` **mantiene** la reserva. Un fallo confirmado la libera. Un reembolso solo se pide sobre un
  pago con dinero capturado (`SUCCEEDED`, `DUPLICATE_CAPTURE`, `CAPTURE_MISMATCH`).
- **`REFUND` no consume presupuesto operativo ni puede ser vetado por un `NO_GO` legal o económico del
  producto**: devolver dinero a un cliente es una obligación, no un gasto discrecional. Sí exige permiso,
  identidad verificada fuera de simulación, `Idempotency-Key`, límite ≤ cobrado, `ExternalAction`, kill switch y
  resolución del resultado desconocido.
- **Aceptado no es devuelto.** Que el proveedor acepte la petición (`ExternalAction` `SUCCEEDED`) deja el reembolso
  en `SENDING` con su referencia: el dinero solo se da por devuelto cuando llega un `refund.succeeded` **verificado**
  (el mismo principio que el cobro: la respuesta de una llamada no confirma dinero). `refunded_amount` solo lo
  mueve ese hecho. Un `SENDING` que el proveedor no confirma en una hora se marca `attention_required`
  (`refund_unconfirmed`). El evento se empareja por la referencia del proveedor o, si la respuesta de pedir la
  devolución se perdió, por nuestro `refund_id` (la referencia de cliente que enviamos).
- Un resultado desconocido de un reembolso **bloquea nuevos reembolsos del mismo cobro** (el veto del gate por
  resultado desconocido, acotado a «sus» reembolsos) hasta reconciliarlo o resolverlo.
- Ningún camino crea reembolsos automáticamente: siempre hay una orden humana explícita (plan maestro §33). Una
  automatización futura tendría que pasar por `REQUIRE_APPROVAL`.

### 6. Fulfillment: un pedido, varios; y una unidad comprada no vuelve al pool

El modelo **no asume** que todas las líneas de un pedido se compran al mismo proveedor ni que se envían en un
solo fulfillment. Un pedido puede acabar necesitando varios fulfillments, cada uno con un subconjunto de líneas
(`fulfillment_items`). M44 no implementa sourcing multi-proveedor ni envíos parciales avanzados; solo evita que el
esquema los haga imposibles. Una línea de pedido tiene identidad propia (`line_number`), y el mismo producto puede
repetirse en varias líneas (variante, proveedor, cotización, precio, lote).

**Asignación.** `order_items.allocated_quantity` se mueve con aritmética de base de datos
(`UPDATE … WHERE quantity - allocated_quantity >= :q`, `CHECK 0 ≤ allocated ≤ quantity`): ninguna línea se asigna
de más, ni siquiera con peticiones simultáneas.

**`release_allocation()` — qué estados pueden ejecutarla.** Una unidad confirmada como comprada no puede volver
al pool disponible automáticamente (evita la doble compra):

| Estado del fulfillment | ¿Puede liberar la asignación? |
|---|---|
| `READY` → `CANCELLED` (cancelar antes de comprar) | **Sí** |
| `READY` → `FAILED` (compras fallidas de forma confirmada, sin compra confirmada) | **Sí** |
| `PURCHASING` | No (la compra puede estar en vuelo) |
| `PURCHASED`, `SHIPPING`, `SHIPPED`, `COMPLETED` | **No, nunca** |
| `UNKNOWN_OUTCOME` (de cualquier fase) | **No** |

La liberación es una sola función cuyo compare-and-set exige `status = 'READY' AND purchased_at IS NULL AND
unknown_phase IS NULL` en la misma transacción. Un fallo de **envío** posterior a `PURCHASED` no pasa a `FAILED`:
el fulfillment vuelve a `PURCHASED` con `failed_attempts + 1`, las unidades siguen asignadas, queda una incidencia
operativa (`attention_required`), el envío puede reintentarse y puede requerir resolución humana; **nunca** se
reasignan en silencio a otro fulfillment.

La entrega (`COMPLETED`) es una confirmación humana con actor: no hay transportistas todavía.

### 7. Cada operación externa, gobernada

Que una operación no consuma presupuesto no significa que no tenga gobierno:

| Control | `payment.open` | `payment.refund` | `fulfillment.purchase` | `fulfillment.ship` |
|---|---|---|---|---|
| Identidad verificada fuera de simulación | sí | sí | sí | sí |
| RBAC (`ApiAction`) | `PAYMENT_WRITE` | `REFUND_WRITE` (OWNER, ADMIN) | `FULFILMENT_WRITE` | `FULFILMENT_WRITE` |
| Política operativa del proveedor | sí | sí | sí | sí |
| Kill switch (gate y `begin_call`) | sí | sí | sí | sí |
| `PermissionEngine` | `PAYMENT_COLLECT` | `MONEY_REFUND` | `EXTERNAL_SPEND` | `EXTERNAL_SPEND` |
| Vetos del gate | legal `NO_GO`; resultado desconocido | solo resultado desconocido de sus reembolsos | legal; economía si gasta; presupuesto; desconocido | legal; presupuesto si hay coste; desconocido |
| Presupuesto operativo | no | **no** | sí | solo con coste conocido positivo |
| `ExternalAction` e `Idempotency-Key` | sí | sí | sí | sí |

**Coste por operación (`ActionCost`):** `ZERO` (cero declarado, con procedencia), `KNOWN(Money)` y `UNKNOWN`.
`UNKNOWN` nunca significa cero. Una operación con coste conocido positivo, o desconocido, se trata como gasto:
el desconocido se deniega siempre, el conocido pasa por la misma disciplina de reserva y compromiso del libro.
`SimulatedFulfilmentAdapter` declara el envío como `ZERO` simulado; un adaptador real con coste desconocido no
ejecutaría ningún gasto. No se construyen tarifas de transporte.

**`ProviderOperatingPolicy` complementa a `usage_rights`, no la sustituye.**

- `usage_rights` = **qué podemos hacer con los datos** de la fuente (guardar, derivar, redistribuir…).
- `ProviderOperatingPolicy` = **qué operaciones externas declara soportar** ese adaptador y bajo qué condiciones
  (efectos reales o simulados, modelo de coste, idempotencia, consulta).

Una operación no declarada se deniega (`UNKNOWN → DENIED`). No se duplican derechos: una política no dice qué se
puede hacer con un dato, y una entrada de derechos no dice qué operaciones admite un adaptador.

**Sin bandeja de aprobación de pedidos.** Cuando el gate responde `REQUIRE_APPROVAL` para una operación de un
pedido, M44 devuelve 409 con los motivos y no ejecuta nada. Crear la autorización sería una tercera clase de
permiso de un solo uso, el disparador que la ADR 0027 deja para unificar el mecanismo; queda para M45.

### 8. Dinero y datos personales

- Todo importe es `Money` (`Decimal`, nunca `float`) y `Numeric(18,4)` más moneda en base de datos; en la API
  viaja como cadena. Los importes de cobros, reembolsos y compras se limitan a céntimos. La única frontera
  legada es `ExternalAction.amount` y el libro (`float`), que se cruza con `legacy_float`.
- **Desconocido no es cero**: IVA, envío, descuentos, comisión de pasarela y coste de proveedor no tienen
  columna salvo que se conozcan; el coste de una línea es `NULL` si no se conoce.
- **Sin datos personales.** Un pedido solo lleva `customer_ref`, una referencia opaca (1–64 caracteres de
  `[A-Za-z0-9._:-]`, sin `@`). En simulación debe empezar por `sim_` y fuera de simulación no puede hacerlo; un
  `CHECK` de base de datos lo impide mezclar. Ni nombre, ni email, ni teléfono, ni dirección, ni datos fiscales.
  Un test de esquema comprueba que ninguna tabla nueva los tiene.

### 9. Idempotencia

Las rutas con efecto exigen `Idempotency-Key` **siempre**, también en simulación (428 si falta), más estricto
que la ADR 0025. El frontend conserva la clave por **intención** (operación, objetivo y parámetros canónicos):
la mantiene en el doble clic, el timeout, el 5xx, el fallo de red y el 409 «en curso», y la renueva cuando
cambian los parámetros o tras un éxito. El webhook se deduplica por `(provider, provider_event_id)`; un mismo id
con otro `payload_hash` es un 409 y el original queda intacto.

### 10. Operaciones muestra datos reales o un estado vacío

El panel deja de inventar pedidos, clientes y transportistas. Lo que M44 puede representar se lee de
`GET /api/orders`; lo que no, es un estado vacío explícito. Lo que siga siendo demostración queda etiquetado.

## Qué queda expresamente fuera de M44

Web pública KOVA, carrito, checkout y cuentas de cliente; pasarela, proveedor de abastecimiento o transportista
reales; datos personales de clientes (RGPD); IVA/OSS, factura y contabilidad; conversión de moneda; cancelación
de un cobro abierto en el proveedor (`payment.cancel`); devoluciones físicas; seguimiento de envíos; sourcing
multi-proveedor y envíos parciales avanzados; bandeja de aprobación de pedidos; el libro económico de ingresos
(M45).

## Consecuencias

- Un pago confirmado se aplica una sola vez, y el dinero realmente cobrado es siempre auditable, aunque viole la
  expectativa comercial.
- Hay tres cambios sobre piezas endurecidas: observadores en `ExternalActionService`, el gate por operación
  (coste, permiso, `COLLECT_PAYMENT`, `REFUND`) y dos dominios de proveedor nuevos (pago y fulfillment). La
  política de arranque no cambia (staging/production siguen sin arrancar con `mock`), pero ahora exige además
  adaptadores no simulados de pago y fulfillment.
- `attention_required` se deriva en lectura: no hay una columna que pueda quedar obsoleta.
- Un intento de cobro `OPEN` solo se cierra por evento del proveedor hasta que exista `payment.cancel`.
- Las migraciones de M44 **no se aplican a Supabase** sin una autorización y un procedimiento aparte.

## Alternativas descartadas

- **`Order 1:1 Payment` + `PaymentAttempt`:** duplica `(reference, sequence)` y vuelve a limitar los cobros
  tras una caducidad.
- **Descartar o marcar como conflicto un éxito tardío:** pierde dinero real de la contabilidad.
- **`UNIQUE(order_id)` sobre fulfillment, o sobre `(order_id, product_id)` en las líneas:** cierran
  estructuralmente el múltiple proveedor, las variantes y los lotes.
- **Liberar la asignación de un fulfillment fallido en cualquier estado:** permitiría comprar dos veces la
  misma unidad.
- **Un solo estado «pendiente» para «no enviado» y «resultado desconocido»:** hace ambigua la recuperación.
- **Proyectar el resultado de una acción externa al dominio con un barrido:** deja un estado intermedio tras
  `reconcile-actions` o `resolve-action`.
- **Registrar el cuerpo bruto del webhook:** incorpora datos personales que no necesitamos.
