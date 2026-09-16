# ADR 0005: Orquestador de pipeline para la cadena de descubrimiento de Fase 3

- **Estado:** Aceptada
- **Fecha:** 2026-09-16
- **Depende de:** [ADR 0001](adr-0001-orchestrator-vs-ceo.md), [ADR 0003](adr-0003-rls-deny-by-default.md), [ADR 0004](adr-0004-agent-capability-pairs-validate-vs-discover.md)

## Contexto

Fase 3 (Milestones 2-11) construyó 8 agentes "descubrir-muchos" operativos
(research, sourcing, economics, legal_compliance, ecommerce, marketplace,
marketing, operations) más el Agente CFO — cada uno con su propio
servicio, tabla+migración+RLS, API y página en el Control Center, por
diseño de ADR 0004: ninguno se cablea en el grafo de tareas de
`planner.py`/`decision_engine.py`. El cierre de Fase 3
(`docs/milestones/milestone-9-demo.md`, "Cierre de Fase 3") documentó
explícitamente que el recorrido completo (Research → ... → Operations)
es **manual hoy**: un humano visita cada página del Control Center y
copia IDs reales (`product_id`, `supplier_quote_id`, ...) de la salida
de un paso al formulario del siguiente. Los tests e2e existentes
(`test_operations_to_full_chain_flow.py`, `test_cfo_aggregation_flow.py`)
demuestran que la cadena funciona correctamente extremo a extremo, pero
son ellos mismos quienes hacen de "humano" — encadenando llamadas HTTP
secuenciales a mano.

Fase 4 (Linear, "Integración y pruebas") pide en 4.1 (IVA-29) integrar
los agentes en un entorno común y en 4.2 (IVA-30) tests de flujo
completo. Verificado en el código: no existe ningún mecanismo interno
que encadene automáticamente los 9 pasos — se confirma la lectura de
que 4.1 es un cambio de arquitectura real, no una verificación de que
"ya está conectado".

## Decisión

Se construye un **nuevo componente de orquestación, separado de
`CEOOrchestrator`/`planner.py`/`decision_engine.py`**: un
`PipelineOrchestrator` (`backend/app/pipeline/service.py`) que, dado
`category` + parámetros de negocio (mercado, plataformas, precio de
venta, presupuesto diario, etc.), invoca en secuencia los 9 servicios ya
existentes (`ResearchService` → `SourcingService` →
`EconomicAnalysisService` → `LegalComplianceService` →
`EcommerceStorefrontService` → `MarketplaceListingService` →
`MarketingCampaignService` → `OperationsService` → `CFOService`),
seleccionando automáticamente el mejor candidato de research
(`opportunity_score` descendente) y la mejor cotización de sourcing
(`total_landed_cost_per_unit` ascendente) — el mismo criterio de ranking
que cada agente ya aplica internamente — y enhebrando `product_id` y los
demás IDs reales entre pasos exactamente como lo hacía el humano.

Se persiste un nuevo registro **`pipeline_runs`** (tabla propia, RLS
activado desde su propia migración, per ADR 0003) que guarda, por cada
ejecución: el `correlation_id` propio del pipeline, el `product_id`
elegido, el estado global (`COMPLETED` o `PARTIAL`), y un JSON `steps`
con el resultado de cada paso (su propio `correlation_id`, id de
entidad, y `recommendation`/`status`) — sin sustituir los
`correlation_id` individuales que cada servicio ya genera y audita por
su cuenta.

**Ningún paso detiene la cadena por un `NO_GO`/`BLOCKED` intermedio** —
mismo comportamiento que ya existe hoy entre servicios (economics
devolviendo `NO_GO` no impide hoy que un humano siga adelante con legal,
ecommerce, etc.; marketing incluso propaga automáticamente el `BLOCKED`
de marketplace). El pipeline solo se detiene si un paso no puede
ejecutarse en absoluto (p. ej. research no encuentra ningún candidato
para la categoría) — ese caso se registra como `PARTIAL` con el paso y
el motivo. Los controles humanos que decidan **cuándo actuar** sobre un
`NO_GO` agregado se formalizan en Milestone 14 (IVA-33), no aquí.

`planner.py`, `decision_engine.py` y `CEOOrchestrator` **no se
modifican**. El pipeline es un componente nuevo y paralelo — no una
extensión del grafo de validación de Milestone 1.

## Alternativas consideradas

1. **Extender dinámicamente el grafo de tareas de `planner.py`** para
   incorporar los 9 pasos de Fase 3 (la opción que el propio cierre de
   Milestone 9 dejó anotada como posible). Rechazada: mezclaría dos
   dominios con contratos distintos — la validación de un `Objective`
   abstracto (contexto arbitrario, sin fila de `Product` necesaria) y el
   descubrimiento concreto sobre entidades de catálogo ya persistidas
   (`Product`, `SupplierQuote`, ...) — y tocaría el núcleo de decisión
   GO/NO-GO/HUMAN_APPROVAL ya probado y estable desde Milestone 1, que
   ADR 0004 protege explícitamente.
2. **Encadenar mediante llamadas HTTP internas** desde la capa de API
   (el propio backend haciendo `requests` a sus propios endpoints).
   Rechazada: overhead y acoplamiento innecesarios cuando los servicios
   ya pueden invocarse directamente en proceso, compartiendo la misma
   sesión de base de datos y transacción de auditoría.

## Consecuencias

- Una sola llamada (`POST /api/pipeline/runs`) reemplaza el recorrido
  manual de 9 páginas — sin eliminar ninguna de las 9 páginas ni APIs
  individuales, que siguen existiendo para uso independiente/depuración.
- Cada servicio conserva su propio `correlation_id`/auditoría; el nuevo
  `pipeline_runs.correlation_id` es un nivel de trazabilidad adicional
  que los agrupa, no un reemplazo.
- La selección "mejor candidato"/"mejor cotización" es determinista y
  documentada — mismo criterio que cada agente ya usa internamente para
  rankear, así que el pipeline no introduce ninguna heurística nueva.
- Si en el futuro se decide detener la cadena automáticamente ante un
  `NO_GO` (en vez de solo registrarlo), eso es un cambio de
  comportamiento que debe revisarse explícitamente — no se asume aquí.
