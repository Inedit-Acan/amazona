# ADR 0027: Dos bandejas con una frontera explícita — y la autorización del presupuesto sigue siendo del propietario en la consola

- **Estado:** Aceptada
- **Fecha:** 2026-10-01
- **Depende de:** [ADR 0007](adr-0007-production-security.md) (seguridad de producción: los roles y el primer propietario no se conceden por HTTP), [ADR 0011](adr-0011-action-gate.md), [ADR 0023](adr-0023-single-budget-source-and-absence-is-not-permission.md), [ADR 0024](adr-0024-external-actions-lifecycle-and-unknown-outcome.md)
- **Milestone:** hardening pre-M44, fase 2 (fases 6 y 7)
- **Enmendada por:** [ADR 0028](adr-0028-orders-payments-fulfilment-core.md) (Milestone 44: nuevos espacios de referencias de las acciones externas; sigue sin haber bandeja de aprobación de pedidos; ver «Enmienda (Milestone 44)» al final)

## Contexto

Existen dos «bandejas» de aprobación humana, `Approval` y `PipelineReview`, y se muestran juntas en la pantalla de
Aprobaciones. La pregunta no es si fusionarlas —no se fusionan «porque sí»— sino si **significan lo mismo**. Si significan lo
mismo, hay una duplicidad arquitectónica peligrosa; si no, el peligro es otro: que alguien (o un agente) use una por la otra.
Y aparte: la autorización del presupuesto es un comando de consola; ¿es eso lo que debe seguir siendo antes de M44?

## Parte 1 — `Approval` y `PipelineReview`

### Auditoría semántica

| | `Approval` | `PipelineReview` · `ACTION_GATE` | `PipelineReview` · `POST_HOC` |
|---|---|---|---|
| **Qué autoriza** | una **decisión** del CEO (`decision_id`, acción, importe) | **un efecto de un paso** de una ejecución (`run`, `step`, `action`) | nada: es una anotación sobre una ejecución **ya terminada** |
| **Quién la crea** | `CEOOrchestrator._maybe_create_approval` cuando la decisión pide aprobación humana | `PipelineOrchestrator._await_approval` cuando el gate responde `REQUIRE_APPROVAL` | `PipelineOrchestrator._settle` cuando la evaluación de riesgo pide revisión |
| **Quién la consume** | nadie la «consume»: se **resuelve** (`approve`/`reject`/caducar) por la API | el paso, al arrancar: `APPROVED → CONSUMED`, en la misma transacción (ADR 0011, enmienda) | nadie |
| **Estados** | `PENDING`, `APPROVED`, `REJECTED`, `EXPIRED`, `CANCELLED` | `PENDING`, `APPROVED`, `CONSUMED`, `REJECTED` | `PENDING`, `APPROVED`, `REJECTED` |
| **Caducidad** | sí: 24 h (`expires_at`); caducar es una resolución con compare-and-set | **no**: una pregunta espera hasta que alguien contesta | no |
| **Actor** | `resolved_by`, con `actor_name(identity, declared, settings)` | igual | igual |
| **Audit trail** | `approval.requested` / `approve` / `reject` / `expire` | `pipeline.await_approval`, `pipeline_review.approve` / `reject` / `consume` | `pipeline.run` y la resolución |
| **Presupuesto** | **lo mueve**: el CEO reserva el importe al pedirla (`approval:{id}`); aprobar lo compromete, rechazar o caducar lo libera | **no lo mueve**: el gasto lo reserva el paso al empezar, con su `ExternalAction` (`action:{id}`, ADR 0024) | no |
| **Reintentos** | una sola resolución (compare-and-set); tras caducar, no sirve | **un solo uso**: tras `CONSUMED` no vale para reanudar, rehacer ni reintentar; un fallo tras consumirla exige otra | — |
| **Relación con el paso** | **ninguna**: el CEO no ejecuta pasos | **exacta**: una por `(run, step)`, una pendiente a la vez (índice único, ADR 0026) | ninguna |

### Decisión: A — dos conceptos legítimamente distintos

No hay duplicidad: responden a preguntas distintas. `Approval` es **gobernanza de una decisión** (¿seguimos con este
proyecto y con este dinero?) y lleva su propio dinero reservado y su caducidad. `PipelineReview` es **permiso de un efecto
concreto** (¿se puede publicar *esto*, *ahora*, *una vez*?) y no toca el libro. Compartir pantalla es una decisión de
presentación (para quien decide son la misma bandeja de entrada), no de datos.

El peligro real es el contrario: usar una por la otra **por accidente**. Por eso la frontera se hace cumplir con pruebas,
no con una convención:

1. **Ningún módulo del pipeline** (`pipeline`, `gates`, `jobs`, `actions`) importa el modelo, el servicio o la API de
   `Approval`; **ningún módulo del CEO** (`ceo`, `approvals`, `api/approvals`) importa `PipelineReview`, el pipeline, el gate
   ni las acciones (`tests/unit/test_approval_boundary.py`).
2. Las **referencias del libro** viven en espacios de nombres que solo escribe su dueño: `approval:` solo el CEO y la
   resolución de la aprobación; `action:` solo el modelo de la acción externa; `pipeline_step:` solo el pipeline.
3. **Comportamiento** (`tests/integration/test_approval_boundary_behaviour.py`): aprobar una decisión del CEO no desbloquea
   un paso del pipeline; resolver una revisión del pipeline no toca las aprobaciones ni el libro; resolver una aprobación
   del CEO no toca ninguna revisión; una revisión `POST_HOC` aprobada **no** autoriza nada.
4. Los dos modelos llevan en su docstring la frontera y apuntan aquí.

### Un hallazgo: `ApprovalService` en memoria

`app/approvals/service.py::ApprovalService` es un modelo **en memoria** del Milestone 1: no persiste nada, el CEO lo
construye y **no lo usa**, y ninguna ruta autoriza a través de él. Es una tercera «aprobación» que existe solo en el
código, y la más peligrosa de usar por error (parece el ciclo de vida de verdad). **No se ha eliminado** en esta fase (lo
construyen tests y el constructor del orquestador; quitarlo es un refactor sin urgencia), pero su docstring lo dice sin
ambigüedad y una prueba fija que solo `approvals/service.py` y `ceo/orchestrator.py` lo mencionan y que ninguna ruta de la
API lo importa. Queda como deuda: eliminarlo cuando se toque el orquestador del CEO.

### Lo que cambiaría la decisión

Pasaría a **B** (duplicidad peligrosa) si una tercera clase de autorización necesitara el mismo ciclo de vida (consumo de
un solo uso con caducidad y reserva a la vez): entonces habría que unificar el *mecanismo* (consumo atómico, caducidad,
auditoría) conservando los dos *conceptos*. Mientras no ocurra, unificar mezclaría una decisión con dinero reservado y un
permiso de un solo uso, que se resuelven, caducan y se auditan de maneras distintas.

## Parte 2 — Autorización del presupuesto: la consola sigue siendo lo correcto antes de M44

Opciones evaluadas: **A)** seguir con la consola · B) endpoint interno protegido · C) pantalla mínima en Finanzas · D) otro
patrón existente.

**Decisión: A.** Seguir con `AMAZONA_BOOTSTRAP=1 python -m app.cli authorise-budget`. No se construye nada nuevo.

Por qué:

- Es el patrón de `grant-role` ([ADR 0007](adr-0007-production-security.md)): el dinero y el poder del propietario no se
  conceden por un endpoint HTTP. Un endpoint que fije el techo de gasto es un endpoint que puede **subirlo**; con la consola,
  quien lo sube tiene acceso a la máquina que tiene la base de datos, que es exactamente quien debe poder hacerlo.
- No hay un gasto real que habilite todavía: ningún proveedor real está conectado. Autorizar un techo es un acto que ocurre
  una vez por entorno y antes del primer euro, no una operación frecuente que justifique una interfaz.
- Una pantalla o un endpoint exigen identidad fuerte (OWNER verificado, confirmación explícita, protección contra CSRF), y
  construirlos sin una necesidad inmediata es superficie de ataque a cambio de comodidad.

### Los requisitos, uno a uno

| Requisito | Cómo se cumple hoy |
|---|---|
| solo OWNER/ADMIN | solo quien ejecuta en la máquina con la base de datos y `AMAZONA_BOOTSTRAP=1`; no hay ruta HTTP |
| intención explícita | la variable `AMAZONA_BOOTSTRAP=1` y `--hard-limit` obligatorio; sin ella, `BootstrapError` |
| auditoría antes/después | `budget.authorise` con `before` y `after` |
| actor y marca de tiempo | `cli:<usuario>` y `created_at` de la fila de auditoría |
| importe | `hard_limit` y `soft_limit`, antes y después |
| **moneda y ámbito** | **añadidos en esta fase**: `currency` (`EUR`, la moneda contable), `scope` (el nombre del presupuesto) y `period` van en `before` y `after` |
| hard limit | obligatorio, `> 0`, y `soft_limit ≤ hard_limit` |
| sin «presupuesto infinito» silencioso | `inf`, `nan`, importes con más de dos decimales y todo lo que supere **10 000 000** se rechazan antes de escribir (ADR 0026); no existe un presupuesto sin techo |
| idempotente | autorizar dos veces el mismo importe deja una fila de presupuesto y una de saldo (`test_authorising_the_same_budget_twice…`) |
| concurrente | lock transaccional por presupuesto y restricciones únicas (ADR 0026); doce autorizaciones a la vez dejan un presupuesto y un saldo |
| sin default permisivo | sin presupuesto autorizado, un gasto real se deniega; el sistema nunca lo crea solo (ADR 0023) |

### Cuándo habría que revisarlo

Cuando alguien que **no** tenga acceso a la máquina tenga que autorizar o cambiar el techo. Entonces la opción B (un endpoint
interno) tendría que exigir, como mínimo: rol `OWNER` verificado (no declarado), `Idempotency-Key` obligatoria, un cuerpo que
**repita** el importe como confirmación explícita, el mismo `budget.authorise` en la auditoría con el actor verificado, y
una cota superior que no se pueda saltar desde la propia petición. La opción C solo tiene sentido encima de B.

## Consecuencias

- Quien añada una ruta o un servicio que mezcle las dos bandejas rompe una prueba, no una convención.
- La moneda del presupuesto es la contable (`EUR`) y no una columna: un presupuesto en otra moneda no existe todavía. Si hiciera
  falta, es una migración y una decisión de producto.
- La consola exige acceso a la máquina: es una limitación deliberada, no una carencia.

## Alternativas descartadas

- **Fusionar `Approval` y `PipelineReview`**: mezclaría una decisión con dinero reservado y caducidad con un permiso de un
  solo uso sin caducidad. Si se unifica algún día, será el mecanismo, no el concepto (ver arriba).
- **Eliminar `ApprovalService` ahora**: es un refactor sin riesgo funcional pero con coste de revisión; la protección que
  importa (que nadie lo use por error) ya la dan el docstring y la prueba.
- **Un endpoint o una pantalla para el presupuesto «por si acaso»**: superficie de ataque sin una necesidad que la justifique.

## Enmienda (Milestone 44): nuevos espacios de referencias, y la bandeja que sigue sin existir

La [ADR 0028](adr-0028-orders-payments-fulfilment-core.md) añade tres espacios de nombres de las **acciones externas** (no del libro de presupuesto): `order_payment:`,
`order_refund:` y `order_fulfilment:`, cada uno dueño de un observador que mueve su parte del dominio (ver la enmienda de la
[ADR 0024](adr-0024-external-actions-lifecycle-and-unknown-outcome.md)). La frontera de esta ADR no cambia: el libro sigue
escribiéndose con `approval:` (solo el CEO), `action:` (solo el modelo de la acción externa) y `pipeline_step:` (solo el
pipeline), y la prueba de frontera lo sigue fijando. Una compra a un proveedor con coste conocido gasta el presupuesto que el
propietario autorizó en la consola, y por el mismo libro; un reembolso **no** es gasto y no lo toca.

Ninguna operación de un pedido crea una `Approval` ni una `PipelineReview`. Cuando el gate responde `REQUIRE_APPROVAL` para
una operación de un pedido, M44 devuelve 409 con los motivos y **no ejecuta nada**: una bandeja de aprobación de pedidos
sería la tercera clase de autorización de un solo uso, que es el disparador que la sección «Lo que cambiaría la decisión»
prevé para unificar el *mecanismo* de las dos bandejas. Queda para el Milestone 45. La autorización del presupuesto sigue siendo un comando de consola
del propietario.
