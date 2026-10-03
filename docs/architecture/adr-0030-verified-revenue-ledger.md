# ADR 0030: Registro de ingresos verificados — una proyección inmutable de hechos de pago verificados, no una segunda fuente de verdad

- **Estado:** Aceptada (decisiones del propietario del 2026-10-03). **Implementada en el Commit 7 de M45** (ver «Qué se implementó»); el Commit 6 solo la decidió, sin tabla, migración, código ni ruta.
- **Fecha:** 2026-10-03
- **Depende de:** [ADR 0003](adr-0003-rls-deny-by-default.md), [ADR 0023](adr-0023-single-budget-source-and-absence-is-not-permission.md), [ADR 0024](adr-0024-external-actions-lifecycle-and-unknown-outcome.md), [ADR 0026](adr-0026-database-identity-guards.md), [ADR 0028](adr-0028-orders-payments-fulfilment-core.md), [ADR 0029](adr-0029-scheduled-reconciliation-and-unknown-outcome-authority.md)
- **Enmienda a:** [ADR 0028](adr-0028-orders-payments-fulfilment-core.md) (anexo E10: el dinero verificado tiene una proyección inmutable) y [ADR 0023](adr-0023-single-budget-source-and-absence-is-not-permission.md) (anexo: el gasto sigue siendo del libro de presupuesto; el margen es una lectura)
- **Milestone:** 45 (cierra la mitad de P1-2: de dónde sale el dinero real de Dashboard, CFO y Proyectos)
- **Nombre:** *Verified Revenue Ledger* / **Registro de ingresos verificados**. Internamente, el módulo será `app/revenue/` y la tabla `revenue_ledger_entries`.

> **Qué NO es.** Este registro **no es el libro contable ni fiscal de KOVA**. Es un registro de *hechos monetarios operativos
> verificados* que salen del dominio de pagos. No sustituye contabilidad, facturación, IVA/OSS, conciliación bancaria,
> comisiones de pasarela ni reconocimiento contable o fiscal definitivo (§17). Cuando este documento dice «ingreso» quiere decir
> «ingreso operativo verificado», nunca «ingreso contable».

## Contexto

M44 dejó el dinero bien guardado pero mal contado. Lo que existe hoy, comprobado en el código:

1. **El dinero cobrado solo existe como columnas de un estado mutable**: `payments.captured_amount`, `refund_committed_amount` y
   `refunded_amount` (`app/db/models/payment.py`). No hay una lista de hechos («en este instante entró esta cantidad por este
   evento»), solo un saldo que se actualiza. Para responder «cuánto se ha cobrado este mes» hay que sumar estados, y para responder
   «de dónde sale este importe» hay que reconstruirlo a mano desde `payment_events`.
2. **Dos únicos puntos de escritura.** `captured_amount` solo lo escribe `PaymentService._record_capture`
   (`app/payments/service.py`). `refunded_amount` solo lo suben `ledger.settle` (reembolso iniciado por nosotros) y
   `ledger.reserve_and_settle` (reembolso iniciado por el proveedor), y los dos solo se llaman desde `PaymentService`
   (`git grep`: ningún otro llamante; `RefundActionObserver` solo hace `release`, nunca `settle`). Los dos nacen de un
   `PaymentEvent` verificado y aplicado. Por eso una proyección puede nombrar siempre el evento que la causó.
3. **La clasificación ya existe como estado del cobro.** `Payment.status` es `SUCCEEDED`, `DUPLICATE_CAPTURE` (con
   `duplicate_of_payment_id`) o `CAPTURE_MISMATCH`, con `CHECK`s que las sostienen, y esos tres estados son terminales (no están en
   `CLOSABLE_PAYMENT_STATUSES`). No hace falta inventar lógica de clasificación: hay que reflejarla.
4. **`financial_events` no sirve para ingresos.** Es el libro de gasto (ADR 0023/0026): `Numeric(12,2)`, **sin columna de
   moneda**, con clave foránea a `budgets` y unicidad «una reserva y una liquidación por referencia». Los ingresos son
   multimoneda `Numeric(18,4)` y su identidad es un `PaymentEvent`. Mezclarlos rompería el invariante del presupuesto y la regla
   «no convertir divisas».
5. **El gasto no tiene moneda.** `ExternalAction.amount` y `financial_events.amount` carecen de columna de moneda (y
   `financial_events.amount` es `float` en el modelo). El fulfillment cotiza en la moneda del pedido
   (`provider.quote_cost(..., currency=order.currency)`) pero guarda el importe sin su moneda y reserva `float(action.amount)` en el
   presupuesto. Para un pedido que no esté en EUR el gasto no tiene una moneda demostrable. Es una inconsistencia **previa a M45**
   (§14): este ADR no la corrige, la rodea.
6. **No hay precedente de triggers** en `alembic/versions/`. Sí hay precedente de RLS (`10de07bea94d`, `9f2b6c0a1d47`).
7. **Existe `app/payments/ledger.py`**, y no es esto: es la *aritmética de reembolsos* sobre `payments` (`reserve`, `settle`,
   `release`). El nombre «ledger» ya está ocupado; de ahí el módulo `app/revenue/` y el nombre «registro de ingresos».
8. Dashboard, CFO y Proyectos siguen mostrando pedidos inventados (P1-2). Para que dejen de hacerlo necesitan un dinero real que
   mostrar y poder decir de dónde sale.

## Decisión

### 1. Propósito y límites

El registro responde a una sola pregunta: **«¿qué dinero se ha verificado que entró o salió por pagos, en qué moneda, cuándo y
por qué hecho?»** Es una lista de hechos, no de saldos.

| Es | No es |
|---|---|
| Una proyección determinista e **inmutable** de hechos de pago verificados | Una segunda fuente de verdad económica |
| Dinero observado, clasificado y trazable hasta su `PaymentEvent` | El libro contable ni fiscal oficial de KOVA |
| Multimoneda, exacto por moneda (`Decimal`/`Numeric(18,4)`) | Una conversión de divisas (no hay FX) |
| De ingresos y reembolsos del dominio de pagos | De gasto (el gasto sigue siendo del libro de presupuesto) |
| Una base honesta para Dashboard, CFO y Proyectos | Facturación, IVA/OSS, comisiones, impuestos ni conciliación bancaria |

### 2. Fuentes de verdad: el hecho es la causa, el registro es su proyección

- **La fuente de verdad del dinero verificado es el hecho de pago**: un `PaymentEvent` verificado y *aplicado* por
  `PaymentService` (ADR 0028 §1), con el estado que ese evento produjo en `Payment` y `Refund`.
- **El registro no decide nada.** Cada entrada es una función determinista de `(evento, cobro, reembolso)` en el instante en que
  `PaymentService` aplica el evento: mismo hecho, misma entrada. No contiene nada que el hecho no contuviera.
- **Una entrada nunca aparece porque un pedido «diga» `PAID`.** El estado visible de un pedido (`PAID`, `CANCELLED`, lo que sea)
  no crea, no modifica ni borra entradas. Una captura tardía sobre un pedido cancelado **sí** crea entrada: el dinero existe
  aunque el pedido no vuelva a `PAID` (ADR 0028 §4).
- **Trazabilidad obligatoria hacia** `PaymentEvent`, `Payment`, `Order` y, cuando corresponde, `Refund` (§3). No hay entradas
  sin procedencia.
- **El registro no es un contador mutable.** No existe una fila «ingresos del mes» que se suba y se baje: los totales se
  calculan siempre sumando entradas (por moneda y clasificación).

### 3. La tabla `revenue_ledger_entries` (decidida; se crea en el Commit 7)

| Columna | Tipo / regla |
|---|---|
| `id` | identidad (`IdMixin`). Sin `updated_at`: una fila no cambia |
| `kind` | `CAPTURE` \| `REFUND` (`CHECK`) |
| `classification` | `ORDER_PAYMENT` \| `DUPLICATE_RECEIPT` \| `MISMATCH_RECEIPT` (`CHECK`) |
| `payment_event_id` | FK `payment_events`, `NOT NULL`, **único**: la procedencia |
| `payment_id` | FK `payments`, `NOT NULL` |
| `order_id` | FK `orders`, `NOT NULL` (copia del pedido del cobro en el instante del hecho) |
| `refund_id` | FK `refunds`; `NOT NULL` si `kind = REFUND`, `NULL` si `CAPTURE` (`CHECK`) |
| `capture_entry_id` | FK a la entrada `CAPTURE` del mismo cobro; `NOT NULL` si `REFUND`, `NULL` si `CAPTURE` (`CHECK`) |
| `amount` | `Numeric(18,4)`, `> 0` (`CHECK`); el importe del evento |
| `currency` | `String(3)`, la del cobro (el evento solo se aplica si coincide) |
| `occurred_at` | cuándo ocurrió el hecho según el proveedor (`PaymentEvent.occurred_at`), no cuándo llegó |
| `recorded_at` | cuándo se proyectó (el reloj de la transacción que aplicó el evento) |

Restricciones de identidad (ver §9) y de herencia (ver §5):

- `UNIQUE (payment_event_id)`.
- Índice único parcial: **una** `CAPTURE` por `payment_id`; **una** `REFUND` por `refund_id`.
- `UNIQUE (id, classification, currency, payment_id)` y, desde las filas `REFUND`, una **clave foránea compuesta**
  `(capture_entry_id, classification, currency, payment_id) → (id, classification, currency, payment_id)`: la base de datos
  garantiza que un reembolso hereda clasificación, moneda y cobro de la captura que revierte, sin que ningún código pueda
  olvidarlo. (Con `MATCH SIMPLE`, las filas `CAPTURE` —con `capture_entry_id` nulo— no se comprueban.)
- Sin columna `float`; sin columna de coste, de comisión ni de impuesto (§15).

### 4. Qué entrada produce cada caso (y qué no)

| Caso | Estado del cobro / evento | ¿Entrada? | Dónde se ve |
|---|---|---|---|
| **Captura normal** | `payment.succeeded` aplicado; cobro `SUCCEEDED` | **Sí**: `CAPTURE`, `ORDER_PAYMENT` | Ingreso verificado |
| **`DUPLICATE_CAPTURE`** | un segundo cobro real del mismo pedido; cobro `DUPLICATE_CAPTURE` (con `duplicate_of_payment_id`) | **Sí**: `CAPTURE`, `DUPLICATE_RECEIPT` | «Dinero en revisión», **fuera** del titular de ingresos |
| **`CAPTURE_MISMATCH`** | captura de un importe distinto del esperado; cobro `CAPTURE_MISMATCH` | **Sí**: `CAPTURE`, `MISMATCH_RECEIPT`, por el importe **realmente** capturado | «Dinero en revisión», fuera del titular |
| **`CONFLICT`** | el evento contradice un hecho ya registrado o no se puede aplicar sin inventar | **No** | «Evidencia económica pendiente de revisión» |
| **`UNMATCHED`** | ningún cobro nuestro lo explica | **No** | «Evidencia económica pendiente de revisión» |
| `STALE` | ya estaba registrado (misma captura, mismo reembolso, etc.) | No (ya hay una entrada del hecho original) | — |
| `RECEIVED` | verificado, todavía no aplicado | No (no hay hecho aplicado) | Estado de reconciliación (ADR 0029) |
| `REJECTED` | hoy ningún código asigna este estado | No (no sería un hecho verificado) | — |

**`CONFLICT` y `UNMATCHED` con dinero** (decisión D1). Un evento `CONFLICT` o `UNMATCHED` cuyo `amount` no sea nulo se conserva
**sin alterar su evidencia original** en `payment_events` (ya es inmutable salvo su estado de proceso) y se hace **visible** como
«evidencia económica pendiente de revisión»: una lectura (no una tabla nueva) de los eventos en esos dos estados con importe, por
moneda, con su nota, su edad y su procedencia. Ejemplos reales que hoy acaban en `CONFLICT` con importe: una captura en otra
moneda que la del cobro; un segundo evento de captura con otro importe para el mismo cobro; un reembolso confirmado por un
importe distinto del pedido; un reembolso del proveedor que no cabe en lo capturado. **No generan entrada porque no cambiaron el
estado del cobro**: si la generaran, `Σ entradas ≠ columnas del cobro` (L7). Tampoco se suman al ingreso: el sistema ni oculta ni
cuenta lo que no puede explicar. Una persona decide (y, si hace falta, un reembolso o un nuevo hecho verificado cambia el estado
y entonces sí hay entrada).

### 5. Reembolsos: el normal y el de dinero en revisión (decisión D2)

- Un reembolso **confirmado** (`refund.succeeded` aplicado) genera una entrada `REFUND`. Un reembolso fallido, pedido o en vuelo
  **no**: la reserva (`refund_committed_amount`) no es dinero que haya salido, es una intención, y sigue viviendo solo en el cobro.
- **Herencia exacta de clasificación.** La entrada `REFUND` apunta, con `capture_entry_id`, a la entrada `CAPTURE` del cobro que
  revierte y **hereda su clasificación** (y su moneda y su cobro, por la clave foránea compuesta de §3):
  - captura normal → el reembolso **reduce el ingreso verificado** (`ORDER_PAYMENT`);
  - `DUPLICATE_CAPTURE` o `CAPTURE_MISMATCH` (dinero en revisión) → el reembolso **reduce ese dinero en revisión**
    (`DUPLICATE_RECEIPT` / `MISMATCH_RECEIPT`), **no** el ingreso legítimo.
  Esta es, de hecho, la forma normal de resolver un duplicado: devolverlo.
- **Nunca se netea entre clases.** Los totales se calculan por moneda **y clasificación**; un reembolso de un duplicado no
  «compensa» un ingreso normal ni al revés.
- **Reconstrucción sin inferencias.** Dado un reembolso se llega a su captura por `capture_entry_id` (no por «el cobro del
  pedido más probable»), a su evento por `payment_event_id`, a su `Refund` por `refund_id` y a su pedido por `order_id`. Dada una
  captura se obtienen sus reembolsos por `capture_entry_id`.
- Los reembolsos iniciados por el proveedor (`origin = PROVIDER`, p. ej. desde su panel) siguen la misma regla: el `Refund` se
  crea en la misma transacción (`PaymentService._provider_refund`) y su entrada lo referencia.

### 6. Relación exacta con `PaymentEvent`

- Una entrada nace de **exactamente un** `PaymentEvent` y un `PaymentEvent` produce **como mucho una** entrada
  (`UNIQUE (payment_event_id)`).
- Solo dos tipos de evento producen entradas, y solo cuando el efecto se aplicó: `payment.succeeded` → `CAPTURE` y
  `refund.succeeded` → `REFUND`. Ningún otro tipo (`payment.failed`, `payment.expired`, `payment.attempt_failed`,
  `refund.failed`) crea entradas.
- El evento referenciado es siempre uno **`APPLIED`**. El registro no escribe nada en el evento: `PaymentEvent` sigue siendo un
  hecho inmutable salvo su estado de proceso (ADR 0028 §1, ADR 0029 §6); la relación evento→entrada se obtiene por el índice
  único de la entrada.
- Un evento `RECEIVED` (verificado, sin aplicar) **no** tiene entrada: el dinero verificado pendiente de aplicar se ve en el
  estado de reconciliación (ADR 0029), que ya lo cuenta con su edad y sus intentos.

### 7. Atomicidad: evento aplicado + cambio económico + entrada, o nada

Las tres cosas ocurren dentro de la transacción que ya envuelve `PaymentService.apply` (reclamo por compare-and-set, efectos,
resultado del evento). Los puntos exactos (los únicos que mueven dinero, §Contexto 2):

1. **Capturas:** la entrada se escribe **dentro de `_record_capture`**, justo después del `UPDATE` compare-and-set del cobro y
   antes de devolver; así, **donde quiera que se llame** a `_record_capture` la entrada comparte su suerte.
2. **Reembolso de una operación nuestra:** en `_refund_succeeded`, tras mover el `Refund` a `SUCCEEDED` y `ledger.settle` con éxito.
3. **Reembolso del proveedor:** en `_provider_refund`, tras `reserve_and_settle` y crear y vaciar (`flush`) el `Refund`, para tener
   su `id`.

**Savepoint.** Cuando no hay otro cobro canónico, `_capture` registra la captura dentro de `begin_nested()`; si pierde la carrera de
«un solo `SUCCEEDED` por pedido» (`uq_payments_one_succeeded_per_order`), el savepoint se deshace **con la captura y con su entrada**,
y la captura se reintenta como `DUPLICATE_CAPTURE`, que escribe **otra** entrada, ahora `DUPLICATE_RECEIPT`. Nunca queda una entrada
huérfana de una captura que no existe, ni una captura sin entrada.

**Requisito que sale de leer el código** (y que el Commit 7 tiene que cumplir y probar). Hoy `_capture` captura *cualquier*
`IntegrityError` del savepoint, busca un cobro canónico y, si no lo encuentra, **sigue** hacia `_mark_order_paid` como si la captura
se hubiera registrado. Con la entrada dentro del savepoint aparecen `IntegrityError`s nuevos posibles (por ejemplo, una violación de
`UNIQUE (payment_event_id)`) que **no** son la carrera. Esos **no** pueden tragarse: el Commit 7 debe distinguir la restricción de la
carrera (`uq_payments_one_succeeded_per_order`) de cualquier otro fallo y dejar que este último **suba** y deshaga el evento entero.

**Falla cerrada.** Si la entrada no se puede escribir, el evento **no se aplica**: la transacción se deshace, el evento sigue
`RECEIVED` y entra en el ciclo de la ADR 0029 (reintento programado, tope de 5, visible). No existe el estado «aplicado sin entrada»
ni «entrada sin evento aplicado». El orden de bloqueo no cambia (pedido → cobro, ADR 0028 E1): la entrada solo añade filas nuevas
y referencias a filas que esta transacción ya tiene bloqueadas. **No hay interruptor para apagar el registro**: apagarlo haría
divergir el estado y el libro y violaría L3.

### 8. Política append-only

- Una entrada **nunca se actualiza ni se borra.** Un `trigger` de base de datos rechaza `UPDATE` y `DELETE` (y `TRUNCATE` en
  PostgreSQL). No hay un tipo `REVERSAL` ni correcciones manuales en M45: un hecho no se «arregla», se **compensa con un nuevo hecho
  verificado** (un reembolso es una entrada `REFUND`, no una edición de la captura).
- Una entrada errónea es un **defecto**, no un dato: lo detecta la reconciliación (§12), se diagnostica y se resuelve con una decisión
  y una migración aprobadas, nunca con un `UPDATE`.
- Defensa en profundidad: `CHECK`s (importe positivo, clases cerradas, coherencia `kind`/`refund_id`/`capture_entry_id`), claves
  foráneas, RLS activada (ADR 0003: sin acceso para `anon` ni `authenticated`) y una **prueba de arquitectura** de que solo
  `app/revenue/` escribe en la tabla y solo `PaymentService` llama a ese módulo.
- **Límite honesto:** el trigger protege contra el código y contra el SQL accidental. **No** protege contra el dueño de la tabla o un
  superusuario, que pueden desactivarlo o tocar el esquema; contra eso solo valen el control de acceso a la base y la auditoría.

### 9. Idempotencia

Varias capas independientes, de modo que ninguna sola sea la barrera:

1. `PaymentEvent` es único por `(provider, provider_event_id)`: la misma entrega dos veces es **un** evento (ADR 0028 §9).
2. `PaymentService.apply` solo actúa sobre `RECEIVED` y lo reclama por compare-and-set: un evento ya aplicado no vuelve a hacer
   nada.
3. `UNIQUE (payment_event_id)`, **una** `CAPTURE` por cobro y **una** `REFUND` por reembolso: aunque dos caminos se cruzaran, la base
   rechaza la segunda entrada (y, por §7, rechazaría y deshará el evento entero, no solo la entrada).
4. La misma captura anunciada por **otro** `provider_event_id` ya no llega a escribir: `_capture` la devuelve como `STALE` si el
   importe coincide o `CONFLICT` si no.
5. Un reintento de un evento `RECEIVED` (el reconciliador, `retry-payment-event`) vuelve a ejecutarlo **entero** desde cero:
   como la transacción se deshizo, no hay mitad aplicada que duplicar.

### 10. Moneda: EUR y multidivisa

- **El registro es multimoneda y exacto por moneda.** Cada entrada lleva la moneda del cobro; los totales se calculan **por moneda**
  y por clasificación; **una moneda nunca se suma con otra**. No hay conversión: no se asume FX, no se usan tipos de cambio y
  no se «redondea a EUR».
- **EUR es la única moneda en la que M45 calcula márgenes** (decisión D3). Un margen exige a la vez: pedido, cobro verificado
  (`ORDER_PAYMENT`) y coste confirmado, todos en EUR, y procedencia suficiente. Para cualquier otro caso se muestra «Sin datos».
- «EUR» es una **decisión de M45**, no un ajuste: `Settings.currency` (que existe en `SpendLimitSettings`) es el techo de gasto de
  un proveedor, no una moneda contable global, y no se usa para esto.
- **Por qué hace falta la restricción:** el gasto no guarda moneda (§Contexto 5). Para un pedido en EUR se puede afirmar que el gasto
  está en EUR (es la moneda del presupuesto y de los techos); para uno que no lo esté, no se puede, y **no se adivina**.
- **La inconsistencia previa** (el fulfillment cotiza en la moneda del pedido y reserva ese importe en un presupuesto sin moneda,
  sin convertir) queda registrada como **deuda de M45**, **sin corregir aquí**: el margen la rodea al limitarse a EUR.
- La futura capa multidivisa (conversión explícita, con tipo y fecha documentados) se resolverá en un milestone posterior; este ADR
  no la anticipa.

### 11. El margen es una lectura, no una entrada

El coste **permanece fuera del registro de ingresos** (decisión D3 del plan). Ingresos: este registro. Gasto: el libro de
presupuesto (`financial_events`) y las fuentes de coste ya autorizadas (ADR 0023). El margen de un pedido es una **proyección de
lectura** que solo se calcula si **todas** estas condiciones se cumplen, y si no, «Sin datos»:

- pedido, cobro y entradas en EUR (§10);
- hay entradas `ORDER_PAYMENT` del pedido (el dinero en revisión no es margen);
- el coste está **confirmado y conocido**: las fases de fulfillment que haya tenido el pedido tienen su acción `SUCCEEDED`, con
  importe conocido y su `COMMIT` en el libro de presupuesto (el enlace gasto→pedido es la referencia
  `order_fulfilment:{fulfillment_id}:{fase}`);
- un coste desconocido o sin confirmar **no es 0**; un importe ausente **no es 0**.

La fórmula exacta y su cálculo con `Decimal` (`financial_events.amount` es `float` de 2 decimales y se leerá con `Decimal(str(...))`)
se fijan en el commit de los agregados de lectura; este ADR fija las **condiciones necesarias**, no la implementación.

### 12. Reconciliación (solo lectura)

El registro se reconcilia con el estado de pago **sin corregir nada**. Dentro del trabajo `reconcile.report` (ADR 0029 §8, ya de solo
lectura) se comprueba:

- **C1.** Por cobro: `Σ CAPTURE = captured_amount`.
- **C2.** Por cobro: `Σ REFUND = refunded_amount`.
- **C3.** Toda entrada nombra un `PaymentEvent` `APPLIED` del tipo que corresponde a su `kind`.
- **C4.** Todo cobro con dinero capturado desde que existe el registro tiene su entrada `CAPTURE` (ver §13 para lo anterior).

Las divergencias se **informan** (cobro, diferencia por moneda, motivo), con un contador, en el estado de reconciliación; **nunca**
se corrigen solas. Una divergencia es un defecto con prioridad, porque L3 dice que no puede ocurrir.

### 13. Datos anteriores al registro

- **Sin retrorrelleno en M45.** No hay dinero real (todo es simulado, ADR 0028), la base local es desechable y Supabase
  **no tiene siquiera las tablas de pagos** (12 migraciones). Una base con cobros capturados antes de la migración es posible en
  local; su estado es **`outside_ledger`**, no un fallo.
- **Definición operativa.** Un cobro con `captured_amount > 0` y **sin entrada `CAPTURE`** cuyo evento de captura se aplicó **antes**
  de la primera entrada del registro (o con el registro vacío) es `outside_ledger`: se **lista** aparte en la reconciliación como
  informativo, con sus importes, y **no** cuenta como divergencia. Uno **posterior** a la primera entrada sin su entrada **sí** es
  una divergencia (C4). *Limitación declarada:* con el registro vacío no se distingue un cobro anterior de uno posterior; el
  Commit 7 lo cubre con la primera captura tras la migración.
- **Reembolsos de un cobro `outside_ledger`:** el reembolso **se aplica igual** (un hecho de dinero nunca se bloquea por una laguna
  del registro), **no** produce entrada (no hay captura a la que referirse) y deja una auditoría
  (`revenue.refund_outside_ledger`) con el cobro y el importe.
- Una proyección determinista **podría** reconstruir entradas históricas a partir de eventos `APPLIED`; si el propietario lo pide
  algún día, será un commit propio, aprobado, con su prueba de equivalencia. No se hace por defecto.

### 14. PostgreSQL frente a SQLite

- **Las dos bases** ejecutan la migración y las pruebas funcionales: clases cerradas, `CHECK`s, índices únicos parciales (con el
  patrón ya usado, `postgresql_where` / `sqlite_where`) y el trigger append-only (función + trigger en PostgreSQL; `BEFORE UPDATE` /
  `BEFORE DELETE` con `RAISE(ABORT, …)` en SQLite). Una prueba por cada base demuestra que `UPDATE` y `DELETE` fallan.
- **Solo PostgreSQL** prueba lo que exige una base real: carreras entre cobros del mismo pedido (el savepoint), dos workers o un
  reintento y una reentrega a la vez, la exactitud de la aritmética `Numeric(18,4)` y el `TRUNCATE`. Las variantes SQLite de esas pruebas
  se saltan con motivo explícito, como en el Commit 5.
- **La clave foránea compuesta** exige `PRAGMA foreign_keys` en SQLite: el Commit 7 comprobará que está activa en las pruebas; si
  no lo estuviera, esa propiedad se prueba solo en PostgreSQL y SQLite la cubre la comprobación C3 y la prueba de arquitectura.
- RLS: solo en PostgreSQL y solo con política cuando existen los roles `anon`/`authenticated` (Supabase); en SQLite no hace nada
  (patrón de `9f2b6c0a1d47`).
- La migración **no se aplica a Supabase**: ponerla al día sigue siendo una operación aparte (inventario, copia, ensayo local,
  procedimiento y autorización expresa).

### 15. Lo que el registro no contiene, a propósito

- **IVA / OSS, impuestos y obligaciones fiscales**, **facturas**, **comisiones de la pasarela**, **transporte** y cualquier otro
  coste que no se conozca: no se calculan, no se estiman y **no se rellenan con 0** ni con una tasa. Un dato que falta es «Sin
  datos».
- **Conversión de divisas** (§10), caja, cobros bancarios, devengo y reconocimiento (§17).
- **Costes** (§11): son del libro de presupuesto.
- **Datos personales**: el registro no guarda nada de un cliente; solo referencias a entidades que ya tienen su régimen (ADR 0028 §8).

### 16. Invariantes

Las comprueba el Commit 7 (con PostgreSQL real para carreras y bloqueos):

1. **L1. Trazabilidad total.** Toda entrada tiene `payment_event_id` (de un evento `APPLIED`), `payment_id`, `order_id` y, si es
   `REFUND`, `refund_id` y `capture_entry_id`. Ninguna entrada aparece porque un pedido muestre `PAID`.
2. **L2. Identidad e idempotencia.** Una entrada por evento; una `CAPTURE` por cobro; una `REFUND` por reembolso.
3. **L3. Atomicidad.** El estado del cobro y su entrada cambian juntos o no cambian; el evento aplicado y la entrada, igual. No existe
   el estado «aplicado sin entrada» ni «entrada sin evento aplicado»; perder una carrera no deja entradas huérfanas.
4. **L4. Inmutabilidad.** Ninguna entrada se actualiza ni se borra.
5. **L5. Clasificación determinista y heredada.** La clasificación sale del estado del cobro; un `REFUND` hereda la de su captura y los
   totales nunca netean entre clases.
6. **L6. Una moneda, un total.** Ninguna moneda se suma con otra; sin FX; sin `float`.
7. **L7. Reconciliación.** Por cobro, `Σ CAPTURE = captured_amount` y `Σ REFUND = refunded_amount` (salvo `outside_ledger`).
8. **L8. Nada oculto, nada inventado.** Un duplicado, una discrepancia, un `CONFLICT` o un `UNMATCHED` con dinero nunca entran en el
   titular de ingresos **y** nunca desaparecen; un coste desconocido no es 0; un margen no calculable es «Sin datos».
9. **L9. Lo que se lee no escribe ni crea hechos.** Ningún `GET` escribe; el estado visible de un pedido no crea ni cambia entradas.

### 17. Ingreso operativo verificado frente a contabilidad oficial

| | Registro de ingresos verificados (este ADR) | Contabilidad / fiscalidad oficial |
|---|---|---|
| Qué registra | un hecho monetario verificado de pago | el reconocimiento de ingresos y gastos con criterio (devengo, caja), impuestos y obligaciones |
| Momento | cuando el evento de pago se aplica (`occurred_at`) | cuando lo dicta la norma (factura, entrega, cobro) |
| Importe | lo que el proveedor dice que se movió | lo facturado y devengado, con impuestos |
| IVA / OSS | **no** | sí |
| Comisiones del PSP, transporte | **no** | sí |
| Reembolsos | `REFUND` verificado que revierte una captura | abonos y rectificativas |
| Conciliación bancaria | **no** (es el hecho de pago, no el abono en el banco) | sí |
| Corrección | por un nuevo hecho verificado; nunca se edita | asientos de ajuste con su régimen |
| Moneda | la del cobro, por moneda | la de la entidad, con conversión documentada |
| Uso en M45 | números reales y trazables para Dashboard, CFO y Proyectos | **fuera de alcance** |

## Failure modes

| Fallo | Qué pasa | Por qué es seguro |
|---|---|---|
| La entrada no se puede escribir (restricción, base caída a medias) | el evento no se aplica: se deshace todo, el evento sigue `RECEIVED` | L3; reintento programado con tope y visible (ADR 0029) |
| Dos capturas del mismo pedido a la vez | una gana `SUCCEEDED`; la otra pierde el savepoint y se reescribe como `DUPLICATE_CAPTURE` con su entrada `DUPLICATE_RECEIPT` | §7; el registro no tiene huérfanas |
| Un `IntegrityError` del registro dentro del savepoint de `_capture` | **debe subir** y deshacer el evento, no confundirse con la carrera | §7 (requisito del Commit 7, con prueba) |
| El mismo evento se entrega o se reintenta dos veces | una sola entrada | §9, capas 1–5 |
| Un reembolso del proveedor no cabe en lo capturado | `CONFLICT`, sin entrada; visible como evidencia pendiente | D1, L7 |
| Se reembolsa un duplicado | la entrada `REFUND` hereda `DUPLICATE_RECEIPT`; reduce el dinero en revisión, no el ingreso | D2, L5 |
| Alguien actualiza una entrada a mano | el trigger lo rechaza (salvo dueño/superusuario) | §8 |
| Alguien se salta `PaymentService` y mueve dinero | la prueba de arquitectura falla; si ocurriera igualmente, C1/C2 lo detectan | L1, L7 |
| Cobro anterior al registro | `outside_ledger`, informativo; sus reembolsos se aplican y se auditan | §13 |
| Pedido que no está en EUR | el registro lo muestra por su moneda; el margen dice «Sin datos» | §10 |
| Coste desconocido o sin confirmar | margen «Sin datos», no 0 | L8, §11 |
| La reconciliación encuentra una divergencia | se informa con prioridad; nunca se corrige sola | §12 |
| Se revierte el Commit 7 | el estado de pago sigue intacto; solo se pierde la proyección | «Rollback» |

## Alternativas descartadas

- **Ampliar `financial_events` con ingresos.** Es contabilidad de gasto en EUR sin moneda, con clave a `budgets` y unicidad por
  referencia; los ingresos son multimoneda y su identidad es un evento. Rompería el invariante del presupuesto.
- **Calcular los ingresos sumando `payments.captured_amount`** (sin registro). No hay lista de hechos, no hay `occurred_at`, no hay
  clasificación ni procedencia por entrada, y el saldo cambia sin dejar rastro.
- **Un registro con saldos mutables** («ingresos del mes» que se suben y se bajan). Es una segunda fuente de verdad que puede
  divergir; el registro es una proyección inmutable y los totales se calculan.
- **Guardar el coste en el registro.** Mezclaría gasto con ingreso, duplicaría la fuente del gasto y obligaría a inventar la moneda del
  coste (§Contexto 5).
- **Escribir la entrada en un paso posterior** (un trabajo que «proyecte» después). Abre una ventana en la que el estado de pago y el
  registro difieren y obliga a vigilarla; la proyección va en la misma transacción.
- **Un interruptor para apagar el registro.** Apagarlo desincroniza el estado y el libro (viola L3). Se revierte el commit, no se apaga.
- **Entradas para `CONFLICT` y `UNMATCHED`.** Hacen que `Σ entradas ≠ columnas` y mezclan lo explicable con lo que no lo es; se
  muestran como evidencia pendiente, aparte.
- **Netear reembolsos contra el ingreso total.** Un reembolso de un duplicado compensaría un ingreso legítimo y escondería el dinero
  en revisión.
- **Un tipo `REVERSAL` o correcciones manuales.** Una edición por otro nombre; un hecho se compensa con otro hecho verificado.
- **Retrorrelleno por defecto.** No hay datos reales que reconstruir; si algún día hace falta, es un commit propio y aprobado.
- **Convertir todo a EUR «para poder sumar».** Es FX sin tipo ni fecha documentados y contradice la regla del proyecto.

## Consecuencias

- Dashboard, CFO y Proyectos podrán leer **dinero real con procedencia** o decir «Sin datos»; el CFO separará **REAL** (este registro y
  el libro de presupuesto) de **PLAN / DEMO** (escenarios), sin mezclarlos y sin inventar IVA, impuestos, caja ni comisiones.
- `PaymentService` gana tres puntos de escritura (captura, reembolso nuestro, reembolso del proveedor) y una dependencia hacia
  `app/revenue/`. La **prueba de arquitectura** de M44 que fija quién escribe el estado de un cobro se amplía con una que fija quién
  escribe el registro.
- La base gana **una tabla**, **una migración**, **el primer trigger del repositorio** y una función de PostgreSQL.
- **Coste operativo:** una fila por captura o reembolso confirmado; el volumen es el de los eventos de pago, no el de los ticks.
- **El registro no es contabilidad:** quien lo lea como tal se equivoca (§17). La interfaz lo dirá.
- **Relación con los milestones.** *M44* construyó los hechos (eventos, cobros, reembolsos) y la regla «la evidencia financiera nunca se
  descarta»: este registro es su proyección. *M45* lo construye (Commit 7), lo prueba (Commit 8), lo expone con agregados de lectura y
  lo consume en Dashboard, CFO y Proyectos (commits siguientes). *M46 y siguientes* (CFO real, multidivisa, contabilidad y fiscalidad)
  construirán **sobre** este registro, no en su lugar: cualquier ingreso contable o fiscal necesitará su propio ADR.

## Rollback

- **Revertir el Commit 7** con `git revert` (nunca `reset`): el código vuelve a no escribir en el registro. El estado de pago
  (`payments`, `refunds`, `payment_events`) **no cambia** nunca por culpa del registro, así que revertir **no pierde ningún hecho**.
- **Migración:** `downgrade` quita el trigger, la función y la tabla. Es seguro porque el registro es una **proyección**: los hechos
  siguen en `payment_events`, `payments` y `refunds`, y la proyección podría reconstruirse (§13). `downgrade` solo se prueba en local
  y **no** se ejecuta contra Supabase.
- **No hay interruptor de apagado** (§7, alternativas): el único camino es revertir y bajar.
- **Este commit (el ADR)** es solo documentación: revertirlo no afecta a nada que se ejecute.

## Compatibilidad con los ADR existentes

- **ADR 0028:** sin cambios de modelo ni de estados. **Se amplía** con la proyección: `PaymentEvent` sigue inmutable; `PaymentService`
  escribe, en la misma transacción, la entrada correspondiente. La regla «la evidencia financiera nunca se descarta» se mantiene y se
  hace visible (D1).
- **ADR 0023/0026 (libro de presupuesto):** sin cambios. El gasto sigue siendo suyo; el margen es una lectura que combina ambos.
- **ADR 0024:** sin cambios. El registro no interviene en el ciclo de las acciones externas ni en `UNKNOWN_OUTCOME`.
- **ADR 0029:** sin cambios de máquina de estados. Un evento `RECEIVED` cuya entrada no se pueda escribir sigue su ciclo (reintentos,
  tope de 5, visible); la reconciliación del registro (§12) vive en `reconcile.report`.
- **ADR 0003:** la tabla nueva nace con RLS y sin acceso público.

## Qué no resuelve este ADR

Contabilidad, facturación, IVA/OSS, comisiones, conciliación bancaria y reconocimiento contable o fiscal (§17); conversión de divisas
y márgenes fuera de EUR; la **moneda del gasto** y la inconsistencia previa del fulfillment en pedidos que no son EUR (deuda
registrada); cualquier retrorrelleno de datos históricos; el CFO completo (M46); aplicar la migración a Supabase (operación aparte);
cualquier proveedor, pasarela o transportista real.

## Criterios de aceptación del Commit 7

El Commit 7 (`feat: verified revenue ledger`) se acepta solo si:

1. **Migración** con `down_revision = d7e2a9c4f1b8`: crea `revenue_ledger_entries` con todas las columnas, `CHECK`s, índices únicos
   parciales, la clave foránea compuesta de herencia, RLS y el trigger append-only (PostgreSQL y SQLite); `downgrade` lo deshace;
   se prueba `upgrade → downgrade → upgrade` en PostgreSQL local **con datos** y en el CI, y **no se aplica a Supabase**.
2. **Módulo `app/revenue/`** con una sola vía de escritura, llamada solo desde `PaymentService` en los tres puntos de §7, y la
   **prueba de arquitectura** que lo hace cumplir (quién escribe la tabla y quién llama al módulo; sin `float`).
3. **Atomicidad probada:** una carrera real de dos capturas del mismo pedido (PostgreSQL, hilos con barrera) deja exactamente una
   `ORDER_PAYMENT` y una `DUPLICATE_RECEIPT`, **sin entradas huérfanas** y con `Σ = captured_amount`; un fallo al escribir la entrada
   deja el evento `RECEIVED` y el cobro intacto; **un `IntegrityError` del registro dentro del savepoint sube** y no se confunde con la
   carrera.
4. **Casos de §4 cubiertos**, uno por uno: captura normal, `DUPLICATE_CAPTURE`, `CAPTURE_MISMATCH`, `CONFLICT` y `UNMATCHED` (sin
   entrada), `STALE`, `RECEIVED`, captura tardía sobre un pedido cancelado, reembolso nuestro, reembolso del proveedor, reembolso
   fallido (sin entrada), reembolso de un duplicado (hereda `DUPLICATE_RECEIPT`) y reembolso de una discrepancia.
5. **Identidad e idempotencia:** el mismo evento entregado dos veces, reintentado y reconciliado a la vez produce una sola entrada; una
   segunda entrada para el mismo evento, cobro o reembolso la rechaza la base.
6. **Inmutabilidad:** `UPDATE` y `DELETE` fallan en SQLite y en PostgreSQL (y `TRUNCATE` en PostgreSQL).
7. **Herencia:** un `REFUND` con clasificación, moneda o cobro distintos de los de su captura lo rechaza la base (PostgreSQL; SQLite si
   las claves foráneas están activas, §14).
8. **Reconciliación:** `reconcile.report` informa C1–C4 y `outside_ledger` sin escribir nada; una divergencia provocada se detecta;
   un cobro anterior al registro se lista como `outside_ledger` y su reembolso se aplica y se audita.
9. **Evidencia pendiente:** los eventos `CONFLICT`/`UNMATCHED` con importe son consultables por moneda con su nota y su edad, sin
   alterar el evento.
10. **Sin regresión:** `python -m pytest` y `pytest` completos contra PostgreSQL local, `ruff`, `mypy` y las mutaciones del registro
    (romper la herencia, la idempotencia, el savepoint, la inmutabilidad y la reconciliación; deben detectarse), sin tocar los ficheros
    protegidos del propietario y con Supabase intacta.
11. **Sin alcance extra:** ni agregados `GET`, ni cambios de frontend, ni margen: eso son los commits siguientes.

## Qué no fue el Commit 6 (el ADR)

Fue **solo documentación**: ni tabla, ni migración, ni código, ni ruta, ni cambio de frontend. Los nombres `revenue_ledger_entries`,
`app/revenue/`, `ORDER_PAYMENT`, `DUPLICATE_RECEIPT`, `MISMATCH_RECEIPT` y `outside_ledger` los decidió para que el Commit 7 los creara.

## Qué se implementó (Commit 7 de M45)

- **Modelo y migración.** `app/db/models/revenue.py` (`RevenueLedgerEntry`) y la migración `c4e8b1d9a273` (`down_revision = d7e2a9c4f1b8`):
  todas las columnas, `CHECK`s, índices únicos parciales, la clave ajena compuesta de herencia, RLS (ADR 0003) y el trigger append-only
  (PostgreSQL: función y dos triggers, `TRUNCATE` incluido; SQLite: un trigger por operación). El texto del trigger es el mismo en el
  modelo (`after_create`, para las bases de las pruebas) y en la migración, y una prueba comprueba que no se separan. Sin retrorrelleno.
- **Escritura.** `app/revenue/ledger.py` (`RevenueLedger`) es la única vía; solo la llama `PaymentService`, en `_record_capture`,
  `_refund_succeeded` y `_provider_refund` (§7). Un `IntegrityError` del registro se convierte en `RevenueLedgerWriteError`, que no es un
  `IntegrityError` y sube hasta deshacer el evento. Además `_capture` ya no continúa a «pedido cobrado» si el `IntegrityError` no es la
  carrera del índice (nunca había una captura registrada en ese caso). Un reembolso de un cobro sin captura en el registro
  (`outside_ledger`) se aplica y deja la auditoría `revenue.refund_outside_ledger`, sin entrada.
- **Lectura.** `app/revenue/check.py` (C1–C4 y `outside_ledger`, §12 y §13) y `app/revenue/evidence.py` (evidencia pendiente, §4), solo
  `SELECT`. Aparecen en `GET /api/reconciliation/status` (bloque `revenue`, sin cuerpos ni hashes) y en el resultado del trabajo
  `reconcile.report` (contadores). Ninguna ruta nueva ni cambio de frontend.
- **Pruebas.** Servicio (SQLite y PostgreSQL), carreras reales en PostgreSQL, reconciliación, migración (SQLite y PostgreSQL), herencia
  con claves ajenas activas en SQLite, pruebas de arquitectura (quién escribe el registro, quién llama a su escritor, lecturas que no
  escriben, sin `float`, sin depender del estado visible del pedido) y mutaciones.
- **Precisiones de implementación** (no cambian ninguna decisión de este ADR):
  1. La evidencia pendiente cuenta solo eventos `CONFLICT` o `UNMATCHED` de los tipos que mueven dinero (`payment.succeeded` y
     `refund.succeeded`) **con importe**: un `payment.failed` o un `refund.failed` con importe no es dinero recibido ni devuelto.
  2. `currency` es `varchar(3)` y además lleva `CHECK (length(currency) = 3)`: una moneda de más de tres letras la rechaza el tipo y una
     de menos la rechaza el `CHECK`.
  3. La reconciliación compara importes a la precisión de la columna (`round(…, 4)`), porque SQLite suma en coma flotante.
  4. `outside_ledger` se decide por el instante en que se aplicó el evento de captura frente a la primera entrada del registro, tal como
     describe §13, con su limitación declarada (registro vacío).
