# ADR 0031: Procedencia estructurada del dinero — dos ejes (evidencia y origen operativo), persistidos como propiedad del hecho

- **Estado:** Aceptada (decisiones del propietario del 2026-10-12, con una segunda ronda el mismo día que retira toda inferencia por nombre: §6 y §18). **Implementada en parte**: el Commit 2A de M46 implementa el origen en el cobro, el evento y el registro, y el emparejado (ver el **addendum, §21**); el Commit 1 de M46 (este ADR) fue solo documentación. El Commit 2B añade `check_ledger` C5/C6, la guarda arquitectónica contra la inferencia, el caos y las mutaciones (**addendum, §22**). El Commit 3 lleva la procedencia a la API de ingresos, pedidos y reconciliación (**addendum, §23**). El Commit 4 cierra la interfaz: el origen se representa sin inferirlo ni mezclarlo (**addendum, §24**). Faltan los Commits 5–9 (§20).
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
| 3 | API: agregados por origen, `OrderOut`/pagos con origen, `SCOPE` (**implementado**, §23) | no |
| 4 | frontend: `Verified<T>` con origen, etiquetas, fuera «Real»; prueba de frontera actualizada (**implementado**, §24) | no |
| 5 | `POST /api/economics/runs`: canal desconocido → 422 (**implementado**, §25) | no |
| 5b | `POST /api/economics/runs`: precio > 0 y costes fijos ≥ 0; `POST /api/exchange-rates`: `provenance` como enum canónico (**implementado**, §26) | no |
| 5c | Entradas numéricas: `NaN`/`±Infinity`, `bool`, desbordes y paridad economics/pipeline/tipos de cambio (**implementado**, §27) | no |
| 6 | Las 9 lecturas silenciosas del Panel → estados de lectura `loaded` / `empty` / `unread` / `error` (**implementado**, §28) | no |
| 7 | `ProjectOut.created_at` (y moneda de `finance_validation` solo si existe) (**implementado**, §29: `created_at` sí; la moneda no existe en la fuente y no se añade) | no |
| 8 | Textos que afirman más de lo que el sistema sabe (**implementado**, §30) | no |
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

### 23. Addendum del Commit 3 (2026-10-12): la procedencia llega a la API, sin deducirse y sin mezclarse

Este apartado documenta **exactamente** el Commit 3 (sin migración, sin cambios de esquema; `check_ledger` no cambia). Donde difiere de lo previsto en §10 y §20, manda este apartado.

**`SCOPE` ya existía, y no es un filtro.** `aggregates.SCOPE` es el bloque `scope` de cada respuesta de ingresos: declara lo que las cifras **no** son (`is_accounting_ledger`, `basis`, `excludes`). Se **reutiliza**: `basis` dice ahora que toda cifra va separada por `provider_kind` y nunca se suma entre orígenes, y `excludes` añade `cross_origin_totals`. El filtro que pide el consumidor se llama **`provider_kind`** (y no `scope`, para no chocar con ese bloque ni con `RefundOut.origin`, que significa quién inició el reembolso, `OPERATOR` o `PROVIDER`).

**El filtro `?provider_kind=`** (`summary`, `series`, `entries`): `mock`, `sandbox` o `real` (el vocabulario cerrado del puerto de pagos, no una lista escrita aparte); cualquier otro valor, incluido `""`, `composite` o `REAL`, es un **422**. Sin filtro se devuelven **todos los orígenes, siempre separados**: no existe un modo «todo sumado». Un origen sin datos no aparece (sin datos, no un cero).

**Contratos (antes → después)**

| Respuesta | Antes | Ahora |
|---|---|---|
| `GET /api/revenue/summary` | `verified[]`, `under_review[]`, `pending_evidence.by_currency[]` por moneda; `consolidated_eur` (objeto o `null`) **sumaba todos los orígenes** | las mismas filas con `provider_kind` (clave `(origen, moneda[, clase / tipo])`); **`consolidated_eur` desaparece**, lo sustituye `consolidated_eur_by_origin[]` (una fila por origen con EUR; vacío = «Sin datos»); `entries_by_provider_kind[]` (A5: Σ = `entries`); `scope` ampliado |
| `GET /api/revenue/series` | cubos `(día, moneda)` | cubos `(día, origen, moneda)` |
| `GET /api/revenue/entries` | sin origen | `EntryOut.provider_kind` y filtro |
| `GET /api/reconciliation/status` | evidencia y eventos con tope sin origen | `provider_kind` en cada total, cada elemento y cada evento con tope |
| `PaymentOut` / `RefundOut` | sin origen | `provider_kind` (el persistido; el del reembolso, el de su cobro: D4, `refunds` sigue sin columna) |
| `OrderOut` | `is_simulated` | **sin** `provider_kind`: un pedido puede reunir cobros de varios orígenes. `is_simulated` se mantiene, documentado en el esquema OpenAPI como **contexto del pedido**, no procedencia (§12) |

**Compatibilidad y migración del contrato.** Los campos de fila existentes siguen y solo se añade `provider_kind`: un lector que los ignore no se rompe. Lo único que se retira es lo que **mezclaba orígenes**: `consolidated_eur`. En el Control Center, `lib/revenue-contract.ts` valida cada respuesta (`revenueSummary/Series/Entries`) y **falla a la vista** con `RevenueContractError` si llega el contrato antiguo (`consolidated_eur`), si falta `consolidated_eur_by_origin` o si una fila no trae un `provider_kind` válido: nunca se lee como «Sin datos» ni se completa con `mock`. Los consumidores de la API que quieran la cifra de un origen usan `consolidated_eur_by_origin[provider_kind=…]` o `?provider_kind=`. Una repetición con la misma `Idempotency-Key` de una respuesta de cobro o reembolso **guardada antes de este cambio** no trae `provider_kind` y fallaría al validarse: solo afecta a una base con M44 y claves sin caducar (Supabase no tiene M44).

**Fuente única.** Los agregados leen **solo** las columnas guardadas (`revenue_ledger_entries.provider_kind`, `payment_events.provider_kind`, `payments.provider_kind`); no recrean `check_ledger` (C5/C6 validan lo que ellos leen). La guarda arquitectónica de 2B se amplía a `api/revenue.py`, `api/orders.py`, `api/payments.py` y `api/reconciliation.py` (excepción nombrada: la lectura de `order.is_simulated` y el campo `OrderOut.is_simulated`). Prueba dinámica: con `ProviderBinding.is_simulated` y el registro envenenados, `Order.is_simulated` invertido por SQL y unos `Settings` que dicen otro proveedor, la respuesta de ingresos es idéntica.

**Frontend (mínimo, solo contratos y vistas; sin etiquetas finales, que son del Commit 4).** `lib/api.ts` (tipos y `RevenueProviderKind`), `lib/revenue-contract.ts` (nuevo), `lib/revenue-view.ts` (vista por origen: líneas con `providerKind`; `eurByOrigin` en lugar de `eur`; series por `<origen>·<moneda>`), las tarjetas de ingresos del Panel y del CFO (el valor del origen **tal cual**, sin traducir). Las cifras de cabecera: con **un** origen se enseña su cifra y su origen; con **varios** no hay cifra («Varios orígenes») y cada uno va aparte. Los textos que decían que «el registro todavía no guarda esa procedencia» eran ya falsos y se corrigen (sin la palabra «real»), y `dashboard-revenue-boundary.test.ts` se **actualiza conscientemente** (lo pedía su propio mensaje; el ADR §11 lo situaba en el Commit 4): ahora exige que la procedencia sea estructurada (`provider_kind`) y que ninguna señal débil (`is_simulated`, `environment`…) entre en los tipos del registro, y sigue prohibiendo la palabra «real» como etiqueta.

**Coste.** Medido en PostgreSQL local con 300 000 entradas: agrupar también por `provider_kind` no cambia el plan ni el tiempo (ventana de 30 días 16 → 19 ms; todo el registro 112 → 114 ms). Sin migración ni índice nuevo.

**Residuales anotados.** (1) `lib/cfo-margin.ts` suma por pedido todas las entradas sin mirar su origen (A6): hoy solo existe `mock`; un pedido con cobros de dos orígenes mezclaría sus importes en el margen. Es del Commit 4 (`Verified<T>` con origen). (2) `app/operations/operations-panels.tsx:363` sigue rotulando «Simulado»/«Real» según `Order.is_simulated` y `/api/status` conserva la clave `simulated` (deuda P3): son del Commit 4 (§11); el Commit 3 no toca esa pantalla. (3) Las etiquetas de cara al usuario («Simulado», «Entorno de pruebas», …) siguen sin fijarse: el valor del origen se enseña en crudo. (4) Las repeticiones de claves de idempotencia anteriores (arriba).

### 24. Addendum del Commit 4 (2026-10-12): la interfaz representa el origen sin inferirlo y sin mezclarlo

Este apartado documenta **exactamente** el Commit 4 (solo Control Center: sin cambio de backend, de contrato ni de esquema). Donde difiere de lo previsto en §11 y §20, manda este apartado.

**Una sola fuente del vocabulario de origen** (`lib/provenance.ts`; `components/origin-badge.tsx` solo lo pinta). El origen es un **segundo eje**, ortogonal a la procedencia de la cifra (registro / declarado / PLAN / demo): `Origin` (`mock`, `sandbox`, `real`), `summarizeOrigins` (`none` / `single` / `multiple` / `unknown`) y los textos: *Simulado* · *Entorno de pruebas* · *Proveedor real* · *Varios orígenes* · *Sin cobro* · *Sin datos de origen*. El origen describe **al proveedor** del hecho: «Proveedor real» no afirma que el dinero esté liquidado ni contabilizado (su tooltip lo dice). Un valor fuera del vocabulario nunca se traduce a `mock`, `sandbox` ni `real` (§9). **Esos textos no se escriben en ningún otro fichero**: lo impone una prueba (`lib/origin-boundary.test.ts`).

**`Verified<T>` lleva el origen** (§11): `Verified<T, O extends Origin>`. `verified(x)` a secas ya no existe (`verified(x, origin)`); `add`/`subtract`/`total` genéricos ya no aceptan hechos verificados; `addVerified` / `subtractVerified` exigen el mismo origen: con orígenes literales distintos **no compila** (`NoInfer`, comprobado con `@ts-expect-error`) y con orígenes que vienen de datos **lanza `MixedOriginError`**. `lib/revenue-contract.ts` reutiliza el mismo vocabulario.

**Operaciones.** El chip «Simulado»/«Real» que dependía de `Order.is_simulated` desaparece. El origen de un pedido es el de sus **cobros con dinero verificado** (`payments[].provider_kind`, el que guardó el backend): uno ⇒ su origen; varios ⇒ «Varios orígenes»; ninguno (o solo intentos sin dinero) ⇒ «Sin cobro», nunca un origen inventado. Cada cobro y cada reembolso llevan su `OriginBadge`. `Order.is_simulated` sobrevive **solo** como una fila de *contexto del pedido* (`orderContextText`: «Creado en un despliegue de simulación»), y es lo único que lo lee en toda la aplicación (además del tipo). Los KPI «Cobrado» y «Reembolsado», que sumaban los cobros de todos los orígenes, pasan a agruparse **por origen y, dentro, por moneda**: con varios orígenes el valor es «Varios orígenes» y cada uno va aparte. El CSV lleva «Origen del dinero». Textos retirados: «Dinero realmente cobrado», «Datos reales · eventos simulados».

**CFO / margen** (`lib/cfo-margin.ts`, reescrito). El margen se agrega **por origen**; no existe ni una cifra de margen, ingreso, neto, coste o cobertura a nivel de resumen (una prueba lo exige). Las entradas se agrupan por `(pedido, origen)` y las sumas pasan por `addVerified`. Un pedido con ingreso en **varios orígenes** enseña sus cifras separadas por origen y **no tiene margen, ni el de ningún origen implicado** (`mixed_origins`): el coste es del pedido y repartirlo sería inventar un reparto (ni promedio, ni proporción). Un origen no reconocido en una entrada no se asigna a ninguno y bloquea los márgenes (`unknown_origin`). Se mantienen la cobertura visible, «Sin datos» cuando falta un coste, EUR como única moneda, los duplicados fuera y la moneda separada. Se retiran `isSimulated` y `simulated`.

**Panel y registro.** Las tarjetas del Panel y del CFO pintan el origen con `OriginBadge` o con el nombre de la fuente única; con varios orígenes la cabecera dice «Varios orígenes» y nombra cada cifra aparte. La serie se elige por origen y moneda.

**Vocabulario.** Se corrigen el texto de demostración («se sustituirá por el real») y uno de entregas de proveedor («entregas reales»); `dashboard-revenue-boundary.test.ts` y `cfo-boundary.test.ts` se ajustan de forma consciente: la palabra «real» solo puede salir de la definición del origen `real` en `lib/provenance.ts`.

**Pruebas.** 715 de frontend (+57 sobre las 658 del Commit 3): las 7 combinaciones de orígenes en el margen y en Operaciones, pedido sin cobros, intento sin dinero, varias monedas, coste parcial y ausente, reembolso, duplicado, origen desconocido, `Order.is_simulated` invertido sin que cambie nada, el nombre del proveedor sin efecto, y `lib/origin-boundary.test.ts` (15 pruebas arquitectónicas que leen el código: dónde se lee `is_simulated`, que nada suma por encima del origen, que el vocabulario vive en un sitio, que ningún provider_kind se pinta crudo, que ningún texto afirma «dinero real», «ingresos reales» o «realmente cobrado»). 27 mutaciones, 27 muertas.

**Deuda restante de M46** (§20): Commit 5 (`POST /api/economics/runs`: canal desconocido ⇒ 422), 6 (las 9 lecturas silenciosas del Panel ⇒ `UNREAD`), 7 (`ProjectOut.created_at`; moneda de `finance_validation` solo si existe), 8 (textos que afirman más de lo que el sistema sabe), 9 (docs: milestone 46 y `system-overview`). Y la Fase B de Supabase (7 revisiones pendientes).

### 25. Addendum del Commit 5 (2026-10-13): un canal que el catálogo no declara es un 422

Este apartado documenta **exactamente** el Commit 5 (solo backend, un endpoint: sin migración, sin cambio de esquema ni de frontend). No tiene relación con el origen del dinero; cierra una deuda de §20.

**Causa.** `POST /api/economics/runs` aceptaba `channel` como cadena libre y el servicio lo resolvía con `channel_for()`, que lanza `UnknownChannelError`. Esa excepción es un `ValueError` suelto —no un `ValidationError` del dominio— y ningún manejador la traducía: un typo del cliente salía como un **500**. No escribía nada (la comprobación ocurre antes de cualquier escritura), pero decía «fallo del servidor» donde el fallo era de quien llama.

**Cambio.** `_require_declared_channel` en `app/api/economics.py` comprueba el canal en la frontera de entrada, antes de crear nada, y traduce **solo** `UnknownChannelError` a `ValidationError`, que ya tiene su 422 registrado (`{"detail": "<mensaje>"}`, el mismo cuerpo que una moneda fuera de catálogo). El mensaje lista los canales declarados. La comparación es literal: `OWN_WEB`, `" own_web "` o `""` **no** se normalizan; recortarlos guardaría un análisis bajo un canal que el cliente no escribió.

**Lo que no cambia, a propósito.** El servicio sigue fallando en voz alta si un llamador interno le pasa un canal inexistente, y eso sigue siendo un 500: no se hizo `UnknownChannelError` hija de `ValidationError` porque convertiría en «culpa del cliente» un typo de un adaptador nuestro. Un canal declarado pero **no transaccional** (`search:google`, `social:*`) ya era un 422 del dominio y lo sigue siendo. El canal por defecto (`own_web`) y el pipeline no cambian.

**Pruebas.** `tests/integration/test_economics_channel_boundary.py`, 36: cada canal transaccional aceptado y conservado tal cual; los no transaccionales con su 422; 13 valores no declarados (typo, vacío, mayúsculas, espacios, salto de línea, NUL) con 422, cuerpo `{"detail": <cadena>}` sin clase interna, ruta ni traceback, y **ninguna fila nueva en ninguna tabla**; tipo incorrecto, payload incompleto, dos llamadas inválidas seguidas sin envenenar la siguiente, producto inexistente que sigue siendo 404, y dos pruebas de que un fallo interno sigue siendo 500 sin filtrar su mensaje. Con el código anterior fallan 15. 16 mutaciones, 16 muertas.

**Fuera de alcance, anotado.** Otras entradas de economics que también acaban en 500 y no comparten esta frontera: `sale_price = 0` (`ZeroDivisionError` en `economics/scenarios.py`), `provenance` fuera del enum en `POST /api/exchange-rates` (`ValueError` del enum), y un `sale_price` negativo que se acepta con 201.

### 26. Addendum del Commit 5b (2026-10-13): precio, costes fijos y procedencia del tipo de cambio en la frontera de entrada

Este apartado documenta **exactamente** el Commit 5b (solo backend, un fichero de aplicación: sin migración, sin esquema de base de datos ni frontend). Cierra los tres hallazgos anotados en §25 y no tiene relación con el origen del dinero.

**Causas.** (A) `sale_price = 0` llegaba a `economics/scenarios.py` y dividía por cero (500). (B) un `sale_price` o un `monthly_fixed_costs` negativo se aceptaba y se guardaba con un 201. (C) `ExchangeRateCreate.provenance` era una cadena libre y el endpoint hacía `SupplierFactProvenance(valor)`: un valor fuera del enum lanzaba un `ValueError` que ningún manejador traducía (500).

**Decisiones de dominio.** El `sale_price` es un precio de venta comercial: **estrictamente positivo**; cero y los negativos son inválidos y no se usan para modelar promociones gratuitas ni subvenciones (si existen, tendrán semántica propia). Los `monthly_fixed_costs` son **≥ 0**: cero es válido y un negativo no representa ingresos, subvenciones ni créditos. «Positivo» se entiende **como importe monetario**: `Money` guarda `INTERNAL_PLACES` (4) decimales y redondea con ROUND_HALF_UP, así que un precio por debajo de 0,00005 se queda en 0,0000 —un precio cero que el análisis daba por «evaluable»—; el mínimo aceptado se deriva de esa constante (`MIN_SALE_PRICE`). Esta lectura es una **precisión nuestra** sobre la decisión «> 0», no una cota comercial.

**Cambio.** `_require_amounts_the_analysis_can_use` (`app/api/economics.py`) exige un precio finito ≥ `MIN_SALE_PRICE` y unos costes fijos finitos ≥ 0, y es lo primero que hace el endpoint, antes de crear nada: un 422 de dominio `{"detail": "<cadena>"}` que nombra los campos y **no repite lo que mandó el cliente**. Es una precondición, no un `except ZeroDivisionError`. No se usó `Field(ge=...)`: el 422 de esquema repite el valor recibido en su cuerpo y un `NaN` o un `Infinity` no se pueden escribir en JSON, de modo que habría convertido un 422 que ya era limpio en un 500 (lo detectaron las pruebas). `ExchangeRateCreate.provenance` pasa a ser el enum canónico `SupplierFactProvenance` (no se creó un segundo enum): un valor fuera de él es un 422 de esquema de FastAPI antes de entrar en el endpoint, sin normalizar, sin sustituir por un valor por defecto y sin inferir; `unknown` está en el enum y `ExchangeRate` lo sigue rechazando con su propio mensaje de dominio.

**Lo que no cambia, a propósito.** Los fallos internos (`RuntimeError`, `ZeroDivisionError` o `ValueError` de dentro) siguen siendo un 500 y no filtran su mensaje. El servicio no se tocó. El tipo incorrecto (`"abc"`, `null`, lista…) sigue siendo el 422 de esquema de siempre.

**Pruebas.** `tests/integration/test_economics_input_bounds.py` y `tests/integration/test_exchange_rate_provenance_boundary.py`: precios válidos hasta el mínimo representable, 17 precios inválidos (cero, negativos, sub-resolución, `NaN`, `Infinity`, cadenas numéricas), costes fijos válidos y 10 inválidos, 14 procedencias fuera del enum (mayúsculas, espacios, vacía…), tipos incorrectos, payload incompleto, dos inválidas seguidas, ninguna fila nueva en ninguna tabla tras una entrada inválida y fallos internos que siguen siendo 500. Contra el código del Commit 5 fallan 44. 27 mutaciones, 27 muertas.

**Fuera de alcance, anotado.** `sale_price` o `monthly_fixed_costs` de ~1e308 (`decimal.InvalidOperation` en `Money`; requeriría una cota de dominio) siguen dando 500; `POST /api/pipeline/runs` (`PipelineRunCreate`) tiene el mismo esquema sin validar; Pydantic acepta `true` y `"20"` como número; un tipo de cambio se puede declarar como `simulated` por la API; y `ApiError.detail` del frontend solo muestra el `detail` cuando es una cadena.

### 27. Addendum del Commit 5c (2026-10-13): fronteras numéricas de entrada y paridad entre endpoints

Este apartado documenta **exactamente** el Commit 5c (solo backend: sin migración, sin esquema de base de datos ni frontend). Cierra la deuda D1–D5 anotada tras el 5b. No tiene relación con el origen del dinero.

**Causas.** (1) Un `NaN`/`Infinity` repetido en el `input` de un 422 de esquema no se puede escribir en JSON y convertía ese 422 en un 500, en cualquier campo numérico con restricción de cualquier endpoint. (2) Un `decimal.InvalidOperation` suelto al cuantizar en `Money` (importes ≥ 1e24, o precio × unidades) salía como 500. (3) `Money` representa más de lo que algunas columnas guardan: en PostgreSQL un importe válido para `Money` pero fuera de `Numeric(12, 4)` / `Numeric(12, 2)` / `Numeric(18, 8)` era un 500 o, en el pipeline, un `PendingRollbackError` que dejaba el run en `RUNNING`. (4) `POST /api/pipeline/runs` no validaba ningún número. (5) `monthly_unit_sales_base` enorme daba ingresos y beneficio `null` en silencio dentro de un análisis «con éxito» (el `inf` de coma flotante se serializaba como `null`). (6) `true`, `false` y cadenas numéricas se aceptaban como número.

**Decisiones.** *Una sola regla de «representable como Money»*: `Money._quantize` (la única fuente de verdad) y `Money.can_represent`; solo la causa «importe **finito** demasiado grande» se traduce a `AmountNotRepresentableError` (un `ValidationError`); cualquier otro `InvalidOperation` sigue siendo visible. La consecuencia técnica (precisión 28 y 4 decimales ⇒ importes de valor absoluto < 1e24) **se documenta, no se escribe como constante**. *No es un máximo comercial ni fiscal*; la política de límites de negocio sigue sin definirse. *La capacidad de las columnas se lee de las propias columnas* (`app/db/numeric_capacity.py`): `require_row_fits_storage` rechaza, antes de `db.add`, un resultado que `Numeric(12, 4)` o el `INTEGER` de PostgreSQL no guardan (`ValueNotStorableError`, un 422 que no nombra columnas). El efecto práctico y su alcance se describen en el apartado **LIMITACIÓN TÉCNICA DEL ESQUEMA ACTUAL** que sigue. *Una sola precondición compartida* (`app/api/numeric_inputs.py::require_amounts`): `sale_price` y `monthly_fixed_costs` pasan por el mismo código en economics y en el pipeline; `daily_budget >= 0` y que quepa donde se guarda el gasto (`ExternalAction.amount`); `monthly_unit_sales_base >= 0`; todo finito. *Tipado estricto* (`StrictFloat`/`StrictInt`) solo en los campos numéricos de los tres esquemas: rechaza `bool` y cadenas numéricas; `rate` sigue aceptando la cadena `"0.92"` (es un `Decimal`, formato del contrato). *`max_results` 1..20* con una sola fuente (`MAX_RESULTS_MIN/MAX`) que usan research, sourcing y pipeline. *`rate`* con `max_digits`/`decimal_places` leídos de `Numeric(18, 8)`: rechaza (422) en vez de redondear lo que la columna desbordaría o guardaría como `0E-8`. *Manejador global de `RequestValidationError`* (`app/api/validation_body.py`, registrado en `main.py`): mismo cuerpo que FastAPI, solo `input`/`ctx` saneados (`NaN`/`Infinity` como texto; eco acotado a 256 caracteres o 1 024 de JSON); no captura nada más. *Escenarios*: `build_scenarios` falla en voz alta si un escenario no es un número real o no cabe como `Money`, en lugar de devolver `null`.

**LIMITACIÓN TÉCNICA DEL ESQUEMA ACTUAL.** Las cotas que este commit hace cumplir proceden **exclusivamente** de la capacidad de representación y de persistencia del esquema actualmente implementado:

| Origen | Cota | Dónde se aplica |
|---|---|---|
| `Numeric(12, 4)` en `economic_analyses.contribution_margin_per_unit`, `contribution_margin_per_order`, `allocated_fixed_cost_per_order` y `max_breakeven_cac` | valor absoluto ≤ 99 999 999,9999 | `require_row_fits_storage`, antes de `db.add` |
| `Numeric(12, 2)` en `external_actions.amount` (donde acaba `daily_budget`) | valor absoluto ≤ 9 999 999 999,99 | `require_amounts` en `POST /api/pipeline/runs` |
| `Numeric(18, 8)` en `exchange_rates.rate` | ≤ 9 999 999 999,99999999 y 8 decimales | `max_digits`/`decimal_places` de `ExchangeRateCreate.rate` |
| `Integer` en `economic_analyses.units_per_order` (el `INTEGER` de PostgreSQL) | ≤ 2 147 483 647 | `require_row_fits_storage` |
| `Money` / `Decimal` (precisión 28, 4 decimales) | valor absoluto < 1e24 | `Money._quantize` / `Money.can_represent` |

**Ninguna de estas cotas es** un máximo comercial, un máximo fiscal, un límite de precio permitido por AMAZONA ni una política de negocio. Nadie ha decidido que un precio de 150 000 000 sea «demasiado»: es lo que el esquema actual no puede guardar. Se rechaza con 422 porque aceptar el input y fallar después con un 500 en PostgreSQL (o dejar un run atascado) es peor. La política de límites de negocio sigue sin definirse y, cuando exista, estas cotas seguirán siendo el suelo técnico por debajo de ella. Ampliar las columnas con una migración las levantaría.

*El límite efectivo depende del resultado derivado, no solo del precio unitario de entrada.* Lo que se comprueba es lo que se guarda: el margen por unidad (precio − costes), el margen **por pedido** (margen por unidad × `units_per_order`), el coste fijo asignado por pedido y el CAC máximo de equilibrio. El mismo precio unitario puede caber con un pedido de una unidad y no con uno de tres.

*Ejemplo del impacto técnico: el caso VND* (medido en una base en memoria con un tipo de cambio USD→VND de 25 000 declarado a modo de prueba, que no es un tipo real). (i) **Sin tipo de cambio declarado** el análisis queda `not_evaluable` (faltan `exchange_rate`, `product`, `logistics` e `import`): no se calculan ni se guardan márgenes y la cota de almacenamiento **no entra en juego** (un precio de 2 000 000 000 VND da 201). (ii) **Cuando existe conversión y el análisis es evaluable**, `Numeric(12, 4)` puede limitar importes normales de monedas de gran unidad nominal: 100 000 000 VND por unidad da 201 y 150 000 000 VND da 422; con el pedido, 50 000 000 VND con 2 unidades por pedido da 201 y con 3 da 422, y 1 000 000 VND con 100 unidades da 201 y con 200 da 422. (iii) Un 422 en estos casos es hoy preferible a aceptar el input y provocar después un 500 en PostgreSQL (antes eran un 500 en PostgreSQL, mientras que SQLite los guardaba sin queja porque no impone la precisión). (iv) **Queda registrado como deuda de diseño del esquema monetario**, no como comportamiento comercial definitivo: la solución es una migración que ensanche las columnas o una política de límites por moneda, ambas fuera de M46.

**Lo que no cambia, a propósito.** Los fallos internos (`RuntimeError`, `InvalidOperation` interno…) siguen siendo un 500 y no filtran su mensaje. Las reglas de FX (`rate > 0`, procedencia como enum, rechazo de `unknown`) no se tocan. Las cadenas numéricas y los `bool` siguen aceptándose en el **resto** de la API (deuda D4).

**Pruebas.** Matrices de frontera por familia de campo (válido, cero, mínimo, negativo, `NaN`, `±Infinity`, extremo, `bool`, cadena, `null`, lista, objeto) en economics, pipeline y tipos de cambio; paridad valor a valor entre economics y pipeline; ninguna fila nueva tras una entrada inválida; ningún run `RUNNING`; pruebas unitarias de `Money.can_represent`, de la capacidad de columnas, del manejador y de los escenarios. Verificado además en PostgreSQL real: 0 respuestas 500 y 0 runs atascados con los casos que antes los producían.

**Fuera de alcance / sin resolver.** Un máximo de negocio para precios, costes, presupuestos y volúmenes (hoy el techo es el técnico de `Money` y de las columnas: una limitación técnica del esquema actual, ver arriba, y no una política). Pipeline: un precio que pasa la precondición pero cuyo margen no cabe en `Numeric(12, 4)` se encola (202) y el run termina `FAILED` en `economics` con un error explícito (no se puede saber antes de ejecutar el análisis). El manejo de errores del *worker* ante un fallo de base de datos a mitad de un paso (`PendingRollbackError`) sigue sin tocar: solo se impide que el input inválido lo alcance. Las cadenas/`bool` como número en el resto de endpoints. El eco sin límite en el 422 de canal del Commit 5.

### 28. Addendum del Commit 6 (2026-10-14): una lectura que falla no es un dato

Este apartado documenta **exactamente** el Commit 6 (solo Control Center: sin cambio de backend, de contrato HTTP, de esquema ni de modelo monetario). Cierra la deuda de las 9 lecturas silenciosas del Panel (§20) y no tiene relación con el origen del dinero.

**Causa.** `app/dashboard/page.tsx` leía agentes, ejecuciones, aprobaciones, revisiones de pipeline y, por producto, proveedores, economía, legal, tienda y campañas con `.catch(() => [])`: cualquier fallo —4xx, 5xx, backend inaccesible, respuesta con otra forma— se convertía en una lista vacía y de ahí salían hechos falsos: «Agentes en línea 0 / 0 · 0 % operativos» con la insignia *verificado*, «0 del backend» (afirmar que el backend no tiene aprobaciones), **ejecuciones de demostración haciéndose pasar por el log** (el fallo activaba `usingDemoRuns`), un producto con tienda lanzada en fase «En observación», un margen rotulado como supuesto de demostración, un mercado `"eu"` inventado. Si fallaba la lectura de productos, un aviso con el mensaje crudo del error sustituía **toda** la página y escondía los ingresos que sí habían cargado. Un producto fuera del tope de lectura (`PRODUCT_LIMIT = 8`) salía «En observación»: un «sin leer» disfrazado de fase.

**Taxonomía.** Cada lectura es una de cuatro cosas, y ninguna se confunde con otra (`lib/read-state.ts`, `ReadState<T>`): `loaded` (lectura válida con contenido), `empty` (lectura válida y vacía: es un hecho, y solo aquí puede enseñarse «0» o «Sin …»), `unread` (no existe lectura válida porque **no se intentó**: un producto fuera del tope, o un dato que depende de otra lectura) y `error` (se intentó y falló, o la respuesta no tiene forma de lista). No hace falta ninguna categoría más; *stale* no aplica porque el Panel se renderiza en servidor y no conserva datos previos: ante el error se usa `error`. Nota de vocabulario heredado: el `UNREAD = "No se pudo leer"` de M45 (`revenue-view.ts`) significa, en esta taxonomía, `error`; no se renombra porque lo usan Finanzas y Proyectos.

**Cambio.** Se **reutiliza** `settle` (M45): ahora acepta el generador del texto de error (por defecto el de los ingresos), de modo que no hay un segundo sistema de lectura. `readList` lee, valida que la respuesta sea una lista y la clasifica. `lib/dashboard-reads.ts` hace las lecturas del Panel sobre una `DashboardSource` inyectable (la `api` real; dobles en las pruebas), sin `.catch`. `lib/dashboard-view.ts` recibe estados y devuelve estados discriminados: un `error` o un `unread` **nunca** produce un 0, un porcentaje, una suma ni un «Sin datos»; la demostración solo se activa con un log **válido y vacío**; la fase de un producto es indeterminada si alguna de sus cinco lecturas falló y `unread` si no se leyó; las solicitudes de demostración solo se construyen sobre productos con las cinco lecturas válidas; si una de las dos lecturas del backend de decisiones falla no hay lista parcial ni conteo. La interfaz dice cada fallo en su sitio (aviso resumen en la cabecera, aviso por tarjeta, «No disponible» en la cifra) con un botón **Reintentar** que hace `router.refresh()` **una vez por clic**: sin temporizadores, sin bucles y desactivado mientras reintenta. Si falla la lectura de productos el Panel sigue mostrando lo demás y solo la tarjeta de oportunidades queda en error.

**Textos para el usuario.** Nada técnico: ni estado HTTP, ni `fetch failed`, ni `ECONNREFUSED`, ni trazas, ni el detalle del backend. «No se pudieron cargar los datos» / «Datos no disponibles en este momento: los agentes, las aprobaciones.» También se neutralizó `revenueErrorText` (M45), que mostraba el estado y el detalle; el error de **contrato** de ingresos, que es texto nuestro escrito para verse («El contrato de ingresos cambió: …»), sigue visible.

**Lo que no cambia, a propósito.** Backend, contrato HTTP (un error es un 4xx/5xx; una lista vacía es `200 []`), modelo monetario, Supabase. El estado vacío válido sigue mostrando «Sin agentes», «0 · Nada esperando tu decisión» y «Todavía no hay catálogo».

**Pruebas.** Matriz por cada una de las 9 lecturas (datos, vacío válido, 401/403/404/422/500/503, red caída, conexión rechazada, cuerpo no JSON, carga útil inválida, recuperación, aislamiento, una petición por intento); las vistas sobre los cuatro estados; un barrido de las 256 combinaciones de agentes × ejecuciones × aprobaciones × revisiones; y `lib/read-boundary.test.ts`, una guarda arquitectónica acotada a las capas de lectura del Panel (ninguna forma de convertir un error en un vacío, todas las lecturas por `readList`/`settle`, la fuente solo declara lecturas, el reintento es manual, nada técnico llega al usuario) con un **trinquete** para las demás pantallas. Verificado además en el navegador con datos, vacío, fallos parciales, recuperación y backend caído.

**Deuda restante (no se corrige aquí).** El mismo patrón sigue en otras pantallas: **32 lecturas** de negocio (`approvals` 8, `status` 6, `ceo` 3, `economics` 3, `legal` 3, `audit` 2, `research` 2, el grafo `neural-nexus` 2, `agents`, `operations` y `sourcing` 1 cada una) y 3 de otra naturaleza (`auth-server` ×2, `kill-switch-control`). El trinquete (`REMAINING_SILENT_READS`) fija el número exacto por fichero y solo permite que mengüe; la infraestructura de este commit (`readList`, `ReadState`, `ReadErrorNotice`, `RetryButton`) está lista para reutilizarse. Otros textos técnicos de error fuera del Panel (por ejemplo, `ApiErrorAlert`) tampoco se tocan.

### 29. Addendum del Commit 7 (2026-10-14): la fecha de inicio es la del proyecto; la moneda no existe y no se inventa

Solo `ProjectOut` y la pantalla de Proyectos. Sin migración (la columna ya existe), sin cambio del modelo monetario.

**`created_at`.** `projects.created_at` existe desde la migración inicial (`DateTime(timezone=True)`, `NOT NULL`, fijado al insertar el proyecto por `TimestampMixin`) y `GET /api/projects` ya ordenaba por él, pero `ProjectOut` solo devolvía `id`, `objective_id`, `name` y `status`. Por eso la pantalla deducía la fecha de inicio de la entrada de auditoría `project.created`, que solo se lee cuando el proyecto tiene decisión: un proyecto sin decisión, o con la lectura de auditoría fallida, decía «Sin datos» o «No se pudo leer» aunque la fecha estuviera en la base. Ahora `ProjectOut.created_at` (obligatorio, sin valor por defecto) sale directamente de la fila y `startedAt = Date.parse(project.created_at)`, o `null` («Sin datos») solo si el valor no es una fecha. **No hay respaldo**: ni la auditoría, ni `updated_at` (cambia con cada estado), ni «ahora», ni la posición en la lista. La auditoría se conserva solo para fechar los hitos (`task.completed`).

**Zona horaria.** SQLite descarta la zona al leer; PostgreSQL (`timestamptz`) no. `ProjectOut` normaliza a UTC un valor sin zona (precedente: `_as_aware_utc` de `api/approvals.py`; todo lo que se guarda aquí es UTC), de modo que el cliente nunca lee `2026-09-12T10:00:05` como hora local. Un valor con zona conserva su instante.

**Moneda de `finance_validation`: no existe, no se añade.** `FinanceAgent` lee `unit_cost`, `sale_price`, `monthly_unit_sales` y `monthly_fixed_costs` de un `dict` libre (`objective.context["finance_validation"]`) y devuelve `margin`, `monthly_profit` y `finance_veto`: ni la entrada ni la salida ni ninguna columna llevan moneda, y nada valida ese `dict`. No existe una moneda global de configuración (el `currency = "EUR"` de `config.py` es `SpendLimitSettings`, el tope de gasto de un proveedor, y no tiene que ver con la proyección). Por eso la proyección sigue enseñándose **sin símbolo monetario** y sin sumarse con ninguna otra cifra, y no se crea columna, ni migración, ni se modifica el contrato. Si algún día el agente declara una moneda real, esta decisión se revisa a propósito: un test fija hoy que la evidencia no trae `currency`.

**Pruebas y guardas.** Backend: `tests/integration/test_project_created_at.py` (contrato exacto de claves, la fecha persistida, varios proyectos con orden distinto, no es `updated_at` ni «ahora», lista = detalle, zona UTC explícita, instante conservado, y la moneda ausente). Frontend: la fecha de inicio solo sale de `created_at` y no depende de la auditoría, `startedAtOf` devuelve `null` ante un valor no fechable sin recurrir a otra fuente, y una guarda acotada a las capas de Proyectos prohíbe `new Date()`, restas «hoy − N», fechas derivadas de la posición, códigos `CEO-0001` y cualquier moneda (`currency`, `EUR`, `€`, `formatEuro`).

**Deuda restante de M46:** Commit 8 (textos que afirman más de lo que el sistema sabe), 9 (docs: milestone 46 y `system-overview`) y la Fase B de Supabase.

### 30. Addendum del Commit 8 (2026-10-14): la interfaz no eleva el nivel de certeza de un dato

Solo texto, etiquetas e insignias del Control Center (sin cambio de backend, de contrato, de datos ni de lógica). Principio: **la interfaz no puede decir más de lo que el sistema sabe**; cambia el nombre de cada cosa, no la cosa.

**Método.** Barrido de solo código de los 222 ficheros de `app/`, `components/` y `lib/` con 17 familias de vocabulario de certeza (`real*`, `verific*`, `confirm*`, `aprob*`, `complet*`, `éxito`, `beneficio`, `margen`, `ingres*`, `cobr*`, `activ*`, `actual`, `final`, `segur*`, `list*`, `garant*`, `demo*`): ≈1.600 coincidencias, ninguna cambiada por coincidencia. La inmensa mayoría son identificadores (`success`, `active`, `ready`…), estados literales del backend o usos legítimos; **37 entradas exageraban** y se corrigieron.

**Qué se corrigió, por clase.**
- **«real» como «no es demo» / «existe en el backend»** (Agentes, Aprobaciones, Auditoría, Estado, Panel, Tienda, Marketing, Proveedores, Economía, Nexus): pasa a «del backend», «declarado», «guardado» o «medido en esta carga» según lo que de verdad es. «Real:» como prefijo de lo que sí viene del backend pasa a «Del backend:».
- **La insignia `verified` decía dos cosas.** Su texto («Dato verificado contra su fuente original») se aplicaba a 19 sitios donde solo significaba «el backend devolvió este registro». Esos pasan a la insignia **`recorded`** («Registro del backend»), neutral y sin pretensión de verificación; `verified` queda solo para el coste de una cotización cuyo proveedor consta como verificado por un tercero («Verificado por un tercero»). Es la única categoría de insignia nueva: ninguna existente decía «lo guarda el backend» sin elevarlo (`ledger` es solo dinero).
- **Una recomendación no es una aprobación.** `Decision.status = GO/NO_GO` lo sintetiza un motor sobre agentes simulados; la aprobación humana es `HUMAN_APPROVAL`. GO pasa de «Aprobada» a **«Favorable»** («recomienda avanzar; no una aprobación humana») y NO_GO de «Rechazada» a «No viable»; las validaciones derivadas de un análisis dicen «Sin bloqueo» o «Favorable»; la puerta legal de Tienda dice «Sin bloqueo».
- **Un estado técnico no es «activo».** `launch_status = READY` de una tienda es «Preparada», no «Activo»: nada está publicado.
- **Lo que existe no es lo que está validado.** «Economía validada», «Proveedor validado» y «Precio aprobado» pasan a «Economía analizada», «Proveedor seleccionado» y «Precio de venta del análisis». La creatividad «Aprobado» por una puntuación de demostración pasa a «Puntuación alta».
- **Una inferencia no es un resultado.** El backend no guarda el resultado de una acción de auditoría: «Éxito» se infería del nombre. Se dice **«Sin error registrado»** (la clave interna no cambia); «Evento verificado», «Eventos verificados» y «Última verificación» (la integridad es de demostración) pasan a «Evento del registro», «Eventos registrados» y «Última comprobación (demo)».
- **Certeza en el copy:** «datos verificados», «calidad verificada», «costes reales», «tiempo real» (Estado y Agentes: la página se carga una vez), «de verdad».
- **DEMO sin su etiqueta:** cada KPI y tarjeta de rendimiento de Marketing, las certificaciones y los documentos de Legal, la configuración por mercado y las pestañas de páginas y pruebas A/B de Tienda llevan ya su insignia DEMO; la vista previa de la tienda dice que reseñas y distintivos son «de ejemplo»; los veredictos fijos de las solicitudes de demostración de Aprobaciones se rotulan DEMO.
- **Un tercero no es «real».** Las señales de Investigación pasan de «Real (señales medidas)» con insignia `verified` a «Señales medidas (proxy de interés)» con `third_party`.

**Lo que se revisó y se deja, con su porqué.** El CFO y los ingresos (ADR 0030, ya vigilados por `origin-boundary`); el rótulo «Proveedor real» del origen del dinero (dato estructurado `provider_kind`, con su salvedad: no confirma liquidación); los usos de «real» que niegan o marcan lo pendiente («sin proveedores reales»); «Verificado por un tercero» (campo estructurado con «quién verificó» obligatorio); «SIN BLOQUEO EN LO DECLARADO» de Legal; el estado literal `Project.status = APPROVED`, que el orquestador asigna ante `GO` sin persona (se mantiene el valor del backend); `status-chip.tsx` y `kill-switch-control.tsx` (ficheros protegidos).

**Guarda.** `lib/certainty-boundary.test.ts` no es una lista negra de palabras: cada aparición de «real» en lo que se lee en pantalla se juzga **en su contexto** (un fragmento concreto de un fichero concreto, con su porqué) y solo en una lista cerrada de ficheros gobernados; lo que no está en la lista falla, y una entrada permitida que ya no existe también. Además fija, por contexto, que la insignia `verified` no se pinta sobre un registro, que una recomendación no se llama aprobación, que el resultado inferido pasa por `resultLabel`, que el DEMO no se pierde y que PLAN, declarado y registro siguen siendo tres cosas. Probada contra el código anterior (15 de sus 21 primeras comprobaciones fallaban) y con 44 mutaciones muertas.

**Deuda restante (no se corrige aquí).** Las derivaciones del frontend de la auditoría (`resultOf`, `criticalityOf`) son inferencias: se corrigió cómo se llaman, no la derivación. `Project.status = APPROVED` es un estado que el orquestador asigna solo. El contenido de ejemplo de la tienda (distintivos «Pago seguro», «Envío gratis») y los textos de `lib/demo/**` no se barrieron. `components/cash-flow-chart.tsx` («Saldo real») no se usa en ningún sitio. Las 35 lecturas silenciosas fuera del Panel, la Fase B y el Commit 9 siguen pendientes.

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
