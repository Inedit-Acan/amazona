# Invariantes y pruebas de caos del hardening pre-M44 (fase 2)

Qué frases tienen que seguir siendo ciertas pase lo que pase, y qué prueba fija cada una. Si una de estas pruebas falla, no es
un test frágil: es una de estas frases que ha dejado de valer. Decisiones de fondo en las
[ADR 0022–0027](system-overview.md#8-índice-de-adrs).

Todas las pruebas con carreras usan **barreras explícitas** y PostgreSQL efímero; ninguna es probabilística. Los proveedores
son falsos y cuentan los efectos que habrían tenido «en el mundo real». Un guardia global (`tests/conftest.py`) hace fallar
cualquier test que intente salir de la máquina.

## Invariantes (`backend/tests/integration/test_economic_invariants.py`)

| | Frase | Prueba |
|---|---|---|
| I1 | Una autorización humana produce como máximo un efecto | `test_i1_one_human_authorisation_produces_at_most_one_effect` |
| I2 | Un evento económico se contabiliza como máximo una vez | `test_i2_*` (índices únicos de la base y liquidación única del servicio) |
| I3 | Una solicitud idempotente produce como máximo una ejecución lógica | `test_i3_*` (objetivo y ejecución del pipeline) |
| I4 | Un retry nunca crea gasto adicional por sí solo | `test_i4_*` (caída antes de llamar; reanudar con un resultado desconocido) |
| I5 | `UNKNOWN_OUTCOME` nunca se transforma automáticamente en `FAILED` seguro | `test_i5_an_unknown_outcome_is_never_turned_into_a_safe_failure_automatically` |
| I6 | Un presupuesto no puede reservarse por encima del límite mediante concurrencia | `test_i6_a_budget_cannot_be_reserved_above_its_limit_by_concurrency` |
| I7 | CEO y pipeline ven la misma disponibilidad | `test_i7_the_ceo_and_the_pipeline_see_the_same_availability` |
| I8 | La ausencia de presupuesto no equivale a permiso | `test_i8_*` (gate y CEO) |
| I9 | La ausencia de rol no equivale a permiso fuera de simulación | `test_i9_the_absence_of_a_role_is_not_a_permission_outside_a_simulation` |
| I10 | Una lectura no produce escritura salvo contrato explícito | `test_i10_a_read_produces_no_write_on_any_get_route` (todas las rutas `GET`, sobre base vacía) |
| I11 | El kill switch no puede crearse accidentalmente leyendo | `test_i11_*` |
| I12 | Ningún proveedor real puede ser llamado durante los tests | `tests/unit/test_network_is_blocked_in_tests.py` |

## Pruebas de caos (`backend/tests/integration/test_chaos_scenarios.py`)

| # | Escenario | Qué se afirma |
|---|---|---|
| 1 | 20 solicitudes idénticas a la vez | un solo efecto; las demás reciben la respuesta o un 409 |
| 2 | misma clave, otro contenido | 409 y no se ejecuta nada |
| 3 | el worker cae después de reservar | `PENDING`; el barrido libera con seguridad |
| 4 | el worker cae antes de llamar (frontera cruzada) | `UNKNOWN_OUTCOME`; el barrido no lo «arregla»; el gate lo veta |
| 5 | el proveedor ejecuta y da timeout | desconocido; la reserva se queda; la ejecución `BLOCKED` |
| 6 | el proveedor no ejecuta y da timeout | desconocido hasta que una consulta lo aclara; entonces se libera |
| 7 | la respuesta llega tarde | cierra una vez; una segunda entrega no cambia nada |
| 8 | reintento en otro worker | una sola **petición** al proveedor |
| 9 | dos workers consumen la misma aprobación | uno la consume; los demás, error |
| 10 | presupuesto casi agotado y dos acciones compiten | una cabe, la otra se deniega |
| 11 | el CEO y el pipeline compiten por el saldo | una sola reserva |
| 12 | el kill switch se activa entre autorizar y ejecutar | no sale nada; al reanudar, la misma operación y la misma clave |
| 13 | la aprobación caduca entre la reserva y la ejecución | se libera una vez y ya no autoriza |
| 14 | la misma petición tras reiniciar el proceso | la respuesta original |
| 15 | un adaptador sin idempotencia | sin clave y nunca reintentado a ciegas |
| 16 | coste declarado 0 | no reserva nada y completa |
| 17 | coste desconocido | se deniega, también en simulación |
| 18 | ausencia de presupuesto | real: se deniega; simulación declarada: pasa sin mover el libro |
| 19 | permisos desconocidos | fuera de simulación se deniega |
| 20 | recuperación de `UNKNOWN_OUTCOME` | por consulta, la ejecución termina sin repetir el efecto |

## Otras barreras que los sostienen

- Ciclo de vida de las acciones: `test_external_action_lifecycle.py`, `test_external_action_concurrency.py`,
  `test_pipeline_external_actions.py`, `test_provider_idempotency_in_pipeline.py`, `test_adapter_contract.py`.
- Idempotencia de las rutas: `test_idempotent_routes.py`, `test_idempotent_external_reads.py`,
  `test_idempotency_concurrency.py`, `test_post_route_classification.py` (falla si aparece un `POST` sin clasificar).
- Garantías de la base de datos: `test_database_identity_guards.py`, `test_database_identity_concurrency.py` y las pruebas de
  migración de `tests/unit/test_migration_*.py` (subir, bajar, volver a subir, con datos, con duplicados, RLS).
- Frontera entre bandejas: `tests/unit/test_approval_boundary.py`, `test_approval_boundary_behaviour.py`.

## M45: el registro de ingresos y la reconciliación (Commit 12)

Lo de M44 y de M45 se completa con el oráculo del registro y el recorrido de punta a punta
([`system-overview.md` §27](system-overview.md#27-panel-finanzas-y-proyectos-sobre-datos-verificados-y-cómo-se-prueba-milestone-45-commits-9-a-12)).
El mapa de **qué prueba fija cada frase** —y que falla si esa prueba desaparece— es
`backend/tests/integration/test_m45_coverage_map.py`. Lo nuevo:

| Frase | Prueba |
|---|---|
| Ninguna entrada del registro sin un `PaymentEvent` válido, y cada cobro cuadra con sus entradas | `test_m45_end_to_end.py`, `test_m45_walk.py` (oráculo tras cada paso) |
| Un `UNKNOWN_OUTCOME` solo lo cierra una consulta autoritativa o una persona; ningún barrido ni reconciliación lo toca | `test_m45_walk.py`, `test_m45_chaos.py` |
| Una caída después de `begin_call` es desconocida y ningún barrido programado la libera | `test_m45_chaos.py` |
| Un lease vencido en la reconciliación: otro worker recupera el tick y el dinero se cuenta una vez | `test_m45_chaos.py` |
| Los eventos en cualquier orden dan el mismo ingreso verificado; el que no cabe es evidencia, no una entrada | `test_m45_chaos.py` |
| Ningún `GET` escribe, ni sobre una base **llena** de datos de todos los dominios | `test_m45_end_to_end.py` |
| El tope del reembolso se cumple **capa a capa** (servicio, `reserve`, `CHECK` de la base) | `test_m45_end_to_end.py` |
| Ningún fichero de código contiene un byte de control (un `\b` que se vuelve 0x08 desactiva una expresión sin dar error) | `tests/unit/test_no_control_bytes_in_sources.py` |
| Lo retirado de las pantallas no vuelve; PLAN no se viste de verificado; un error de lectura no es un dato | `apps/control-center/lib/m45-boundary.test.ts` |
