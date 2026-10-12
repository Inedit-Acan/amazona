# ADR 0031: Procedencia estructurada del dinero — dos ejes (evidencia y origen operativo), persistidos como propiedad del hecho

- **Estado:** Aceptada (decisiones del propietario del 2026-10-12, con una segunda ronda el mismo día que retira toda inferencia por nombre: §6 y §18). **Implementada en parte**: el Commit 2A de M46 implementa el origen en el cobro, el evento y el registro, y el emparejado (ver el **addendum, §21**); el Commit 1 de M46 (este ADR) fue solo documentación. El Commit 2B añade `check_ledger` C5/C6, la guarda arquitectónica contra la inferencia, el caos y las mutaciones (**addendum, §22**). Faltan la API, la interfaz y el cierre (§20).
- **Fecha:** 2026-10-12
- **Depende de:** [ADR 0003](adr-0003-rls-deny-by-default.md), [ADR 0026](adr-0026-database-identity-guards.md), [ADR 0028](adr-0028-orders-payments-fulfilment-core.md), [ADR 0029](adr-0029-scheduled-reconciliation-and-unknown-outcome-authority.md), [ADR 0030](adr-0030-verified-revenue-ledger.md)
- **Enmienda a:** [ADR 0030](adr-0030-verified-revenue-ledger.md) (el registro hoy «no distingue de forma estructural una operación simulada de una que no lo sea»: deja de ser cierto) y [ADR 0028](adr-0028-orders-payments-fulfilment-core.md) (el alcance de `Order.is_simulated`, §12)
- **Milestone:** 46 (cierra P1-2: la procedencia estructurada del dinero)
- **Nombre:** *Structured Money Provenance* / **Procedencia estructurada del dinero**

> **Qué NO es.** Este ADR **no afirma que ningún dinero del sistema sea real**: hoy no existe ningún proveedor de pago que no sea simulado.
> Tampoco convierte «verificado» en «real», «liquidado», «contabilizado» ni «fiscal». Y no añade ningún proveedor, cuenta, credencial ni gasto.
> Define **cómo se guarda y se enseña de dónde viene un hecho financiero** para que, el día que exista otro origen, ninguna pantalla pueda
> confundirlo con el simulado ni al revés.
>
> **La regla de fondo:** el origen es un **dato estructurado y persistido**, capturado en el momento del hecho desde el registro de
> proveedores. **Nunca se infiere** por una convención de nombres, por `Order.is_simulated`, por el entorno, por la ausencia de `mock`
> ni por una configuración posterior.

## Contexto

Comprobado contra el código el 2026-10-12 (`HEAD 36a9f3f`, Alembic `e5a1d7c93b04`, 43 revisiones). Cada afirmación nombra su fuente.

1. **`Order.is_simulated` mide el despliegue, no el dinero.** Se fija al crear el pedido con `Settings.operating_in_simulation`
   (`orders/service.py:71`), que es verdadero solo si el entorno no es `staging`/`production` **y los nueve tipos de proveedor**
   (siete dominios, FX y ley nacional) son `MOCK` (`core/config.py:243-261`). Un `CHECK` lo ata al prefijo `sim_` de `customer_ref`
   (`db/models/order.py:40-44`). Si mañana otro dominio (por ejemplo inteligencia de producto) pasa a `REAL` y los pagos siguen en `MOCK`,
   los pedidos nuevos saldrían `is_simulated = false` con dinero **íntegramente simulado**.
2. **El resto de la cadena solo guarda el nombre del proveedor.** `Payment.provider` (`orders/payment_attempts.py:126`, `provider.name`),
   `Refund.provider` (`orders/refunds.py:140`) y `PaymentEvent.provider` (`payments/ingress.py`, `_record`) son cadenas. Ninguna lleva un tipo.
   `RevenueLedgerEntry` (`db/models/revenue.py`) **no lleva ninguna columna de procedencia** y `payments/` y `revenue/` no consultan
   `operating_in_simulation` (búsqueda: 0 aciertos).
3. **El registro de proveedores de pago solo admite `MOCK`.** `IMPLEMENTATIONS[PAYMENTS] = {ProviderKind.MOCK: SimulatedPaymentProvider}`
   (`integrations/registry.py:202`); pedir otro tipo lanza `ProviderNotAvailableError` («en vez de caer al simulado en silencio»). Hoy
   **todo cobro es simulado por construcción**.
4. **El tipo ya existe como vocabulario estructurado.** `ProviderKind = MOCK | SANDBOX | REAL | COMPOSITE` (`integrations/ports.py:50`), con la
   distinción explícita de que `SANDBOX` es «forma real, datos irreales». El **tipo con el que se resuelve un adaptador es la clave** de
   `IMPLEMENTATIONS[dominio]`, no una propiedad de su nombre. `Settings.payments_provider` es un `ProviderKind` (`core/config.py:167`).
5. **`ProviderBinding.is_simulated` colapsa `SANDBOX` en «no simulado»** (`registry.py:64-71`: `kind in (MOCK, COMPOSITE)`), y se expone en
   `/api/status` como `simulated` (`main.py:231`). Un booleano «simulado / no simulado» es el vocabulario equivocado para el dinero (§12).
   Además `ProviderBinding.name` es `factory.__name__` (el nombre de la **clase**), no el `name` del adaptador que se guarda en
   `Payment.provider` (`"simulated-payments"`).
6. **El emparejamiento hoy compara nombres, no tipos.** `_find_payment` filtra `Payment.provider == event.provider`
   (`payments/service.py:173-190`), `_find_refund` hace lo mismo (`:156-171`) y un evento sin cobro es `UNMATCHED` (`:126`). El reembolso
   iniciado por nosotros exige `payment.provider == provider.name` (`orders/refunds.py:194-200`) y el del proveedor se crea con
   `provider=event.provider` (`payments/service.py:410`). `Refund.payment_id` es `NOT NULL` con clave ajena (`db/models/payment.py:200`).
7. **`PaymentIngress` no conoce el tipo.** `receive` resuelve el adaptador con `_provider_for` (`payments/ingress.py:82,97`) y comprueba solo
   que `candidate.name == name`; admite además un adaptador **inyectado** sin registro (`provider=`: `cli.py:310,357` y las pruebas). Ni el
   evento que guarda `_record` ni el adaptador llevan hoy un tipo.
8. **Los agregados mezclan todo.** `summary()` agrupa por `(moneda, clasificación, tipo)` (`revenue/aggregates.py:130`), el bloque
   `consolidated_eur` suma todas las entradas en EUR (`:190`) y `pending_evidence_totals` agrupa por `(moneda, tipo de evento)` sin
   proveedor ni origen (`revenue/evidence.py:55`). Mientras solo exista `MOCK` es inocuo; con un segundo origen sería una mentira.
9. **El frontend tiene el eje de evidencia pero no el de origen.** `Provenance = verified | declared | planned | demo`
   (`lib/provenance.ts`); `verified` se enseña como «Registro verificado». `app/operations/operations-panels.tsx:363` pinta
   `order.is_simulated ? "Simulado" : "Real"`, y `lib/cfo-margin.ts:173-180` copia `order.is_simulated` a cada fila de pedido.
   Una prueba, `lib/dashboard-revenue-boundary.test.ts:121-150`, **falla a propósito** en cuanto los tipos del registro traigan una
   procedencia estructurada, para forzar una decisión consciente: este ADR es esa decisión.
10. **`check_ledger` compara el registro con el cobro** (C1–C4, `revenue/check.py`) y no sabe nada de procedencia.
11. **Supabase no tiene estas tablas.** Su `alembic_version` es `e1b8d4a62f37` y le faltan 6 revisiones; no existen `payments`, `payment_events`
    ni `revenue_ledger_entries` allí (verificado el 2026-10-12, solo lectura). No hay nada que rellenar en esa base.

## Decisión

### 1. Dos ejes ortogonales, no una enumeración de cinco valores (D1)

| Eje | Valores | Qué responde | Dónde vive |
|---|---|---|---|
| **Evidencia** | `verified` · `declared` · `planned` · `demo` | *¿Qué tan firme es este dato y quién lo respalda?* | Ya existe en el frontend (`lib/provenance.ts`); `verified` solo lo es lo que sale del registro |
| **Origen operativo** | `mock` · `sandbox` · `real` | *¿Qué clase de proveedor movió (o simuló mover) este dinero?* | **Nuevo, persistido** en `payments`, `payment_events` y `revenue_ledger_entries` (§4–§7) |

El origen **solo existe para hechos monetarios verificados**. `declared`, `planned` y `demo` **no tienen origen**: no se les pone `mock` ni `real`,
se les pone «no aplica». Los cinco estados del encargo son combinaciones, no valores almacenados:

| Combinación | Se lee |
|---|---|
| `verified` + `mock` | verificado, simulado |
| `verified` + `sandbox` | verificado, entorno de pruebas del proveedor |
| `verified` + `real` | verificado, proveedor real (**sin** afirmar nada comercial; §3) |
| `declared` / `planned` / `demo` | sin origen de dinero |

**No se usa un booleano `simulated` para la procedencia financiera.** Un booleano pierde la distinción `sandbox` y es exactamente el error del punto 5.

### 2. Semántica exacta de `mock`, `sandbox` y `real` (D1)

- **`mock`** — el proveedor fue un **simulador determinista nuestro** (hoy `SimulatedPaymentProvider`): no habla con nadie, no mueve ni puede mover dinero. Un hecho `verified + mock` significa que el backend **verificó la firma de un evento simulado** (la clave de firma es efímera del proceso) y lo aplicó con las mismas reglas que a uno real.
- **`sandbox`** — el **entorno de pruebas de un proveedor real** (API real, credenciales de prueba). Ningún dinero real se mueve. No lo simulamos nosotros, pero tampoco es dinero.
- **`real`** — el **entorno de producción del proveedor**. El proveedor dice que se movió dinero. Sigue sin ser contabilidad ni liquidación (§3).
- **`mock` ≠ `sandbox` ≠ `real`.** Ningún valor implica otro. **«No simulado» no significa «real»**: puede ser `sandbox`. Y «no es `mock`» no es una prueba de nada.
- **`composite` no es un origen de pagos.** `ProviderKind.COMPOSITE` puede rellenar con fixtures; no existe ni se admite para pagos. El `CHECK` solo acepta `mock`, `sandbox`, `real`.
- **No existe un valor `unknown` almacenado.** Todo hecho persistido tiene origen (`NOT NULL`). Lo desconocido solo existe como **ausencia del campo en una respuesta** (§9) y nunca se rellena.

### 3. Qué significa y qué NO significa `verified` (D1)

`verified` significa que el hecho entró por la **única puerta** (`PaymentIngress.receive`), con la firma comprobada por `verify_webhook`; que lo aplicó `PaymentService`; que el registro lo escribió **en la misma transacción**; y que la reconciliación (`check_ledger`, ADR 0030) lo cuadra con el cobro.

`verified` **no** significa: que el dinero sea **real** (un hecho `verified + mock` es correcto y simulado); que esté **liquidado** o en una cuenta bancaria; que no vaya a haber **contracargo**; que esté **contabilizado**, facturado o con IVA/OSS; ni que el proveedor **diga la verdad** más allá de la firma. Tampoco significa nada por estar en PostgreSQL, en el registro, haber pasado por un webhook o haberlo escrito el backend: **ninguna de esas cosas es una prueba de origen.**

### 4. Fuente canónica de `provider_kind` (D5, requisito arquitectónico)

El origen es una **propiedad persistida del hecho**, escrita **una vez**, en el momento en que el hecho nace, desde el **registro de proveedores**:

> `provider_kind` = el `ProviderKind` **con el que `ProviderRegistry` resolvió el adaptador de pagos**, es decir, la **clave** de `IMPLEMENTATIONS[PAYMENTS]` bajo la que se instanció.

- **Una sola resolución produce el par (adaptador, tipo).** Quien persiste un hecho (el alta del cobro, la recepción del evento) toma el tipo **de la misma resolución** que el adaptador que usa, no de una segunda lectura de `Settings`.
- **Un adaptador sin tipo estructurado no es utilizable.** Un adaptador que llegue sin tipo (por ejemplo, **inyectado** sin pasar por el registro) hace que el hecho **se rechace o quede sin aplicar**; **nunca se infiere por nombre**.
- **No existe ni se admite** una función «nombre de proveedor → tipo», ni una convención de nombres que identifique el tipo. Un mismo adaptador puede registrarse bajo `sandbox` y bajo `real` sin cambiar de nombre: el tipo es la clave del registro, no una propiedad del nombre.
- **No puede salir de:** el entorno; `Settings.operating_in_simulation`; `Order.is_simulated`; `ProviderBinding.is_simulated`; el prefijo de `customer_ref`; `ProviderBinding.name` ni `Payment.provider`; la petición (cuerpo, cabeceras, parámetros); la pantalla; ni una configuración **posterior** al hecho.
- **Capturar la configuración en el momento del hecho no es inferir después:** el tipo se lee de la resolución vigente **cuando el hecho ocurre** y se guarda; a partir de ahí es un dato del hecho, y cambiar la configuración no lo toca (§13 F1).
- **Condición para cualquier adaptador futuro no simulado:** debe verificar las firmas **solo con las credenciales del tipo configurado** (un evento de `sandbox` no puede verificarse en un despliegue `real`, ni al revés). Es un requisito del adaptador, no de este ADR.

### 5. Flujo del origen (D4)

```
ProviderRegistry  — una resolución: adaptador + ProviderKind estructurado
   │
   ├─ alta del cobro ────────────► Payment.provider_kind          (inmutable)
   │
   └─ PaymentIngress.receive ────► PaymentEvent.provider_kind     (se captura ANTES de emparejar;
         │                          inmutable; conservado también si el evento queda UNMATCHED)
         ▼  el emparejamiento exige el mismo (proveedor, tipo)
   Payment ◄── Refund: SIN columna nueva; payment_id NOT NULL → su origen es el de su cobro, por clave ajena
         │
         ▼  se COPIA al escribir la entrada (captura: del cobro; reembolso: de la captura, que es del mismo cobro)
   RevenueLedgerEntry.provider_kind                              (inmutable: el registro es append-only)
         │
         ▼
   API /api/revenue/*  (cada fila y cada agregado llevan su origen; §10)
         │
         ▼
   Dashboard / Finanzas / Proyectos  (muestran el origen; nunca «Real» por inferencia; §11)
```

### 6. `PaymentEvent`, `UNMATCHED` y `Refund` (D7 enmendada)

- **`payment_events.provider_kind` es una columna explícita** (`mock | sandbox | real`, `NOT NULL`). Se captura en **`PaymentIngress.receive`**, desde la misma resolución del registro que da el adaptador, **antes** de intentar emparejar el evento con un `Payment`.
- **Un evento `UNMATCHED` conserva su `provider_kind`.** No necesita `payment_id` para conocer su procedencia, y esa procedencia **no se infiere nunca** desde `ProviderBinding.name` ni `Payment.provider`.
- **El emparejamiento exige el mismo tipo.** Además del proveedor, `_find_payment` y `_find_refund` exigen `provider_kind` igual. Si el único candidato difiere en el tipo, el evento no se aplica: es `CONFLICT` (se conserva como evidencia y **jamás** llega al registro).
- **Limitación (la única que se admite):** *un evento cuyo adaptador no tenga `provider_kind` estructurado debe rechazarse o quedar sin aplicar; nunca se infiere por nombre.* Esto incluye el adaptador inyectado sin registro: el llamador (la consola, las pruebas) debe aportar el tipo de forma explícita o el evento se rechaza.
- **`Refund` no lleva columna `provider_kind`** (D4/D7). Comprobado contra el modelo: `Refund.payment_id` es `NOT NULL` con clave ajena (`db/models/payment.py:200`), así que **no existe un reembolso sin cobro**, y su origen es el del cobro **por una clave ajena persistida, no por el nombre**. Su entrada del registro lleva el origen de su captura (mismo `payment_id`; §7). Un reembolso iniciado por el proveedor nace de un evento ya emparejado con ese cobro (mismo proveedor **y mismo tipo**), y uno iniciado por nosotros exige que el cobro sea del proveedor resuelto (`orders/refunds.py:199`), que el Commit 2 amplía al tipo. No hay nada de la procedencia de un reembolso que no quede garantizado sin duplicar la columna.
- **Cláusula de parada (D4):** si en la implementación se descubre que la procedencia de un reembolso no puede garantizarse sin su propia columna, **se detiene el trabajo y se presenta la evidencia al propietario antes de cambiar el diseño.**

### 7. Inmutabilidad y garantías de base de datos (D4)

- `Payment.provider_kind` y `PaymentEvent.provider_kind` **no tienen ningún camino de escritura posterior al alta**: el servicio no los actualiza y la base de datos **rechaza un `UPDATE` de esas columnas** (disparador en PostgreSQL y SQLite; mecanismo exacto a fijar en el Commit 2). El `PaymentEvent` ya es «inmutable salvo su estado de proceso» (ADR 0028): el origen entra en la parte inmutable.
- `RevenueLedgerEntry.provider_kind` es inmutable porque **todo el registro** lo es (disparador *append-only* ya vigente).
- **El origen no puede divergir entre `Payment`, `PaymentEvent` y `RevenueLedgerEntry`**, y no por convención sino por claves ajenas compuestas (el patrón que ya usa `fk_revenue_entries_refund_inherits_capture`), apoyadas en `UNIQUE (id, provider_kind)` en `payments` y en `payment_events`:
  - `payment_events (payment_id, provider_kind) → payments (id, provider_kind)`. Un evento `UNMATCHED` tiene `payment_id` nulo: la restricción no se evalúa y el evento conserva su propio tipo.
  - `revenue_ledger_entries (payment_id, provider_kind) → payments (id, provider_kind)`.
  - `revenue_ledger_entries (payment_event_id, provider_kind) → payment_events (id, provider_kind)`.
  - Así, toda entrada —de captura **o de reembolso**— tiene el origen de su cobro y el de su evento. Esto añade restricciones, **no columnas duplicadas en `refunds`**.
- El mecanismo exacto (disparadores, forma de las claves compuestas en SQLite) se fija en el Commit 2 con pruebas y mutaciones; si no pudiera sostenerse la garantía, se aplica la cláusula de parada de §6.

### 8. Relleno histórico (D3)

Una migración (la **44.ª**, `down_revision = e5a1d7c93b04`) añade `provider_kind` a `payments`, `payment_events` y `revenue_ledger_entries`:

1. añade la columna con un `DEFAULT 'mock'` **temporal** (un `ADD COLUMN` con constante no debería reescribir ni disparar los disparadores de fila, que es lo que permitiría tocar una tabla *append-only*; **el Commit 2 lo demuestra con una prueba** en PostgreSQL y SQLite antes de apoyarse en ello);
2. las filas históricas quedan en `mock`;
3. comprueba que no queda ninguna nula (`NOT NULL`);
4. **retira el `DEFAULT`**, y añade el `CHECK (provider_kind IN ('mock','sandbox','real'))`, las restricciones únicas, las claves ajenas compuestas y los disparadores de §7.

**Por qué `mock` es verdad y no una suposición:** el registro de pagos solo admite `MOCK` (punto 3), y un evento solo se guarda tras verificarlo el adaptador resuelto por ese registro. Ninguna fila anterior pudo nacer de otro origen. Este relleno es **el único sitio** donde se asigna un origen sin haberlo capturado en el momento del hecho, y no se repite jamás.

- **La migración lleva una prueba que demuestra la premisa:** el registro de pagos contiene exactamente `{MOCK}` y cada otro tipo lanza `ProviderNotAvailableError`. Si algún día se añade un adaptador no simulado, esa prueba falla y obliga a revisar el relleno antes de seguir.
- **Y una guarda en la propia migración:** se **niega** a ejecutarse si existe algún cobro o evento cuyo `proveedor` no sea el del simulador. Esa comparación **no clasifica nada**: solo impide rellenar con `mock` datos que no se puede demostrar que lo sean.

**El esquema final no tiene `DEFAULT`** ni en la base ni en el modelo: una operación nueva **debe declarar su origen explícitamente**; una inserción sin él falla (`NOT NULL`). Una prueba lo comprueba inspeccionando el esquema.

`downgrade` quita las columnas **y se niega si existe alguna fila con origen distinto de `mock`** (perdería información que no se puede reconstruir).

### 9. Procedencia desconocida

- En la base de datos **nunca** es desconocida (`NOT NULL`, sin `DEFAULT`): no hay origen derivado ni «cubo desconocido» de eventos.
- Un valor de origen **no reconocido** (ni `mock`, ni `sandbox`, ni `real`) es un error de validación; no se almacena ni se rellena.
- En el frontend el origen es `Origen | null` y el tipo obliga a tratar el `null`: una respuesta que no traiga el campo (una API antigua, un error de lectura) se enseña como «Sin datos de origen», **nunca** como `mock`, `sandbox` ni `real`.
- **D10 (`finance_validation`):** la moneda solo se muestra si existe **explícitamente** en los datos fuente; sin fuente, `null` / «Sin datos». No se asume EUR ni se crea un valor por defecto. *(Pendiente de comprobar en el Commit 7 si el dato existe; este ADR no lo asume.)*

### 10. Reglas de agregación (D2)

- **A1.** Los hechos `verified` de orígenes distintos **no se mezclan** en ningún total de «ingresos». Cada agregado de dinero lleva su `provider_kind` y su moneda: la clave es `(origen, moneda, clasificación, tipo)`.
- **A2.** Un agregado **transversal** (todos los orígenes) solo puede existir si va **etiquetado explícitamente como agregado de registros** (nombre indicativo: `all_origins_records`) y **jamás** como «ingresos», «ingresos verificados», «ingresos reales» ni equivalente. **Ninguna cifra de cabecera de pantalla usa un agregado transversal.**
- **A3.** El bloque actual `consolidated_eur` (que suma todas las entradas en EUR) **se parte por origen o se renombra** según A2 (Commit 3). `non_aggregable_currencies` sigue igual.
- **A4.** `pending_evidence` se separa por el `provider_kind` **persistido** de cada evento (también el de los `UNMATCHED` y `CONFLICT`), no por el nombre del proveedor.
- **A5.** Σ por origen = total de registros (prueba de propiedad).
- **A6.** El margen de un pedido no cruza orígenes: el ingreso verificado de una fila de margen tiene **un** origen (el de sus entradas), y el margen resultante lo hereda; no el de `Order.is_simulated`.
- Los nombres de campo de este apartado son **indicativos**; se fijan en el Commit 3 junto con los tipos de la API.

### 11. Regla de interfaz: nunca «Real» por inferencia (D5)

- **Prohibido** derivar o pintar «Real», «Dinero real», «Ingreso real», «Cobro real» o equivalente a partir de `Order.is_simulated == false`, de `ProviderBinding.is_simulated`, de la ausencia de la palabra «simulado» o de `mock`, del entorno o del nombre de un proveedor.
- Una etiqueta de origen describe **al proveedor**, no afirma nada del dinero: nombres indicativos —`mock` → «Simulado», `sandbox` → «Entorno de pruebas», `real` → «Proveedor real, sin confirmar comercialmente»—; el texto final se fija en el Commit 4.
- Todo importe del registro enseña su origen junto a la etiqueta «Registro verificado». Una cifra `verified + mock` **no se presenta nunca como ingreso**: se presenta como «verificada, simulada».
- El tipo `Verified<T>` del frontend **pasa a llevar el origen**; sumar o restar cifras de orígenes distintos **no compila**, igual que hoy no compila mezclar evidencias.
- `operations-panels.tsx:363` deja de usar `is_simulated` para la etiqueta de dinero; la prueba `dashboard-revenue-boundary.test.ts:121-150` se **actualiza conscientemente** en el Commit 4 (su propio mensaje lo pide) y se añade una prueba que prohíba la palabra «Real» como etiqueta derivada.

### 12. Compatibilidad: `Order.is_simulated` y `ProviderBinding.is_simulated` (D5)

**`Order.is_simulated` se mantiene**, con el `CHECK` del prefijo `sim_` y su significado actual, ahora documentado: **«el despliegue era una simulación cuando se creó el pedido»**. Es **contexto histórico y de despliegue del pedido**, no procedencia del dinero.

- Puede mostrarse como «Pedido creado en simulación».
- **No puede** usarse para clasificar `Payment`, `PaymentEvent`, `Refund` ni `RevenueLedgerEntry` como `mock`, `sandbox` ni `real`, ni para ninguna etiqueta, agregado o decisión sobre el origen del dinero.
- Un pedido sin cobro verificado no tiene origen de dinero: «Sin cobro».

**`ProviderBinding.is_simulated` no es equivalente de procedencia.** Hoy devuelve `kind in (MOCK, COMPOSITE)`: colapsa `SANDBOX` (y `REAL`) en «no simulado». Es **deuda de compatibilidad** y el **Commit 2 debe dejar de usarla** en cualquier camino de pedidos, pagos o registro de ingresos, y lo hace cumplir con una prueba que prohíbe su uso en esos módulos. Su renombrado o retirada, y la clave `simulated` de `/api/status` (`main.py:231`, que ya expone también `kind`), se tratan en el Commit 2/3; hasta entonces **no se interpreta como procedencia**.

### 13. Modos de fallo

| # | Fallo | Qué ocurre |
|---|---|---|
| F1 | Cambia `payments_provider` después de crear cobros o recibir eventos | Los hechos existentes conservan su origen (persistido). Prueba de caos. |
| F2 | El tipo configurado no tiene adaptador | `ProviderNotAvailableError`: no se crea el cobro ni se recibe el evento. Sin degradación a `mock`. |
| F3 | Un adaptador llega sin tipo estructurado (inyectado sin registro) | El evento se **rechaza** o queda sin aplicar. **Nunca** se infiere por nombre. |
| F4 | Un evento llega con un tipo distinto del del cobro candidato | `CONFLICT`, conservado como evidencia, nunca al registro. |
| F5 | La entrada del registro llevaría un origen distinto del de su cobro o su evento | La clave ajena compuesta lo rechaza → `RevenueLedgerWriteError` → el evento sigue `RECEIVED` (ciclo de la ADR 0029). |
| F6 | Código antiguo inserta un cobro o un evento sin origen contra el esquema nuevo | Falla (`NOT NULL`, sin `DEFAULT`): **ruidoso a propósito**, nunca un `mock` silencioso. |
| F7 | Reembolso de un cobro por un proveedor de otro tipo | Rechazado (`ConflictError`, hoy por proveedor; el Commit 2 lo amplía al tipo). |
| F8 | Evento `UNMATCHED` | Conserva su `provider_kind` persistido y se agrega con él; no se sustituye por otro. |
| F9 | La API no trae el campo de origen | La UI muestra «Sin datos de origen». |
| F10 | `downgrade` con filas no `mock` | Se niega. |
| F11 | Un evento de otro entorno del proveedor llega a este despliegue | Falla la verificación de firma (condición del adaptador, §4) y no se guarda. |
| F12 | Las unicidades `(proveedor, referencia)` no incluyen el tipo (`uq_payments_provider_payment_ref`, `uq_payment_events_provider_event`, `uq_refunds_provider_refund_ref`, `db/models/payment.py:63,128,186`) | Con un mismo adaptador en dos orígenes y una referencia repetida, un hecho bloquearía al otro. Hoy es inalcanzable (solo existe `mock`). El Commit 2 decide con evidencia si el cobro y el evento incluyen el tipo en su clave; si el reembolso lo exigiera, rige la cláusula de parada de §6 (no se añade la columna sin presentar la evidencia). |

### 14. Retroceso

- Cada commit de M46 se revierte con `git revert` sin tocar los demás; el ADR no tiene efectos en tiempo de ejecución.
- La migración del Commit 2 tiene `downgrade` con la guarda de F10 sobre las **tres** tablas. Mientras todas las filas sean `mock` (el estado de hoy), sube y baja sin pérdida.
- **Supabase no se toca en ningún retroceso**: no se le ha aplicado nada (§17).

### 15. Invariantes

**De base de datos**

- **DB1** `payments`, `payment_events` y `revenue_ledger_entries` tienen `provider_kind` `NOT NULL`, **sin `DEFAULT`**, con `CHECK` sobre `mock|sandbox|real`.
- **DB2** `payments.provider_kind` y `payment_events.provider_kind` no se pueden actualizar; el registro no se puede actualizar ni borrar.
- **DB3** Un `PaymentEvent` con `payment_id` tiene el origen de su `Payment` (clave ajena compuesta). Un `UNMATCHED` conserva el suyo.
- **DB4** Toda `RevenueLedgerEntry` tiene el origen de su `Payment` y de su `PaymentEvent`; una entrada de reembolso, por la misma vía, el de la captura que devuelve.
- **DB5** `UNIQUE (id, provider_kind)` en `payments` y en `payment_events` sostiene DB3 y DB4.

**De aplicación**

1. Todo `Payment` tiene `provider_kind`, tomado de la resolución del registro, nunca de `Settings`, del entorno, de `Order.is_simulated`, del `customer_ref`, del nombre ni de la petición.
2. Todo `PaymentEvent` que pueda registrarse tiene `provider_kind`, capturado en `PaymentIngress` **antes** de emparejarlo.
3. Un evento `UNMATCHED` conserva `provider_kind`.
4. Toda `RevenueLedgerEntry` copia estructuradamente el origen del hecho económico que la causa.
5. Un `Refund` conserva la procedencia de la captura que devuelve (por `payment_id` y por la clave ajena de la entrada).
6. Un adaptador sin `provider_kind` estructurado no recibe ni aplica eventos; nunca se infiere por nombre.
7. Un evento de tipo distinto del del cobro es `CONFLICT`.
8. `check_ledger` añade **C5** (toda entrada tiene el origen de su cobro) y **C6** (todo evento asociado tiene el origen de su cobro); una divergencia se informa, nunca se arregla sola.
9. Ningún agregado mezcla `provider_kind` distintos sin exponerlos por separado (A1–A6).
10. Una procedencia ausente (UNKNOWN) nunca se convierte en `mock`, `sandbox` ni `real` (§9).
11. Ninguna UI usa «Real» basándose en `Order.is_simulated` ni en `ProviderBinding.is_simulated` (§11–§12).
12. Cambiar la configuración después no modifica ningún hecho histórico.
13. `ProviderBinding.is_simulated` no aparece en `orders/`, `payments/` ni `revenue/`.

### 16. Plan de pruebas y de mutaciones

**Pruebas** (PostgreSQL **local** desechable; nunca Supabase): unitarias de la resolución (par adaptador + tipo, una sola vez) y de que un adaptador sin tipo se rechaza; integración del alta del cobro con su origen, de la recepción del evento (origen capturado **antes** de emparejar, incluido el `UNMATCHED`) y de la entrada del registro; **migración con filas previas** en las tres tablas (sube y baja, relleno `mock`, esquema final sin `DEFAULT`, rechazo de inserción sin origen, guarda de `downgrade`, guarda de proveedor desconocido, **prueba de la premisa del registro**); caos (cambio de configuración entre pedido, cobro, evento y entrada; reentrega; reembolso tras el cambio; evento de otro tipo; adaptador inyectado sin tipo); propiedad de agregación (A5); frontera de frontend (sin «Real» derivado, `Verified<T>` con origen, API antigua → «Sin datos de origen»); prueba de uso prohibido de `ProviderBinding.is_simulated`; regresión de las 4229 + 642 existentes; CI completo entre commits.

**Mutaciones** (cada una debe romper al menos una prueba): M1 no copiar el origen a la entrada · M2 escribir `mock` fijo en el cobro o en el evento · M3 volver a poner un `DEFAULT` · M4 quitar el `CHECK` · M5 quitar una clave ajena compuesta · M6 derivar el origen de `Order.is_simulated` · M7 un agregado que ignora el origen · M8 permitir `UPDATE` de `provider_kind` · M9 mapear «ausente» a `mock` · M10 una etiqueta «Real» derivada · M11 emparejar sin exigir el tipo · M12 resolver el tipo con una segunda lectura de `Settings` · M13 **inferir el tipo del evento por el nombre del proveedor** · M14 capturar el origen del evento **después** de emparejar · M15 usar `ProviderBinding.is_simulated` en la ruta del dinero.

### 17. Implicaciones para Supabase (sin aplicarlas)

- **Nada se aplica en este commit ni en M46.** Línea base verificada el 2026-10-12: `alembic_version = e1b8d4a62f37`; faltan 6 revisiones; no existen `payments`, `payment_events` ni `revenue_ledger_entries` allí.
- Tras el Commit 2 de M46 serán **7** las revisiones pendientes (la 44.ª incluida). Como esas tablas no existen en Supabase, **no hay filas que rellenar** allí: hacer M46 antes de la Fase B evita migrar dos veces.
- La Fase B se rehace con 7 revisiones y se ensaya en local antes. Las columnas nuevas heredan la RLS de sus tablas; la función y los disparadores nuevos (si el mecanismo de §7 los usa) deben revisarse con el asesor de seguridad de Supabase **en la Fase B**, no antes.
- El proyecto objetivo es `amazona`; el proyecto inactivo no se toca.

### 18. Decisiones del propietario (2026-10-12)

| # | Decisión | Dónde |
|---|---|---|
| D1 | Dos ejes: evidencia (`verified/declared/planned/demo`) y origen (`mock/sandbox/real`); sin booleano | §1–§3 |
| D2 | Los hechos `verified` de orígenes distintos no se mezclan como «ingresos»; transversal solo etiquetado como agregado de registros | §10 |
| D3 | Relleno histórico `mock`, solo porque el registro de pagos admite únicamente `MOCK`; prueba de la premisa; `DEFAULT` temporal; esquema final sin `DEFAULT` | §8 |
| D4 | Sin `provider_kind` en `refunds`; el origen se copia al registro y es inmutable; invariantes contra la divergencia; si no se puede sin duplicar, **detenerse** | §5–§7 |
| D5 | `Order.is_simulated` se mantiene, no es fuente de procedencia; prohibido «Real» por inferencia | §11, §12 |
| D6 | Commit 1 = solo este ADR | cabecera |
| D7 *(enmendada, 2.ª ronda)* | `payment_events` **sí** lleva `provider_kind` explícito (capturado en `PaymentIngress` antes de emparejar); `refunds` **no**. **No se infiere nunca por el nombre del proveedor**; un adaptador sin tipo estructurado se rechaza | §4, §6, §7 |
| D8 | Quién/cuándo llevó Supabase a `e1b8d4a62f37`: cuándo, el DDL del 2026-10-02 (10:23:07–10:23:08 UTC); quién, **UNKNOWN** | FASE A (`36a9f3f`) |
| D9 | Corregir antes la documentación del «faltan 24» | FASE A (`36a9f3f`, publicado, CI verde) |
| D10 | Moneda de `finance_validation` solo si existe en los datos; sin EUR por defecto | §9 |
| R2 | 2.ª ronda: ninguna excepción por nombre de proveedor; el origen de un evento sin cobro también es un dato persistido. `ProviderBinding.is_simulated` no es procedencia | §6, §12 |

### 19. Qué no se decide aquí

Ningún adaptador `sandbox` ni `real`; ninguna regla de liquidación, contracargo, IVA/OSS ni contabilidad; ninguna conversión de moneda; ninguna columna en `refunds`; ningún agregado nuevo del CFO; nada sobre Supabase. Queda como deuda P3 el renombrado o retirada de `ProviderBinding.is_simulated` (con su clave `simulated` en `/api/status`) y la diferencia entre `ProviderBinding.name` y `provider.name`.

### 20. Plan de commits de M46

| # | Commit | Migración |
|---|---|---|
| 1 | **docs: ADR 0031** (este) | no |
| 2A | backend: migración 44.ª, dominio, propagación del tipo y emparejado (**implementado**, §21) | **sí (44.ª)** |
| 2B | backend: `check_ledger` C5/C6, defensas, prueba de uso prohibido, caos y mutaciones (**implementado**, §22) | no |
| 3 | API: agregados por origen, `OrderOut`/pagos con origen, `SCOPE` | no |
| 4 | frontend: `Verified<T>` con origen, etiquetas, fuera «Real»; prueba de frontera actualizada | no |
| 5 | `POST /api/economics/runs`: canal desconocido → 422 | no |
| 6 | Las 9 lecturas silenciosas del Panel → `UNREAD` | no |
| 7 | `ProjectOut.created_at` (y moneda de `finance_validation` solo si existe) | no |
| 8 | Textos que afirman más de lo que el sistema sabe | no |
| 9 | docs: milestone 46 y `system-overview` | no |

**Alcance previsto del Commit 2** (dividido por decisión del propietario en 2A, ya implementado, y 2B; el addendum §21 recoge lo que 2A hizo de verdad y en qué se aparta de esta lista):

- **Migración 44.ª** (`down_revision = e5a1d7c93b04`): `provider_kind` en **`payments`, `payment_events` y `revenue_ledger_entries`**, con el relleno y las guardas de §8, `CHECK`, `UNIQUE (id, provider_kind)`, claves ajenas compuestas y disparadores de §7. **Sin columna en `refunds`.**
- **`PaymentIngress`:** recibe (adaptador, tipo) de una única resolución del registro; captura el tipo **antes** de emparejar; rechaza un adaptador sin tipo estructurado. Se adaptan los 3 puntos de producción (`api/payments.py`, `cli.py` ×2) y las 10 líneas de pruebas de 3 ficheros que lo construyen.
- **`orders/payment_attempts.py`:** el alta del `Payment` toma nombre y tipo de la misma resolución.
- **`payments/service.py`:** el emparejamiento exige el mismo tipo; el desacuerdo es `CONFLICT`. **`orders/refunds.py`:** la comprobación de `_check_payment` incluye el tipo.
- **`revenue/ledger.py`:** copia el tipo del cobro/evento/captura a la entrada.
- **`revenue/check.py`:** C5 y C6.
- **Unicidades `(proveedor, referencia)`** de cobros, eventos y reembolsos (F12): evaluar si incluyen el tipo; decisión con evidencia en el Commit 2.
- **Compatibilidad:** `ProviderBinding.is_simulated` deja de usarse en `orders/`, `payments/` y `revenue/`, con prueba que lo impide.
- **Pruebas, caos y mutaciones** de §16 (incluidas M13–M15).

Un commit por responsabilidad, CI completo entre commits y push solo con autorización expresa. Los agregados nuevos del CFO quedan fuera salvo que el volumen real los exija.

### 21. Addendum del Commit 2A (2026-10-12): lo que se implementó

Este apartado documenta **exactamente** la implementación del Commit 2A. Donde difiere de lo previsto arriba, manda este apartado.

**D1 — F12, B-parcial.** `provider_kind` entra en la identidad estructural de `Payment` y de `PaymentEvent`; `Refund` **no** gana columna.

- `uq_payments_provider_payment_ref` es ahora `(provider, provider_kind, provider_payment_ref)` (parcial, `provider_payment_ref IS NOT NULL`)
  y `uq_payment_events_provider_event`, `(provider, provider_kind, provider_event_id)`. `uq_refunds_provider_refund_ref` **no cambia**.
- Comprobado con pruebas: la misma referencia o el mismo id de evento en **dos orígenes** son dos hechos distintos (incluidos `mock`↔`sandbox`
  y `sandbox`↔`real`); en el **mismo** origen siguen siendo uno solo, también bajo carrera.
- **Reembolsos, residual conocido y probado:** su identidad sigue siendo `(proveedor, referencia)`. Una colisión de referencia de reembolso
  entre dos orígenes se **rechaza** (`uq_refunds_provider_refund_ref`, en voz alta); jamás se funde con el otro hecho. El emparejado por
  referencia de un reembolso exige el origen **por su cobro** (`Refund.payment_id` es obligatorio): un evento de otro origen que solo coincide con
  la referencia de un reembolso queda `UNMATCHED`. Condición del propietario: si apareciera una ambigüedad de reembolso que las claves
  actuales no impidan, se detiene el trabajo antes de ampliar `refunds`.

**D2 — Cómo viaja el tipo: `PaymentProvider.kind`** (refina el §4; el tipo sigue siendo estructurado y sale del registro).

- `PaymentProvider.kind: ProviderKind` es un atributo **obligatorio** del puerto. Solo valen `mock`, `sandbox` y `real`; una cadena suelta
  (`"mock"`), `None` o `composite` se rechazan con `PaymentProviderKindError` (`require_payment_kind`).
- `SimulatedPaymentProvider.kind = ProviderKind.MOCK` lo declara él mismo; sus subclases lo heredan y una que quiera otro origen lo declara
  explícitamente. **Ningún camino** deduce el tipo del nombre, de `Order.is_simulated`, de `ProviderBinding.is_simulated` ni del entorno.
- **El registro valida dos veces:** al cargar el módulo (`validate_payment_implementations()`: el `kind` de cada adaptador de pagos debe ser
  el de la clave bajo la que se registra) y al resolver (`ProviderRegistry.resolve`). Un adaptador mal etiquetado no llega a existir.
- Un proveedor sin `kind` válido no abre cobros (`PaymentAttemptService.start`) ni recibe eventos (`PaymentIngress.receive`): se rechaza **antes**
  de verificar ni escribir nada.

**Propagación.** `PaymentProvider.kind` → `Payment.provider_kind` (alta del cobro) → `PaymentEvent.provider_kind` (capturado en
`PaymentIngress.receive`, **antes** de emparejar; lo conserva también un evento `UNMATCHED`) → `RevenueLedgerEntry.provider_kind` (copiado del
cobro; un reembolso, de su captura). `RevenueLedger` comprueba además que el evento es del mismo origen que el cobro (si no,
`RevenueLedgerWriteError`: no es la carrera de las capturas).

**Emparejado (precisa §6 y F4).**

- Por **referencia del proveedor** (cobro o reembolso): solo dentro del mismo origen. Si únicamente la referencia coincide en otro origen, no hay
  emparejado: el evento queda `UNMATCHED`, con su propio origen.
- Por **nuestro id** (`client_reference`): si el cobro nombrado es de otro origen, el evento es `CONFLICT`, se conserva como evidencia y **no se
  enlaza** al cobro (`payment_id` queda nulo: la clave ajena compuesta tampoco lo permitiría), sin tocar el cobro, el pedido ni el registro.
- Pedir un reembolso a un proveedor de otro origen que el del cobro se rechaza (`ConflictError`) sin reservar nada.

**Migración 44.ª (`b7e4a1c9d052`).** Orden: (1) **guarda**, antes de tocar nada: se niega si hay un cobro o un evento cuyo `provider` no es el del
simulador (no clasifica: solo se niega); (2) `ADD COLUMN … DEFAULT 'mock'` temporal en `payments`, `payment_events` y `revenue_ledger_entries`;
(3) se **retira** el `DEFAULT`; (4) `CHECK` cerrado; (5) `UNIQUE (id, provider_kind)` en cobros y eventos; (6) las dos identidades por origen;
(7) tres claves ajenas compuestas (`fk_payment_events_payment_kind`, `fk_revenue_entries_payment_kind`, `fk_revenue_entries_event_kind`);
(8) disparadores que rechazan el `UPDATE` que **cambia** `provider_kind` en cobros y eventos (función `provider_kind_immutable()` con
`SET search_path = pg_catalog`). `downgrade` se niega si alguna fila no es `mock`. Una prueba demuestra la premisa del relleno: el registro de
pagos contiene solo `MOCK`, y cualquier otro tipo lanza `ProviderNotAvailableError`.

- **El relleno no usa `UPDATE`:** el `DEFAULT` temporal no dispara los disparadores *append-only* (demostrado en PostgreSQL con la cadena real de
  Alembic, no solo en un experimento), y una prueba comprueba que la migración no emite ninguna sentencia DML.
- **Trampa de SQLite (solo pruebas):** recrear una tabla con `batch_alter_table` **destruye sus disparadores** sin avisar; el registro dejaba de
  ser *append-only*. La rama SQLite los **vuelve a crear** y hay pruebas, tras subir, bajar y volver a subir, de que existen y rechazan `UPDATE`
  y `DELETE`.
- **Sin tablas nuevas:** la RLS se hereda y no se toca (prueba con la cadena real: `relrowsecurity` y las políticas, idénticas antes y después).

**Radio de impacto real** (corrige la estimación del §20). Con `kind` como atributo del adaptador, los siete proveedores de prueba lo heredan del
simulador y no se tocaron. Hubo que declarar el origen en seis sitios que construyen filas a mano (cobros, un evento «ya guardado» y dos
clonadores de entradas del registro), cuatro pruebas de paridad modelo↔migración que ahora aplican toda la cadena, y tres pruebas antiguas que
fijaban un detalle que cambió (las claves de la auditoría, una llamada directa a `PaymentIngress._record` y la migración del registro sobre
PostgreSQL).

**Lo que quedaba para 2B** (hecho, ver §22) **y siguientes:** `check_ledger` C5/C6, la prueba que prohíbe `ProviderBinding.is_simulated` en `orders/`, `payments/` y
`revenue/`, el caos y las mutaciones restantes (M1–M18), la API y la interfaz.

### 22. Addendum del Commit 2B (2026-10-12): lo que se implementó

Este apartado documenta **exactamente** el Commit 2B (sin migración, sin cambios de esquema ni de comportamiento de la aplicación: solo la comprobación, la guarda y las pruebas). Donde difiere de lo previsto en §15 y §20, manda este apartado.

**`check_ledger` C5 y C6** (`app/revenue/check.py`; una sola consulta cada una, sin bucle por fila, solo `SELECT`):

- **C5** (entrada ↔ origen). Una entrada es divergente si su `provider_kind` difiere del de su cobro, del de su evento o, si es un reembolso, del de la captura que revierte. El hallazgo trae `entry_id`, `payment_id`, los cuatro orígenes (`origin`, `payment_origin`, `event_origin`, `capture_origin`) y los motivos, uno por comparación que falla.
- **C6** (evento ↔ cobro). Un evento **enlazado** a un cobro (`payment_id` no nulo) es divergente si su origen difiere del del cobro. Se mira en **todos** los eventos enlazados, no solo en los que causaron una entrada. Un `UNMATCHED` o un `CONFLICT` por origen no tiene cobro y conserva el suyo: no es una divergencia.
- Se informan en `revenue.ledger.divergences` (y en el recuento del informe programado) junto a C1–C4; **nunca se corrigen** (una prueba exige que mirar no escriba nada, ni siquiera cuando hay divergencias, y que repetirlo dé lo mismo).
- **Qué son y qué no.** Con el esquema íntegro **no pueden ocurrir**: las claves ajenas compuestas y los disparadores de la 44.ª migración los impiden. Existen por deriva de esquema (una restauración con los disparadores desactivados, SQL a mano, una migración futura que quite una clave). Las pruebas **provocan esa deriva** (PostgreSQL: `SET LOCAL session_replication_role = replica`, que es lo que hace `pg_restore --disable-triggers`; SQLite: sin claves ajenas y sin disparadores) y comprueban que se detecta.
- **No hay C7.** «Hechos financieros que deberían estar en el registro y no están» ya lo cubren C1, C2 y C4 (importes) y `outside_ledger` (anteriores al registro); 2B solo añade pruebas de esos controles para los tres orígenes. Un valor de origen **fuera del conjunto cerrado** solo puede existir si se ha quitado el `CHECK`: no se informa como comprobación aparte (deuda anotada en el handoff).
- Coste medido (PostgreSQL local, 300 000 cobros/eventos/entradas sanos, el peor caso para un escaneo): C5 645 ms, C6 255 ms, `check_ledger` completo 3,1 s (C3, ya existente, 390 ms). Joins en *hash* paralelos; escala linealmente.

**La prohibición de inferir el origen deja de ser una convención** (`tests/unit/test_money_provenance_architecture.py`, un recorrido del árbol sintáctico de `orders/`, `payments/`, `revenue/` y `reconciliation/`):

- Prohíbe leer `ProviderBinding.is_simulated`, `ProviderRegistry.kind_for/binding_for/bindings` (leen `Settings`, no al adaptador), `Settings.operating_in_simulation/payments_provider/environment` y `.is_simulated`; nombrar `ProviderKind.X`, construir un `ProviderKind` o escribir `"mock"`, `"sandbox"`, `"real"`, `"simulated-payments"`; comparar el nombre de un proveedor con una constante o mirar su prefijo; dar a `provider_kind=` algo que no sea el origen del proveedor, del cobro o de la captura; asignar a `.provider_kind`; e importar un adaptador concreto.
- Solo el puerto (`payments/port.py`) y los adaptadores (`payments/providers/`) pueden declarar o validar un origen.
- Las excepciones son **cinco entradas en cuatro ficheros, nombradas una a una con su motivo**, y la lista solo puede menguar: `orders/service.py` (anota `Order.is_simulated` al crear el pedido: contexto histórico, §12), `orders/gate_inputs.py` (puerta legal), `orders/domain.py` (valida el prefijo `sim_` del pedido) y `reconciliation/config_check.py` (decide qué adaptadores validar al arrancar). Ninguna clasifica un importe.
- **El propio escáner se prueba**: 32 fragmentos que debe rechazar y 12 que debe dejar pasar. Una guarda que no ve nada pasa siempre.
- **Prueba dinámica complementaria** (`test_origin_inference_poison.py`): «envenena» `ProviderBinding.is_simulated` y los métodos del registro (leerlos falla en voz alta) y recorre abrir, capturar, duplicar, reembolsar y reconciliar; invierte `Order.is_simulated` por SQL después de abrir el cobro; y pasa unos ajustes que dicen otro proveedor. El origen no cambia.

**Oráculos de las pruebas.** `m45_invariants_test_support` gana un oráculo del origen **escrito a mano e independiente de `check_ledger`** (el origen está en el conjunto cerrado y nunca cruza cobro, evento, entrada ni captura) y `LedgerWatch` recuerda el origen de cada cobro y evento (un hecho conserva con el que nació). Con ello cada tormenta y cada recorrido de M45 vigila también la mezcla. Hallazgo del ejercicio: `m44_invariants_test_support` seguía tratando `(proveedor, id de evento)` como único y habría llamado «duplicado» a un hecho legítimo de otro origen (la identidad es `(proveedor, origen, id)` desde 2A); corregido.

**Caos y concurrencia** (`test_origin_chaos.py`, `test_origin_reconciliation_postgres.py`): entrega repetida y mismo id/referencia en los tres orígenes en los seis órdenes de llegada; eventos fuera de orden por origen; `UNMATCHED` (conserva el origen y no se aplica después aunque aparezca el cobro) y `CONFLICT`; evento ajeno que nombra un cobro; `UNKNOWN_OUTCOME` y respuesta tardía; proceso que cae entre guardar y aplicar, y registro que falla; reconciliación repetida; cambio de configuración a mitad; tormentas aleatorias de 40 pasos con los tres orígenes y los oráculos tras cada paso; varios reconciliadores y reentregas a la vez (PostgreSQL); `check_ledger` leyendo mientras otros hilos escriben, sin C5/C6 falsos (cada uno es una sola sentencia sobre filas que se confirman juntas con su cobro).

**Mutaciones** (fuera del repositorio; prefijo `B` para no chocar con las M01–M29 de 2A ni con las M1–M15 del ADR): 33, 33 muertas, 0 supervivientes, incluidas M12 (segunda lectura de `Settings`), M13 (inferir por nombre), M14 (adoptar el origen tras emparejar) y M15 (`ProviderBinding.is_simulated`), esta última también como lectura muerta que solo el veneno detecta.

**Residuales anotados.** (1) Un `PaymentEvent` también tiene `refund_id`; C6 compara con `payment_id` (un reembolso pertenece al cobro del evento por construcción). (2) `check_ledger` sigue leyendo en varias sentencias: C1 y C4 pueden ver una foto intermedia bajo escrituras concurrentes (ya era así); C5 y C6 no. (3) La guarda no cubre `api/` ni `cli.py`: `OrderOut.is_simulated` y la clave `simulated` de `/api/status` son deuda de los Commits 3–4. (4) Un origen fuera de `mock|sandbox|real` solo existiría sin el `CHECK`; no hay comprobación aparte.

## Contrastado contra el código el 2026-10-12

| Afirmación | Fuente |
|---|---|
| `Order.is_simulated` sale de `operating_in_simulation` al crear el pedido | `orders/service.py:71`; `core/config.py:243-261`; `db/models/order.py:40-55` |
| `Payment`, `Refund` y `PaymentEvent` guardan solo el nombre del proveedor | `orders/payment_attempts.py:126`; `orders/refunds.py:140`; `payments/ingress.py` (`_record`) |
| `PaymentIngress` resuelve el adaptador sin tipo y admite uno inyectado | `payments/ingress.py:82,97`; `cli.py:310,357` |
| El registro de ingresos no guarda procedencia | `db/models/revenue.py`; `revenue/ledger.py` |
| El registro de pagos solo admite `MOCK`; el tipo es la clave del registro | `integrations/registry.py:202`; `ProviderNotAvailableError` |
| `ProviderKind` distingue `SANDBOX`; `ProviderBinding.is_simulated` lo colapsa | `integrations/ports.py:50-64`; `registry.py:64-71`; `main.py:231` |
| El emparejamiento compara nombre de proveedor, no tipo | `payments/service.py:126,156-190,410`; `orders/refunds.py:194-200` |
| `Refund.payment_id` es `NOT NULL` con clave ajena | `db/models/payment.py:200` |
| Los agregados mezclan todo | `revenue/aggregates.py:130,190`; `revenue/evidence.py:55` |
| Etiqueta «Real» derivada de `is_simulated` | `apps/control-center/app/operations/operations-panels.tsx:363` |
| El CFO copia `is_simulated` al pedido | `apps/control-center/lib/cfo-margin.ts:173-180` |
| Prueba que exige esta decisión | `apps/control-center/lib/dashboard-revenue-boundary.test.ts:121-150` |
| Supabase en `e1b8d4a62f37`, sin tablas de pagos | consulta de solo lectura del 2026-10-12 |
