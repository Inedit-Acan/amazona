# AMAZONA / KOVA — Plan maestro de continuación para Claude Code

**Repositorio:** `Inedit-Acan/amazona`  
**Objetivo de este documento:** continuar el desarrollo del proyecto desde su estado actual, priorizando el paso de simulación a operación real sin romper la arquitectura existente.

---

## 0. Regla principal

No reconstruir AMAZONA desde cero.

La arquitectura actual debe conservarse salvo que exista una razón técnica demostrable para cambiarla. El objetivo de la siguiente etapa es **sustituir progresivamente las capas simuladas por integraciones reales**, reforzar seguridad y preparar ejecución autónoma/semiautónoma 24/7.

Principios obligatorios:

1. No inventar datos reales.
2. No presentar datos `mock`, `demo` o estimados como si fueran reales.
3. No conectar sistemas que puedan producir efectos externos reales sin controles de seguridad previos.
4. Mantener trazabilidad completa mediante `correlation_id`, auditoría y estados persistidos.
5. Toda acción con riesgo económico, legal, reputacional o de gasto debe pasar por controles explícitos.
6. No eliminar capacidades existentes salvo que exista una sustitución funcional superior y documentada.
7. Antes de modificar una parte importante, leer el código actual y sus ADRs/milestones relacionados.
8. Mantener compatibilidad con el Control Center existente.
9. No duplicar lógica de negocio entre backend y frontend.
10. Priorizar adaptadores reales sobre nuevas pantallas.

---

# 1. Estado actual validado del proyecto

AMAZONA dispone actualmente de:

- Backend FastAPI.
- SQLAlchemy + Alembic.
- PostgreSQL / Supabase.
- Redis provisionado en infraestructura local.
- Control Center en Next.js + React + TypeScript.
- Sistema de agentes especializados.
- `CEOOrchestrator`.
- `PipelineOrchestrator`.
- Agente CFO.
- Decision Engine.
- Human approvals.
- Budget ledger.
- Kill switch.
- Audit log.
- `correlation_id`.
- Incident management.
- Monitoring básico.
- GitHub Actions.
- Tests backend y frontend.
- Sistema visual avanzado.
- 12 paneles principales rediseñados.
- Milestones que llegan al menos hasta el 28.

Arquitectura funcional principal:

```text
Research
  ↓
Sourcing
  ↓
Economics
  ↓
Legal
  ↓
Ecommerce
  ↓
Marketplace
  ↓
Marketing
  ↓
Operations
  ↓
CFO
```

También existe un flujo paralelo:

```text
Objective
  ↓
CEOOrchestrator
  ↓
4 agentes de validación
  ↓
Decision Engine
  ↓
GO / REVIEW / NO_GO / HUMAN_APPROVAL
```

---

# 2. Distinción obligatoria: lo implementado no equivale todavía a operación real

La aplicación actual debe tratarse como un **sistema funcional de simulación/orquestación**, no como una empresa autónoma productiva.

Actualmente siguen siendo simulados, entre otros:

- Product Research.
- Tendencias de mercado.
- Proveedores.
- Precios de proveedores.
- Legal/compliance.
- Cambios regulatorios.
- Rendimiento publicitario.
- Marketing.
- Pedidos.
- Tracking.
- Clientes.
- Devoluciones.
- Atención al cliente.
- Contabilidad real.
- Facturación.
- Pagos.
- Marketplace real.
- Tienda pública KOVA.
- Logística real.

Ejemplos actuales de fuentes mock:

```text
backend/app/ai/mock_trends_provider.py
backend/app/ai/mock_supplier_directory.py
backend/app/ai/mock_regulatory_directory.py
```

No eliminar estos mocks inmediatamente. Deben permanecer como proveedores `demo/test`, pero **nunca mezclarse con producción**.

---

# 3. Problema más urgente: seguridad

## 3.1 Situación actual

Actualmente existe:

```python
require_auth: bool = False
```

en:

```text
backend/app/core/config.py
```

La autenticación existe parcialmente mediante:

```text
backend/app/auth/
```

pero no está aplicada globalmente.

Hay endpoints mutadores o críticos que actualmente pueden ejecutarse sin identidad autenticada.

Ejemplos:

```text
POST /api/research/runs
POST /api/sourcing/runs
POST /api/economics/runs
POST /api/legal/runs
POST /api/ecommerce/runs
POST /api/marketing/runs
POST /api/operations/runs
POST /api/cfo/runs
POST /api/pipeline/runs
POST /api/pipeline/kill-switch
```

Además, en varios endpoints el `actor` procede del body y no de una identidad verificada.

Esto es aceptable para desarrollo local, pero **no debe llegar a producción**.

---

# 4. FASE P0 — Seguridad de producción

Esta fase debe completarse antes de conectar APIs reales, dinero, publicidad, marketplaces, compras, pagos o proveedores reales.

## P0.1 — Modos de entorno

Crear una separación inequívoca:

```text
development
test
demo
staging
production
```

Requisitos:

- `development`: puede permitir mocks.
- `test`: fixtures controlados.
- `demo`: datos demo claramente etiquetados.
- `staging`: integraciones reales limitadas/sandbox.
- `production`: prohibidos mocks/demo para decisiones operativas.

Añadir validaciones al arrancar la aplicación.

Ejemplo conceptual:

```python
if environment == "production" and mock_provider_enabled:
    raise RuntimeError(...)
```

---

## P0.2 — Autenticación global

Objetivo:

> En producción, ningún endpoint mutador debe poder ejecutarse sin usuario autenticado.

Crear una estrategia coherente de auth para toda la API.

Preferencia:

- Supabase Auth.
- JWT verificado por JWKS.
- `sub` como identidad canónica.

Endurecer validación JWT:

- verificar firma;
- verificar expiración;
- verificar issuer;
- verificar audience;
- verificar proyecto esperado;
- rechazar tokens incompletos.

No mantener:

```python
verify_aud = False
```

en producción.

---

## P0.3 — RBAC

Implementar roles claros.

Propuesta inicial:

```text
OWNER
ADMIN
OPERATOR
ANALYST
REVIEWER
VIEWER
SYSTEM
```

Permisos mínimos:

### OWNER

Todo.

### ADMIN

Administración general excepto acciones reservadas al propietario.

### OPERATOR

Ejecutar pipelines/agentes y operaciones permitidas.

### ANALYST

Investigación y análisis sin side effects.

### REVIEWER

Aprobar/rechazar decisiones.

### VIEWER

Solo lectura.

### SYSTEM

Identidad interna para procesos y workers.

No confiar en campos `actor` enviados por frontend para acciones protegidas.

---

## P0.4 — Proteger especialmente

Estas operaciones deben tener control reforzado:

```text
kill switch
approvals
pipeline reviews
budget changes
future purchases
future ad activation
future marketplace publishing
future payment actions
future supplier orders
future refunds
```

El kill switch debe requerir:

```text
authenticated identity
+
authorized role
+
audit entry
```

---

## P0.5 — Auditoría de seguridad

Toda acción sensible debe registrar:

```text
actor
role
action
resource
before
after
correlation_id
timestamp
source
```

Si más adelante existe una acción externa:

```text
external_provider
external_request_id
external_response_id
approval_id
decision_id
```

---

# 5. FASE P0 — Separación DEMO / REAL

Existe actualmente uso deliberado de:

```text
lib/demo/
```

para completar visualmente paneles.

Eso puede mantenerse durante desarrollo.

Pero crear una regla fuerte:

> Un build de producción no puede depender de datos demo.

Implementar:

- etiqueta explícita de procedencia;
- validación en CI;
- test que falle si código de producción importa `lib/demo`;
- proveedores mock desacoplados mediante interfaces/adapters;
- configuración explícita del provider activo.

Modelo deseado:

```text
ProductIntelligenceProvider
├── MockProductIntelligenceProvider
├── RealProductIntelligenceProvider
└── SandboxProductIntelligenceProvider
```

Mismo patrón para proveedores, legal, marketing, etc.

---

# 6. FASE P1 — Job system y operación 24/7

Redis existe en infraestructura, pero todavía falta una verdadera ejecución distribuida.

Objetivo:

```text
HTTP request
   ↓
Job
   ↓
Queue
   ↓
Worker
   ↓
Agent
   ↓
Result/Event
   ↓
Next Job
```

No ejecutar pipelines largos íntegramente dentro del request HTTP.

## Requisitos

Crear:

```text
Job
JobAttempt
Worker
Queue
JobEvent
```

Cada job debe tener:

```text
id
type
status
payload
correlation_id
attempt
max_attempts
created_at
started_at
completed_at
failed_at
error
result_reference
```

Estados recomendados:

```text
PENDING
QUEUED
RUNNING
WAITING_APPROVAL
RETRYING
COMPLETED
FAILED
CANCELLED
BLOCKED
```

Implementar:

- retry con backoff;
- idempotency keys;
- timeout;
- dead-letter queue;
- cancelación;
- reanudación;
- heartbeat worker;
- locks;
- detección de worker muerto.

No introducir una infraestructura exagerada. Evaluar opciones compatibles con Python/FastAPI/Redis.

Documentar decisión mediante ADR.

---

# 7. FASE P1 — Hard Gates antes de side effects

El pipeline actual continúa incluso con resultados `NO_GO`/`BLOCKED`.

Eso puede mantenerse para análisis, pero no para acciones externas.

Separar:

## ANALYSIS ACTIONS

Pueden continuar para completar diagnóstico:

```text
research
sourcing
economics
legal
forecast
simulation
comparison
```

## SIDE EFFECT ACTIONS

No pueden ejecutarse libremente:

```text
publicar producto
activar publicidad
gastar dinero
comprar proveedor
realizar pago
enviar pedido
hacer refund
cambiar precio real
enviar comunicación contractual
```

Crear:

```text
ActionGate
```

Entrada:

```text
economic decision
legal decision
risk status
budget status
human approval
permissions
environment
```

Salida:

```text
ALLOW
DENY
REQUIRE_APPROVAL
```

Ejemplo:

```text
Legal = NO_GO
=> DENY publish
=> DENY ads
=> DENY purchase
```

---

# 8. FASE P1 — Product Intelligence real

Ésta debe ser la primera gran conversión de mock → real.

Actualmente:

```text
MockTrendsProvider
```

Objetivo:

crear un sistema capaz de detectar productos/oportunidades reales.

No depender de una única fuente.

Arquitectura deseada:

```text
Product Intelligence
├── Trends
├── Search demand
├── Marketplace demand
├── Competition
├── Social signals
├── Price distribution
├── Review/problem mining
└── Trend persistence
```

Crear una interfaz abstracta.

Ejemplo conceptual:

```python
class ProductSignalProvider(Protocol):
    def discover(...)
    def get_demand(...)
    def get_competition(...)
```

## Datos que deben conservarse por señal

```text
provider
source
query
timestamp
market
value
confidence
raw_reference
method
```

Nunca almacenar solo un número final sin procedencia.

---

# 9. Product scoring

El actual `opportunity_score` puede evolucionar.

No cambiarlo sin:

1. documentar fórmula;
2. introducir versionado del score;
3. tests;
4. datos explicables.

Propuesta futura:

```text
OpportunityScore v2
=
Demand
× Trend durability
× Margin potential
× Supplier availability
× Competition factor
× Regulatory feasibility
× Logistics feasibility
× Scalability
```

No implementar fórmula arbitraria aún.

Primero construir fuentes reales.

---

# 10. FASE P1 — Supplier Intelligence real

Actualmente:

```text
MockSupplierDirectory
```

Convertirlo en sistema de sourcing real mediante adaptadores.

Datos mínimos por proveedor:

```text
supplier_id
name
country
city
website/source
verified status
product match
unit price
currency
MOQ
lead time
Incoterm
shipping options
payment terms
certifications
dropshipping/direct ship
custom packaging
returns
reliability evidence
last checked
```

Distinguir:

```text
supplier claim
third-party verified
AMAZONA estimate
unknown
```

No marcar un proveedor como “verified” sin explicar qué significa.

---

# 11. Supplier Risk

Crear progresivamente un sistema de riesgo:

```text
identity risk
financial risk
quality risk
delivery risk
legal risk
fraud risk
dependency risk
geopolitical/logistics risk
```

No convertirlo inicialmente en un único score opaco.

Mantener dimensiones explicables.

---

# 12. FASE P1 — Legal Intelligence real

Actualmente:

```text
MockRegulatoryDirectory
```

Debe sustituirse progresivamente por fuentes verificables.

Prioridad para UE/España:

```text
EUR-Lex
European Commission
ECHA
Safety Gate
Access2Markets
BOE
autoridades nacionales relevantes
```

Cada requisito legal debe conservar:

```text
jurisdiction
regulation
article/reference
effective_date
source_url/reference
retrieved_at
requirement
product_scope
confidence
status
evidence
```

Nunca emitir:

```text
"100 % legal"
```

La salida debe ser algo parecido a:

```text
PASS
REVIEW_REQUIRED
BLOCKED
UNKNOWN
```

El sistema Legal ayuda a detectar y estructurar requisitos, no sustituye revisión profesional humana cuando sea necesaria.

---

# 13. FASE P2 — KOVA

Separación conceptual obligatoria:

```text
KOVA = ecommerce público / cara al cliente
AMAZONA = sistema operativo empresarial
```

No convertir KOVA en una simple página interna del Control Center.

Arquitectura:

```text
                 KOVA
      ┌────────────────────────┐
      │ Web pública            │
      │ Producto               │
      │ Checkout               │
      │ Cuenta cliente         │
      │ Pedido                 │
      └───────────┬────────────┘
                  │
                  ▼
              AMAZONA
      ┌────────────────────────┐
      │ Product Intelligence   │
      │ Suppliers              │
      │ Economics              │
      │ Legal                  │
      │ Marketing              │
      │ Operations             │
      │ CFO                    │
      │ CEO                    │
      └────────────────────────┘
```

---

# 14. Store Builder

El actual agente ecommerce genera estructura/contenido.

Convertirlo progresivamente en:

```text
ProductPageDefinition
StorefrontDefinition
CheckoutDefinition
SEOContent
LegalContentReferences
AnalyticsConfiguration
```

KOVA debe consumir una representación estructurada, no HTML arbitrario generado sin contrato.

Ejemplo:

```json
{
  "product": {},
  "hero": {},
  "benefits": [],
  "proof": [],
  "faq": [],
  "shipping": {},
  "returns": {},
  "seo": {}
}
```

La UI pública renderiza ese contrato.

---

# 15. FASE P2 — Pagos y pedidos

No implementar hasta completar P0.

Modelo mínimo futuro:

```text
Customer
Cart
Order
OrderItem
Payment
PaymentEvent
Fulfillment
Shipment
Return
Refund
```

Flujo:

```text
KOVA
 ↓
checkout
 ↓
payment provider
 ↓
payment confirmed
 ↓
Order
 ↓
ActionGate
 ↓
Supplier / fulfillment
 ↓
Shipment
 ↓
Delivery
```

Toda operación debe ser idempotente.

Nunca confiar únicamente en respuesta del navegador para marcar un pago como completado.

Usar webhooks verificados.

---

# 16. Modelo sin stock propio

Mantener como principio del proyecto:

```text
primero vender
↓
cobrar
↓
comprar al proveedor
↓
proveedor envía cuando sea viable
```

No asumir que esto siempre es legal/logísticamente viable.

Cada proveedor/producto debe declarar si soporta:

```text
direct shipping
dropshipping
blind shipping
custom packaging
tracking
returns
EU return address
SLA
```

Stock anticipado solo debe habilitarse mediante política específica de riesgo y aprobación.

---

# 17. FASE P2 — Marketing real

Sustituir progresivamente:

```text
MockAdPerformanceDirectory
```

por adaptadores externos.

Separar:

```text
Marketing Planning
Marketing Execution
Marketing Measurement
```

El agente puede recomendar.

El executor ejecuta.

Nunca permitir que el agente llame directamente a plataformas con presupuesto ilimitado.

Crear límites:

```text
daily budget
campaign budget
account budget
product budget
max CPC
max CAC
max spend without approval
```

---

# 18. Feedback loop real

Cuando existan ventas:

```text
Ad
 ↓
Visit
 ↓
Add to cart
 ↓
Checkout
 ↓
Purchase
 ↓
Margin
 ↓
Return/refund
 ↓
Net profit
```

Estos datos deben regresar a:

```text
Product Intelligence
Economics
Marketing
CEO
CFO
```

La métrica principal no debe ser únicamente ROAS.

Preferir:

```text
contribution margin
net margin
cash impact
return rate
repeat purchase
```

---

# 19. FASE P2 — Operations real

Sustituir el pedido ficticio actual.

Construir:

```text
order management
supplier dispatch
tracking
delivery
returns
support
incident handling
```

Integraciones mediante adapters.

No acoplar `OperationsAgent` directamente a proveedores/carriers.

Patrón:

```text
OperationsAgent
      ↓
Action
      ↓
OperationsExecutor
      ↓
Provider Adapter
```

---

# 20. FASE P3 — CFO real

Mantener el CFO actual como sistema analítico hasta que existan transacciones reales.

Cuando existan:

```text
orders
payments
refunds
supplier invoices
ad spend
fees
taxes
shipping
```

crear un ledger económico serio.

No mezclar:

```text
estimated
committed
accrued
paid
received
refunded
```

Estados financieros futuros:

```text
P&L
Cash Flow
Balance summary
Accounts payable
Accounts receivable
Tax estimates
```

Facturación real debe usar herramientas compatibles con requisitos legales aplicables.

---

# 21. Problema de transacciones del pipeline

Actualmente muchos servicios hacen su propio:

```python
db.commit()
```

Esto permite persistencia parcial si un pipeline falla.

No necesariamente debe eliminarse, pero hay que hacerlo explícito.

Crear modelo robusto:

```text
PipelineRun
PipelineStep
PipelineAttempt
```

Por step:

```text
PENDING
RUNNING
COMPLETED
FAILED
BLOCKED
SKIPPED
```

Permitir:

```text
retry step
resume run
cancel run
```

y preservar resultados ya válidos.

No intentar envolver en una sola transacción SQL un proceso que en el futuro incluirá llamadas externas largas.

---

# 22. Idempotencia

Antes de acciones reales, introducir idempotency.

Especialmente:

```text
payments
supplier purchase
marketplace publishing
ad creation
refund
email
shipment
```

Cada acción externa debe tener:

```text
idempotency_key
status
provider
external_id
request_hash
```

---

# 23. Arquitectura de adapters

Cada integración externa debe tener una frontera clara.

Ejemplo:

```text
app/integrations/
├── product_intelligence/
├── suppliers/
├── regulatory/
├── payments/
├── marketplaces/
├── ads/
├── shipping/
└── accounting/
```

Ningún agente debería depender directamente de SDKs externos.

Patrón:

```text
Agent
 ↓
Domain Service
 ↓
Port/Interface
 ↓
Adapter
 ↓
External API
```

Esto permite:

- mock;
- sandbox;
- real;
- fallback;
- test.

---

# 24. Observabilidad

Ampliar progresivamente:

```text
correlation_id
job_id
pipeline_run_id
agent_execution_id
external_request_id
```

Métricas:

```text
latency
success rate
error rate
retry rate
cost per execution
external API cost
tokens if LLM used
jobs queued
jobs stalled
worker health
```

No añadir observabilidad ficticia al panel Estado.

Construir backend primero.

---

# 25. Cost Control

Antes de introducir LLMs o APIs comerciales, añadir:

```text
provider
operation
units
estimated_cost
actual_cost
currency
correlation_id
```

Crear límites:

```text
per agent
per run
per day
per provider
per project
```

El CFO debe poder consumirlos más adelante.

---

# 26. Uso de LLMs

La arquitectura actual dice:

> sin LLM en el camino de decisión.

Mantener esta filosofía para decisiones críticas.

LLMs pueden utilizarse para:

```text
research synthesis
document extraction
copy generation
supplier email drafting
legal text summarization
creative generation
support drafting
```

No deben ser la única fuente para:

```text
legal gate
payment authorization
budget approval
supplier payment
refund
tax calculation
```

La decisión crítica final debe apoyarse en datos estructurados y políticas deterministas.

---

# 27. Versionado de decisiones

Cuando cambien motores o scores, persistir versión:

```text
decision_engine_version
score_model_version
policy_version
agent_version
```

Una decisión histórica debe seguir siendo explicable aunque el código cambie.

---

# 28. README y documentación

Actualizar inmediatamente:

```text
README.md
docs/architecture/system-overview.md
```

Problema actual:

documentan estado hasta Milestone 15 aunque el repo alcanza Milestone 28.

El README debe incluir:

```text
estado actual
qué es real
qué es mock
modo demo
modo producción
arquitectura
cómo ejecutar
seguridad
roadmap
```

No afirmar que un módulo es “real” si usa fixtures.

---

# 29. Dependencias Python reproducibles

Frontend ya tiene:

```text
package-lock.json
```

Backend actualmente usa rangos `>=`.

Adoptar lock reproducible.

Evaluar:

```text
uv
```

o alternativa adecuada.

Objetivo:

misma instalación en:

```text
dev
CI
staging
production
```

---

# 30. Git y forma de trabajo

No realizar una macro-reescritura.

Trabajar por milestones pequeños.

Cada milestone debe contener:

```text
objetivo
problema
alcance
fuera de alcance
archivos afectados
migraciones
tests
security impact
rollback
verification
```

Un commit lógico por milestone.

Cuando exista una decisión arquitectónica importante:

```text
ADR
```

---

# 31. Tests obligatorios

Por cada nuevo módulo:

```text
unit
integration
negative cases
authorization
idempotency when relevant
```

Para adapters reales:

```text
mock adapter tests
sandbox integration tests
failure tests
rate-limit tests
timeout tests
```

Nunca ejecutar acciones económicas reales desde CI.

---

# 32. Primera secuencia de trabajo recomendada

No avanzar todavía a Product Intelligence real.

Primero ejecutar esta secuencia.

---

## MILESTONE 29 — Production Security Foundation

Objetivos:

1. Separar ambientes.
2. Auth global en producción.
3. RBAC.
4. Proteger endpoints mutadores.
5. Proteger kill switch.
6. Proteger pipeline reviews.
7. Quitar identidad declarativa en producción.
8. Endurecer JWT.
9. Tests de autorización.
10. Documentar arquitectura.

Entregable:

```text
ADR-0007-production-security.md
```

o siguiente número libre.

Acceptance criteria:

```text
una petición no autenticada no puede ejecutar ningún mutador en production
VIEWER no puede mutar
ANALYST no puede usar kill switch
REVIEWER puede resolver approvals autorizadas
ADMIN/OWNER pueden manejar kill switch
actor de auditoría procede de identidad autenticada
```

---

## MILESTONE 30 — Demo / Production Isolation

Objetivos:

1. Provider interfaces.
2. Registrar provider activo.
3. Bloquear mocks en production.
4. Bloquear `lib/demo` en production.
5. Provenance uniforme.
6. CI validation.

Acceptance criteria:

```text
production no arranca con MockTrendsProvider
production no arranca con MockSupplierDirectory
production no arranca con MockRegulatoryDirectory
frontend production no importa lib/demo
```

---

## MILESTONE 31 — Async Job Runtime

Objetivos:

1. Job model.
2. Queue abstraction.
3. Redis worker.
4. Retries.
5. Heartbeat.
6. Cancel.
7. Job API.
8. Job UI básica en Estado.

No migrar todo el pipeline todavía.

Primero ejecutar una tarea simple async.

---

## MILESTONE 32 — Async Pipeline

Mover `PipelineOrchestrator` a jobs.

Cada step debe quedar persistido.

Permitir:

```text
retry
resume
cancel
```

---

## MILESTONE 33 — Action Gate

Crear hard gates.

No conectar todavía servicios externos de gasto.

Tests completos sobre:

```text
Legal NO_GO
Economics NO_GO
REVIEW
budget denied
approval missing
kill switch off
```

---

## MILESTONE 34 — Product Intelligence Adapter Architecture

No conectar aún 20 proveedores.

Crear primero el contrato.

Implementar:

```text
Mock adapter
Real adapter #1
```

Persistir procedencia.

---

## MILESTONE 35 — Product Intelligence Real v1

Primera investigación real.

Requisitos:

```text
fuente real
fecha
mercado
signal provenance
confidence
raw references
```

Comparar resultados contra mock.

No eliminar mock.

---

# 33. No hacer todavía

Hasta terminar P0/P1 inicial, NO:

- activar campañas publicitarias reales;
- realizar compras;
- conectar pagos productivos;
- publicar automáticamente productos;
- automatizar refunds;
- enviar pedidos a proveedores;
- otorgar autonomía económica;
- dar acceso público al backend;
- permitir ejecución remota sin RBAC.

---

# 34. Objetivo de arquitectura a medio plazo

```text
                           ┌──────────────┐
                           │     KOVA     │
                           │ Public Store │
                           └──────┬───────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────┐
│                         AMAZONA                            │
│                                                            │
│   CEO / Policies / Decision Engine / Human Approval         │
│                         │                                  │
│                         ▼                                  │
│                    Action Gate                             │
│                         │                                  │
│   ┌─────────────────────┼──────────────────────────────┐   │
│   │                     │                              │   │
│ Research            Suppliers                       Legal  │
│ Economics           Ecommerce                      Ads     │
│ Operations          CFO                            Support  │
│   │                     │                              │   │
│   └─────────────────────┼──────────────────────────────┘   │
│                         │                                  │
│                      Jobs/Queue                            │
│                         │                                  │
│                      Workers                              │
│                         │                                  │
│                  Integration Adapters                      │
└─────────────────────────┬──────────────────────────────────┘
                          │
              ┌───────────┼────────────┐
              ▼           ▼            ▼
          External      Payments     Marketplaces
           Data          /Bank         /Ads/etc.
```

---

# 35. Criterio de éxito

AMAZONA no estará lista para producción simplemente porque todos los paneles estén completos.

Se considerará preparada para una primera operación real controlada cuando:

```text
auth robusta
RBAC
audit
demo isolation
jobs
idempotency
hard gates
product data real
supplier data real
legal sources real
staging
approval gates
cost controls
```

estén funcionando.

Después se podrán activar de forma progresiva:

```text
KOVA
payments
orders
supplier execution
ads
marketplaces
```

---

# 36. Instrucción de ejecución para Claude Code

Antes de escribir código:

1. Leer:
   - `README.md`
   - `docs/architecture/system-overview.md`
   - todas las ADRs
   - milestones 16–28
   - `docs/design/AMAZONA_estado_paneles_rediseno.md`
   - auth actual
   - pipeline actual
   - CI actual

2. Verificar que este documento coincide con el estado real del repositorio.

3. Si detectas una contradicción, no asumir:
   - documentarla;
   - explicar impacto;
   - proponer resolución.

4. Empezar exclusivamente por:

```text
MILESTONE 29 — Production Security Foundation
```

5. Antes de implementarlo, redactar:
   - plan técnico;
   - archivos a modificar;
   - migraciones si aplican;
   - tests;
   - riesgos;
   - criterios de aceptación.

6. No comenzar Milestone 30 hasta que Milestone 29 pase:
   - lint;
   - type check;
   - tests;
   - build;
   - revisión de seguridad.

---

# 37. Resultado esperado del siguiente ciclo

La siguiente entrega de Claude Code debe dejar AMAZONA en este estado:

```text
HOY
Simulación funcional muy avanzada

        ↓

SIGUIENTE ESTADO

Base segura para producción
+
identidad real
+
roles
+
endpoints protegidos
+
mocks aislados
+
camino preparado para jobs y datos reales
```

No se busca todavía autonomía completa.

Se busca construir correctamente la base para que la autonomía futura sea segura, trazable y escalable.
