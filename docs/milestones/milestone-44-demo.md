# Milestone 44 — Pedidos, cobros, reembolsos y fulfillment, simulados

**Fecha:** 02-10-2026 · **ADR:** [0028](../architecture/adr-0028-orders-payments-fulfilment-core.md)
(enmendada al cierre) · **Enmienda a:** [0011](../architecture/adr-0011-action-gate.md)
· [0024](../architecture/adr-0024-external-actions-lifecycle-and-unknown-outcome.md)
· [0025](../architecture/adr-0025-generic-idempotency-for-synchronous-routes.md)
· [0027](../architecture/adr-0027-approval-boundary-and-budget-authorisation.md)
· **Depende de:** [0003](../architecture/adr-0003-rls-deny-by-default.md)
· [0015](../architecture/adr-0015-multiple-real-sources-cost-and-usage-rights.md)
· [0018](../architecture/adr-0018-money-conversion-and-not-evaluable.md)
· [0022](../architecture/adr-0022-idempotent-pipeline-run-creation.md)
· [0023](../architecture/adr-0023-single-budget-source-and-absence-is-not-permission.md)
· [0026](../architecture/adr-0026-database-identity-guards.md)

**Presupuesto: 0 €. Ninguna cuenta, credencial, pasarela, proveedor ni transportista reales.** Ninguna llamada de red a un
tercero: los adaptadores son simulados y ni siquiera importan una librería de red (una prueba de arquitectura lo fija).
**Supabase no se ha modificado:** las migraciones de este milestone no están aplicadas en ella.

## La regla

**El dinero lo confirma un evento verificado, y la evidencia financiera nunca se descarta.** Ninguna ruta acepta un campo
«pagado»; el navegador no confirma nada; un cobro tardío, duplicado o de otro importe se registra tal cual aunque contradiga
al pedido, y el sistema avisa en lugar de «arreglarlo». Y una unidad que se ha comprado al proveedor no vuelve al pool.

## Qué se construyó

Los commits 1 a 11, más dos correcciones (8b y 10b), y este, el 12, que es solo documentación. Cada uno se publicó con su CI revisado
job por job; el del Commit 8 falló una vez por una prueba intermitente y se corrigió en un commit aparte; los commits 10b y 11 se
publicaron juntos y comparten el CI (run `37056659327`):

| # | Commit | Qué |
|---|---|---|
| 1 | `7f7a9d3` | ADR 0028 |
| 2 | `050c9c7` | observadores de transición en `ExternalActionService`: el dominio se mueve en la misma transacción que la acción |
| 3 | `1773628` | el gate gobierna por operación (coste por operación, permiso por acción, `COLLECT_PAYMENT`; `REFUND` no es gasto) |
| 4 | `2966b1e` | proveedores de pago y de fulfillment, con la política operativa de lo que declaran |
| 5 | `c0cc56a` | pedidos, sin datos personales y sin ninguna vía para marcar uno como pagado |
| 6 | `89eeef6` | intentos de cobro y eventos de pago verificados; solo un evento paga un pedido |
| 7 | `7a9b55a` | reembolsos: los ordena una persona, los acota la base de datos, los confirma un hecho verificado |
| 8 | `7b7d255` | fulfillment: las unidades las aparta la base de datos y una comprada no vuelve al pool |
| 8b | `cb58efb` | fix: perder una carrera de compra o envío es un 409, nunca un error interno |
| 9 | `22eef3f` | claves por intención en el frontend: una `Idempotency-Key` por intención y nunca una por clic |
| 10 | `7f959f9` | Operaciones muestra pedidos reales y dice lo que todavía no existe |
| 10b | `cca1472` | fix: un evento de reembolso verificado que coincide con el cierre del reembolso es evidencia, no un error |
| 11 | `b6acbd0` | invariantes, caminatas aleatorias, matriz de caídas y concurrencia sobre PostgreSQL |
| 12 | este | `docs: milestone 44` |

El estado final está descrito en el [§25 del resumen del sistema](../architecture/system-overview.md): 7 tablas, 13 rutas,
4 permisos nuevos, 3 observadores y 7 comandos de consola relacionados (4 de M44 y 3 de las acciones externas, ADR 0024).

## Qué es real y qué es demo

- **Real:** el dominio (pedidos, cobros, reembolsos, fulfillment), sus reglas y restricciones en la base de datos, la API, los
  permisos, la auditoría, la idempotencia y los observadores; todo probado sobre PostgreSQL.
- **Simulado:** la pasarela de pago (`simulated-payments`) y el proveedor y el envío (`simulated-fulfilment`). Un evento
  simulado se firma con una clave efímera por proceso y entra por **la misma puerta** que un webhook real. La entrega la confirma
  una persona; no hay transportista ni seguimiento de estado (la `tracking_reference` es solo la referencia que devuelve el
  proveedor simulado al enviar).
- **Operaciones** lee pedidos reales y lo dice («Datos reales · eventos simulados»). **Dashboard, CFO y Proyectos siguen
  mostrando pedidos inventados**, etiquetados como demostración (P1-2).
- **No existe:** cliente final, carrito, checkout, web pública, IVA/OSS, facturas, contabilidad, devoluciones físicas,
  seguimiento de envíos, bandeja de aprobación de pedidos, libro económico de ingresos, ningún adaptador real.

## Verlo funcionar

La demo recorre un pedido de principio a fin con la consola y la API, y lo enseña en Operaciones. Se comprobó paso a paso el
2026-10-02 sobre una base PostgreSQL local desechable (borrada al terminar); las salidas de abajo son las reales, con los
identificadores sustituidos. **Nunca la apuntes a Supabase.**

```bash
# 1. Una base PostgreSQL local, vacía, y las migraciones
cd backend
export DATABASE_URL="postgresql+psycopg://<usuario>:<clave>@127.0.0.1:<puerto>/<base_local_vacia>"
alembic upgrade head                        # ... -> b3c8f1a5d742 (head)
uvicorn app.main:app --port 8000            # en otra terminal, con el mismo DATABASE_URL
```

```bash
# 2. Un producto (basta uno del catálogo: este lo crea la investigación simulada) y un presupuesto
curl -s -X POST localhost:8000/api/research/runs -H "Content-Type: application/json" \
  -d '{"category":"home","keywords":["air fryer"],"max_results":1}'     # candidates[0].product_id
export AMAZONA_BOOTSTRAP=1                  # los comandos que cambian algo lo exigen
python -m app.cli authorise-budget --hard-limit 500       # budget authorised: hard limit 500.00
```

```bash
# 3. El pedido: sin datos personales (customer_ref opaca `sim_…`); el coste se declara porque desconocido no es cero
python -m app.cli create-test-order --product-id <product_id> --quantity 2 --unit-price 19.99 --unit-cost 8.00
#   order <order_id> created for sim_441ec3a6427a: 39.9800 EUR

# 4. El cobro: se abre en la pasarela simulada y se queda OPEN, esperando un hecho verificado
curl -s -X POST localhost:8000/api/orders/<order_id>/payments -H "Idempotency-Key: demo-pay-1"   # status: OPEN
python -m app.cli simulate-payment --order-id <order_id> --outcome succeeded
#   event <event_id>: applied          <- ahora (y solo ahora) el pedido está PAID

# 5. El fulfillment: una línea, dos unidades; comprar y enviar son acciones externas gobernadas
curl -s -X POST localhost:8000/api/orders/<order_id>/fulfillments -H "Content-Type: application/json" \
  -H "Idempotency-Key: demo-ful-1" -d '{"lines":[{"order_item_id":"<order_item_id>","quantity":2}]}'
curl -s -X POST localhost:8000/api/fulfillments/<fulfillment_id>/purchase -H "Idempotency-Key: demo-buy-1"   # PURCHASED
curl -s -X POST localhost:8000/api/fulfillments/<fulfillment_id>/ship     -H "Idempotency-Key: demo-ship-1"  # SHIPPED
curl -s -X POST localhost:8000/api/fulfillments/<fulfillment_id>/complete                                    # COMPLETED (lo confirma una persona)

# 6. Un reembolso parcial: lo ordena una persona y queda SENDING hasta que el proveedor lo confirme
curl -s -X POST localhost:8000/api/orders/<order_id>/refunds -H "Content-Type: application/json" \
  -H "Idempotency-Key: demo-ref-1" -d '{"payment_id":"<payment_id>","amount":{"amount":"10.00","currency":"EUR"},"reason":"customer_request"}'
python -m app.cli simulate-refund --refund-id <refund_id> --outcome succeeded
#   event <event_id>: applied          <- solo ahora el dinero se da por devuelto

# 7. Qué ocurrió: las acciones externas, los reconciliadores (no hay nada atascado) y el presupuesto
python -m app.cli show-actions --open                     # no open external actions
python -m app.cli reconcile-actions --older-than-minutes 60    # released (never sent): 0 | now unknown (may have been sent): 0
python -m app.cli reconcile-payment-events                # applied: nothing to apply
python -m app.cli show-budget                             # hard limit 500.00 | reserved 0.00 | committed 16.00 | spent 16.00
```

Con la API y el Control Center en marcha (`npm run dev`, <http://localhost:3000>), **Operaciones** enseña el pedido, con 39,98 €,
10,00 € devueltos y confirmados, el fulfillment «Entregado» y su historia con hechos fechados.

**Tres cosas que la demo deja ver** (las tres se comprobaron):

- **Sin clave, 428.** `curl -X POST …/ship` sin `Idempotency-Key` responde `428` con `"code":"idempotency_key_required"`. Repetir la compra con
  la **misma** clave devuelve el mismo resultado sin volver a comprar. Con otra clave sería una segunda petición, y el estado ya no la
  permite: 409 (diez compras con diez claves distintas a la vez dan un 200 y nueve 409, probado en la suite sobre PostgreSQL).
- **Desconocido no es cero.** Si el pedido se crea **sin** `--unit-cost`, `purchase` se deniega con «the cost of this action is
  unknown, and an unknown cost is not zero»: no se gasta nada que no se sepa cuánto cuesta.
- **Un cobro duplicado no se descarta.** Con un pedido cuyo primer intento caducó (`simulate-payment --outcome expired`), un segundo
  intento se abre y se cobra (`PAID`); si después llega el éxito tardío del primero
  (`simulate-payment --payment-id <primer_intento> --outcome succeeded`), el sistema lo **registra** como `DUPLICATE_CAPTURE` (25,00 € reales
  en el pago 1, el pedido sigue `PAID`) y el pedido queda `attention_required` con el motivo `duplicate_capture`. Un reembolso
  posterior lo podría devolver. El sistema avisa; no lo arregla por su cuenta.

Para cargar muchos pedidos en distintos estados a la vez (completado, resultado desconocido, pendiente de cobro, reembolso enviado, compra
fallida) se pueden sembrar con los servicios reales y los ayudantes de `backend/tests/integration/` (`fulfilment_test_support.py`,
`payment_test_support.py`, `order_test_support.py`), que es como se verificó visualmente el Commit 10 con 5 pedidos: nada se escribe a mano
en las tablas.

## Verificación

- **CI (run `37056659327`, el de `b6acbd0`): `success`, job por job y paso por paso.** Backend: ruff, mypy, migración a PostgreSQL limpio y
  **3517 pruebas** (1 warning). Control Center: lint, tipos de rutas, TypeScript, **487 pruebas** y build.
- **En local, sobre PostgreSQL:** `python -m pytest` y `pytest` a secas, **3517 pasan** con las dos; `ruff check .` y `mypy app` (263 ficheros) limpios;
  `eslint`, `tsc --noEmit`, `npm test` (487) y build aislado limpios. Sin PostgreSQL local se omiten las pruebas que lo necesitan: un verde sin
  él no prueba carreras.
- **Invariantes** tras cada paso de 60 caminatas aleatorias (con proveedores que fallan de todas las formas del contrato) y 15 de
  recuperación, sobre dinero, estados y la frontera «nada enviado / posiblemente enviado / desconocido» entre la acción y el dominio.
- **Matriz de caídas:** 5 puntos de caída × 4 dominios (cobro, reembolso, compra, envío). En ninguna se repite lo que el proceso muerto
  pudo haber enviado; el proveedor sigue con una sola ejecución.
- **Concurrencia real sobre PostgreSQL** (cada hilo con su sesión, tras una barrera): 20 clics con la misma clave abren un solo cobro y 20 con
  claves distintas, exactamente uno; capturas de 12 pedidos a la vez; captura contra fallo del mismo cobro; 6 trabajadores con el mismo evento;
  enviar contra cancelar contra abandonar; una **tormenta** de 6 semillas × 5 hilos × 60 operaciones que, tras el arreglo `cca1472`, se
  repitió 14 veces seguidas sin fallos.
- **Mutación:** 13 roturas deliberadas de garantías de M44 (quitar un compare-and-set, saltarse el hash del evento, permitir sobreasignar,
  cambiar de clave en cada reintento…), **13 detectadas**. Una —cancelar un pedido con dinero capturado— sobrevivía a toda la suite hasta
  que se escribió la prueba que faltaba.
- **Migraciones** con datos existentes sobre PostgreSQL local (20 comprobaciones): base vacía → `head` (7 tablas con RLS), datos sembrados en
  `a9d2e7b4c136` → `head` con los datos intactos, `downgrade -1` y vuelta a subir, `downgrade` hasta `e1b8d4a62f37` y vuelta a subir. Los
  *downgrades* borran los datos de las tablas que quitan: es por diseño y solo se ejecutan en local.
- **Operaciones en el navegador**, con base vacía y con pedidos sembrados por los servicios; el log del backend mostró solo lecturas. Repetido
  en esta documentación (02-10-2026) con la demo de arriba.
- **Este commit** es solo documentación: no cambia código, así que no cambia ninguno de los números de arriba.

## Llamadas externas y coste

**Ninguna.** Ninguna pasarela, proveedor, transportista, API de terceros ni consulta de red. Todas las bases usadas fueron PostgreSQL
local en `127.0.0.1`; ninguna prueba toca Supabase (una prueba de arquitectura lo impide y otra escanea los tests buscando referencias
reales de proyecto). **Gasto: 0 €.**

## Lo que NO se verificó

- **Las migraciones de M44 sobre Supabase/PostgreSQL real**: no están aplicadas. Se ejercieron sobre PostgreSQL local y sobre el de CI.
  Tampoco la RLS de estas tablas en la base real (sí que existe y se verifica en las migraciones).
- **Ningún adaptador real**: que un PSP o un proveedor se comporte como el contrato (firma de webhooks, reintentos, consulta de estado,
  claves de idempotencia) está por demostrar contra un sandbox real. La batería de contrato de los proveedores existe (`backend/tests/integration/order_provider_contract_test_support.py`), pero hoy solo la ejecutan los simulados.
- **Carga y volumen**: nada se midió con miles de pedidos. `GET /api/orders` calcula la atención por pedido con varias consultas cada uno.
- **El cableado de React** del Control Center (no hay entorno de DOM): se verificó a mano y con guardas de texto; las funciones puras de `lib/` sí tienen pruebas.
- **El rol real contra Supabase** (403 con un token de REVIEWER/SYSTEM) lo cubren los inventarios con tokens fabricados, no la base real.

## Desviaciones y decisiones de interpretación

- **No hay umbral automático de fallos.** El encargo mencionaba «tras 3 fallos confirmados alcanza `FAILED`»; el contrato aprobado (ADR 0028 §6)
  no lo tiene: `FAILED` es siempre una decisión humana tras ≥ 1 fallo confirmado de compra, y tres fallos dejan el fulfillment en `READY` con
  `failed_attempts = 3` (está probado). **El propietario decidió el 02-10-2026 no añadir un umbral**; uno exigiría una ADR propia (0029).
- **Un commit más de los previstos (`cca1472`)**: lo exigió un defecto real que encontró la tormenta concurrente del propio Commit 11 (un 500
  espurio en un webhook de reembolso). Separado y con su prueba determinista.
- **Operaciones sin el informe del agente de operaciones** (política de devoluciones y ticket de ejemplo): se retiró en el Commit 10 por no
  tener datos reales detrás. Sigue en `GET /api/products/{id}/operations`; **el propietario decidió no reponerlo**.
- **El Commit 11 tocó un fichero del Commit 9** (`test_idempotency_http_intent.py`, para compartir el ayudante de carreras) y renombró los módulos de
  apoyo a la convención `*_test_support.py` que exige una guarda del repositorio.
- **El CI del Commit 8 falló una vez** por una prueba intermitente que dependía de una carrera; no se reproducía en local en 25 intentos. Se corrigió
  en `cb58efb` en un commit aparte, con su autorización.
- **Verificación visual de Operaciones** con el backend lanzado desde la consola y no con `preview_start`, porque el backend no está en
  `.claude/launch.json` y no se quiso modificar un fichero versionado.

## Defectos corregidos durante el milestone

Detalle en la [ADR 0028, enmiendas E1 a E3](../architecture/adr-0028-orders-payments-fulfilment-core.md#enmiendas-cierre-del-milestone-44-2026-10-02):

1. Un pedido reembolsado se podía seguir enviando (el servicio leía cobros desactualizados). `7b7d255`.
2. **Interbloqueo real** entre comprar y cancelar → `FOR NO KEY UPDATE` en los cinco bloqueos del pedido. `7b7d255`.
3. Una petición que **perdía** una carrera de compra o envío recibía un 500 y dejaba la clave de idempotencia en `UNKNOWN_OUTCOME` → 409 limpio. `cb58efb`.
4. Un evento de reembolso verificado que coincidía con el cierre del reembolso por una persona o por la reconciliación producía un 500 en el webhook → se conserva
   como evidencia (`CONFLICT` o `STALE`). `cca1472`.
5. Un hueco de prueba, no de código: cancelar un pedido con dinero capturado **sin pagar** (captura de otro importe) no estaba cubierto. Commit 11.

## Limitaciones conocidas y deuda

Clasificación de la auditoría de solo lectura del cierre (código, ADR, 3517 pruebas). **No hay ningún P0**: no se encontró ningún
defecto que pierda o duplique dinero, permita un efecto externo repetido ni exponga datos personales.

### P1 — bloquean conectar nada real

| ID | Hallazgo |
|---|---|
| P1-1 | **Ningún reconciliador está programado.** `reconcile-actions`, `reconcile-payment-events` y `resolve-action` son comandos manuales. Sin ellos se quedan atascados: acciones `PENDING` (reserva retenida), cobros `OPENING` o `UNKNOWN_OUTCOME` (bloquean cobros nuevos), eventos `RECEIVED`, reembolsos `UNKNOWN_OUTCOME` (bloquean otros del mismo cobro) y fulfillments `UNKNOWN_OUTCOME` |
| P1-2 | **Dashboard, CFO y Proyectos siguen mostrando pedidos inventados** (`buildOrders`), etiquetados como demostración. El principio «dato real o vacío» no se cumple en esos tres paneles |
| P1-3 | **No existe ningún adaptador real** de pago ni de fulfillment, y la política de arranque de `staging` y `production` exige adaptadores no simulados: esos entornos **no arrancan** hasta que existan (intencionado; no es un defecto) |

### P2

| ID | Hallazgo |
|---|---|
| P2-1 | **Defecto confirmado, no corregido.** `ExternalActionStateError` no tiene tratamiento HTTP: solo el servicio de fulfillment la convierte en 409. `PaymentAttemptService.start` y `RefundService.request` no la atrapan, así que una carrera entre el barrido de huérfanas y el ejecutor con un umbral demasiado agresivo sería un 500 y dejaría la clave de idempotencia en `UNKNOWN_OUTCOME`. Inalcanzable con el uso documentado (umbral > arriendo); la consola sí la traduce |
| P2-2 | **Defecto confirmado, no corregido.** Operaciones lee como máximo 500 pedidos (`ORDERS_LIMIT`) y **no avisa** de que trunca |
| P2-3 | Un cobro `OPEN` solo se cierra por evento del proveedor: no existe `payment.cancel` ni caducidad |
| P2-4 | Un reembolso `SENDING` sin confirmar se marca `refund_unconfirmed` tras 1 h, pero nada lo reconcilia (no hay consulta de estado de reembolsos al proveedor) |
| P2-5 | El webhook no tiene limitación de frecuencia ni lista de IPs (sí tope de tamaño, firma, tolerancia y deduplicación) |
| P2-6 | Sin bandeja de aprobación de pedidos: `REQUIRE_APPROVAL` devuelve 409 y no ejecuta (ADR 0028 §7) |
| P2-7 | Sin umbral automático para abandonar un fulfillment: decidido, ver «Desviaciones» |

### P3

| ID | Hallazgo |
|---|---|
| P3-1 | `RuntimeError` defensivos que serían 500 si dispararan, inalcanzables hoy por restricciones (`payments/projection.py`, `refund_projection.py`, `payments/service.py`, `allocation.py`) |
| P3-2 | Los observadores de cobro y reembolso no ponen `applied_at` al cerrar con éxito (el de fulfillment sí): incoherente, inofensivo |
| P3-3 | Claves foráneas sin índice: `order_items.supplier_id`, `order_items.supplier_quote_id`, `payments.duplicate_of_payment_id`, `payment_events.refund_id`, `fulfillments.supplier_id` |
| P3-4 | Índices redundantes cubiertos por una compuesta: `ix_order_items_order_id`, `ix_fulfillment_items_fulfillment_id`, `ix_payments_order_id` |
| P3-5 | `GET /api/orders` calcula la atención pedido a pedido: con 500 pedidos son miles de consultas |
| P3-6 | `idempotency_records` no tiene retención ni purga (la clave no caduca por diseño) y no hay comando para listar las bloqueadas |
| P3-7 | La anotación `float` de `_money` en `api/orders.py` (la convierte con `Decimal(str())`) |
| P3-8 | Desajustes antiguos modelo ≠ migración, ajenos a M44 (`alembic check`): `created_at` anulable en varias tablas, `pipeline_reviews.kind`, un índice y la FK `pipeline_runs.job_id` |
| P3-9 | `ExternalAction.amount` y el libro de presupuesto siguen en `float` (frontera heredada, nombrada una a una en una guarda) |
| P3-10 | El Control Center no tiene entorno de DOM |
| P3-11 | Las intenciones del frontend viven en `sessionStorage` de **una pestaña**: otra pestaña o dispositivo genera otra clave |
| P3-12 | **Hallazgo de esta documentación.** `python -m app.cli simulate-payment` con un `--event-id` ya usado imprime un *traceback* (`ConflictError`) en lugar de un error limpio: el simulador regenera el contenido del evento, y la misma id con otro contenido se rechaza (con razón: es un 409 en el webhook). El comando solo traduce `BootstrapError`. La deduplicación real está probada con la suite, no con la consola |

Además de lo anterior: **no hay formularios de M44** en el Control Center (las funciones de `api.ts` esperan la clave de intención como parámetro
obligatorio), no hay conversión de moneda ni IVA, y 200 ficheros antiguos siguen sin formatear con `ruff format` (el CI solo exige `ruff check`).

## Decisiones del propietario al cierre

Preguntadas el 2026-10-02, antes de escribir este documento:

1. **Umbral automático de fallos: no.** `FAILED` sigue siendo una decisión humana.
2. **P2-1 y P2-2: se dejan para M45**, documentados, sin commits `fix:` previos.
3. **El informe del agente de operaciones no se repone** en Operaciones.
4. **Dashboard, CFO y Proyectos pasan a pedidos reales en M45**, con el libro económico de ingresos.
5. **Sin decidir:** cuándo y con qué procedimiento se aplican las migraciones de M44 a Supabase (requiere autorización expresa y un
   procedimiento aparte).

## Criterios y orden recomendado para M45

Propuesta de la auditoría, por valor y riesgo; **el propietario aún no ha fijado el alcance de M45** salvo lo marcado como decidido arriba.

1. **Programar los reconciliadores** como trabajos del runtime asíncrono existente (P1-1). Sin ello no se puede conectar nada real.
2. **Libro económico de ingresos** alimentado por capturas y reembolsos verificados, y **convertir Dashboard, CFO y Proyectos a pedidos reales**
   (P1-2; decidido para M45). El dinero real debe tener una sola fuente de verdad, igual que el presupuesto.
3. **Bandeja de aprobación de pedidos** (ADR 0028 §7), que unifique las autorizaciones de un solo uso (ADR 0027).
4. **Formularios de M44 en el Control Center** con claves de intención.
5. **P2-1 y P2-2** (decidido para M45) y P2-3 a P2-5. Recomendación: **no empezar por un PSP real.**

Un *criterio de salida* razonable para M45: ningún estado que pueda bloquear un pedido (`OPENING`, `UNKNOWN_OUTCOME`, `RECEIVED`, `PENDING`) puede
quedarse sin que un reconciliador programado lo mire, y ninguna pantalla muestra un pedido que no existe en la base.

## Bloqueos antes de conectar algo real

- **Un proveedor de abastecimiento o fulfillment:** un adaptador con idempotencia honesta y, si puede, consulta de estado; batería de conformidad en verde;
  derechos, coste y política de gasto escritos **antes** de la primera llamada (ADR 0015); reconciliadores programados y un procedimiento humano para
  `resolve-action`; formularios con claves de intención; decidir P2-1.
- **Una pasarela (PSP):** adaptador de pago con webhooks firmados (gestión y rotación de la clave de firma); `payment.cancel` o caducidad (P2-3); consulta de
  estado de reembolsos (P2-4); limitación de frecuencia del webhook (P2-5); observabilidad de `attention_required`; simulacros del kill switch; IVA/OSS y
  facturas (fuera de M44); y las migraciones de M44 aplicadas a Supabase bajo su procedimiento, con la RLS verificada en la base real.
- **Un transportista real:** seguimiento, plazos y devoluciones físicas **no existen**; hay que diseñarlos.
- **La web pública (KOVA):** carrito, checkout y cuentas de cliente están fuera de M44, RGPD y datos personales incluidos.
- **El primer euro real:** todo lo anterior, más un presupuesto autorizado por el propietario en el entorno real (`authorise-budget`, con su límite), reconciliación
  probada contra el sandbox del proveedor, Dashboard/CFO/Proyectos con datos reales, el libro de ingresos y la **autorización expresa** del propietario para ese primer
  gasto. Hoy no se cumple ninguno y el gasto acumulado es 0 €.

## Qué queda fuera de M44, expresamente

Web pública KOVA, carrito, checkout y cuentas de cliente; pasarela, proveedor o transportista reales; datos personales de clientes (RGPD); IVA/OSS, facturas y
contabilidad; `payment.cancel`; devoluciones físicas; seguimiento de envíos; bandeja de aprobación de pedidos; libro económico de ingresos; programación de los
reconciliadores; conversión de Dashboard, CFO y Proyectos a datos reales. Son M45 o posteriores.
