# Milestone 9 Demo

**Ticket:** IVA-57 (Linear).

Plan completo:
[`docs/superpowers/plans/2026-09-16-amazona-milestone-9.md`](../superpowers/plans/2026-09-16-amazona-milestone-9.md).
Arquitectura:
[ADR 0003](../architecture/adr-0003-rls-deny-by-default.md)
(RLS deny-by-default — `operations_records` nace ya con RLS activado)
y [ADR 0004](../architecture/adr-0004-agent-capability-pairs-validate-vs-discover.md)
(convención de capacidades, aplicada como estilo — sin contraparte de
Milestone 1, igual que los Agentes 5, 6 y 7).

**Con este milestone se completan los 8 agentes operativos de Fase 3.**

## Decisión de alcance (enunciado ambiguo, interpretación documentada)

No hay pedidos ni clientes reales en el sistema (ningún milestone
anterior creó tablas `orders`/`customers`). Interpretación adoptada:

- **Procesar pedidos** → el agente simula UN pedido de ejemplo por
  producto×mercado (id determinista, cantidad fija) — no un checkout
  real ni pedidos de clientes reales.
- **Coordinar con proveedores** → reutiliza el lead time/verificación
  **reales** del `SupplierQuote` (Agente 2) — sin mensajería real.
- **Hacer seguimiento** → línea de tiempo determinista (pedido →
  procesando → enviado → en reparto → entregado) escalada al lead time
  real — sin transportista real.
- **Gestionar devoluciones** → política determinista por mercado con
  estimación de reembolso a partir del precio de venta **real**
  (Agente 3) — sin procesamiento de devoluciones reales.
- **Atención al cliente (IA + humano)** → triaje de UN ticket de
  ejemplo: resoluble por IA o escalado a un humano, usando el estado
  legal/de restricción **real** (Agente 4) como criterio — sin chatbot
  ni sistema de tickets real.

## Flujo completo: Investigación → ... → Operations (Fase 3, Agentes 1-8)

```bash
# 1-7. Investigar, sourcear, economía, legal, tienda, listing, campaña (sin cambios desde Milestone 2-8)
curl -s -X POST http://localhost:8000/api/research/runs \
  -H "Content-Type: application/json" -d '{"category": "home", "max_results": 5}'
curl -s -X POST http://localhost:8000/api/sourcing/runs \
  -H "Content-Type: application/json" \
  -d '{"product_id": "<product_id>", "category": "home", "destination_region": "mexico", "max_results": 5}'
curl -s -X POST http://localhost:8000/api/economics/runs \
  -H "Content-Type: application/json" \
  -d '{"product_id": "<product_id>", "supplier_quote_id": "<quote_id>", "sale_price": 50.0}'
curl -s -X POST http://localhost:8000/api/legal/runs \
  -H "Content-Type: application/json" \
  -d '{"product_id": "<product_id>", "market": "us", "certification_available": true}'
curl -s -X POST http://localhost:8000/api/ecommerce/runs \
  -H "Content-Type: application/json" -d '{"product_id": "<product_id>", "market": "us"}'
curl -s -X POST http://localhost:8000/api/marketplace/runs \
  -H "Content-Type: application/json" \
  -d '{"product_id": "<product_id>", "market": "us", "platform": "amazon"}'
curl -s -X POST http://localhost:8000/api/marketing/runs \
  -H "Content-Type: application/json" \
  -d '{"product_id": "<product_id>", "market": "us", "platform": "google", "daily_budget": 20.0}'

# 8. Generar el informe operativo (Fase 3, Agente 8 — último agente operativo)
curl -s -X POST http://localhost:8000/api/operations/runs \
  -H "Content-Type: application/json" -d '{"product_id": "<product_id>", "market": "us"}'
# -> {"correlation_id": "...", "operations_status": "READY|NEEDS_REVIEW|BLOCKED",
#     "data": {"order": {"order_id": "...", "tracking": {"stages": [...]}},
#     "supplier_coordination": {...}, "return_policy": {"refund_estimate": 50.0},
#     "support_ticket_example": {"ai_resolvable": true, ...}}}
```

O desde el Control Center: **Research** → ... → **Marketing** → *Simulate
operations* → **Operations** → ver el pedido simulado con seguimiento,
coordinación con proveedor, política de devoluciones, y el ticket de
ejemplo (IA vs humano).

Los ocho runs de agentes tienen ocho `correlation_id` distintos, todos
reconstruibles vía `GET /api/audit?correlation_id=` — cubierto por
`backend/tests/e2e/test_operations_to_full_chain_flow.py`, que verifica
tanto el camino sano (`READY`, ticket resuelto por IA, seguimiento
reflejando el lead time real, reembolso calculado del precio real) como
el camino de escalado/bloqueo (categoría restringida sin certificación
→ `legal_status NO_GO` → ticket escalado a un humano y operaciones
`BLOCKED`).

**Verificado manualmente en el navegador** (Control Center + backend
contra una base SQLite local de desarrollo): con `home` a $50, lead
time real de proveedor de 10 días, el informe operativo mostró
`READY`, seguimiento con entrega estimada el día 13, política de
devolución con reembolso de $50.00, y un ticket de ejemplo resuelto por
IA. Verificado también a 375px de ancho (mobile).

## Base de datos: tabla `operations_records`

`operations_records` vincula un `Product` (y, opcionalmente, una
`MarketingCampaign` del mismo mercado) a un informe operativo. RLS
activado en su propia migración
(`833c46295739_add_operations_records_table.py`), mismo patrón que las
tablas de los milestones anteriores.

**Verificado contra Supabase real.** `alembic upgrade head` se ejecutó
contra el proyecto `amazona` (`e739124893e2 → 833c46295739`), y
`SELECT relrowsecurity FROM pg_class WHERE relname = 'operations_records'`
confirma `true`. `get_advisors` (linter de seguridad de Supabase)
reporta **0 hallazgos** tras la migración.

## Verificar todo en local

```bash
cd backend && ruff check . && mypy app && pytest       # 399 tests
cd apps/control-center && npm run lint && npx next typegen && npx tsc --noEmit && npm test && npm run build
```

---

## Cierre de Fase 3: valoración de qué queda pendiente

Con los 8 agentes operativos completos (Investigación, Sourcing,
Análisis Económico, Legal, E-commerce, Marketplace, Marketing,
Operaciones), toca revisar las tres capas restantes que menciona el
README original (Orquestador, CEO, CFO) para decidir el siguiente
milestone.

### Agente 9 — Orquestador: **no necesita cambios**

`CEOOrchestrator` (ADR 0001) sigue siendo sólido: coordina el grafo de
tareas de Milestone 1, persiste el grafo de dependencias (M2),
garantiza aislamiento entre ejecuciones concurrentes (M2), y aplica una
política de reintentos acotada (M2). **Su alcance sigue siendo,
deliberadamente, solo el grafo de validación de 4 tareas de Milestone
1** — ninguno de los 8 agentes de Fase 3 se despacha desde ahí, por
diseño (ADR 0004: los agentes "descubre-muchos" viven fuera del grafo
fijo del planner).

**Consecuencia real a tener en cuenta:** el "loop" completo de 8
agentes que este milestone cierra (Research → ... → Operations) es hoy
**manual** — un humano hace clic en cada página y en cada "Validate
this X" para pasar datos reales de un agente al siguiente y, al final,
a la validación de Milestone 1. El Orquestador nunca encadena estos 8
pasos automáticamente. Si en el futuro se quiere autonomía real (el
sistema decide por sí mismo investigar → sourcear → lanzar campaña sin
que un humano navegue por 8 páginas), eso requeriría extender
`planner.py` para incorporar dinámicamente tareas de Fase 3 al grafo —
un cambio de arquitectura real, no cubierto por el alcance actual de
ninguna ADR existente, y que debería documentarse en una ADR nueva
antes de construirse.

### Agente CEO — sigue como capa/lógica, no como agente propio: **correcto por ahora**

Según ADR 0001, "Agente CEO" = `planner.py` + `decision_engine.py` +
las políticas de permisos/presupuesto — lógica determinista invocada
por el Orquestador, no un proceso propio. La propia ADR 0001 ya fijó
la condición para promoverlo a agente direccionable: que necesite
**operar de forma autónoma** (crear objetivos proactivamente, o
negociar recursos entre objetivos concurrentes). Ningún milestone de
Fase 3 ha creado esa necesidad — los objetivos los sigue creando un
humano desde la página CEO. **No hace falta desarrollarlo como agente
explícito todavía**; revisar de nuevo si un futuro milestone pide
autonomía real.

### Agente CFO — **es el hueco real que queda abierto**

El README original lista "Agente CFO: control económico" como una capa
propia, al mismo nivel que Orquestador y CEO — y **nunca se ha
construido como tal**. Lo que existe hoy:

- `BudgetEngine`/`Budget`/`BudgetAllocation`/`FinancialEvent`
  (Milestone 1): autoriza y reserva presupuesto **por aprobación
  individual** (p. ej. una campaña de marketing puntual) — sin visión
  de conjunto.
- `EconomicAnalysisAgent` (Agente 3, Milestone 4): analiza viabilidad
  **por producto**, no agrega across todo el catálogo.

**No existe ninguna vista consolidada** de salud financiera a través de
todos los productos/objetivos/campañas simultáneos — cuánto presupuesto
simulado total está comprometido, qué productos concentran el riesgo,
si el conjunto de campañas activas tiene un ROAS agregado saludable,
etc. Este es el candidato más claro y concreto para el siguiente
milestone: **un Agente CFO que consolide `EconomicAnalysis` +
`MarketingCampaign` + reservas de `BudgetEngine` en un informe de
control económico global**, siguiendo el mismo patrón de
tabla+migración+RLS+API+página que los 8 agentes anteriores.

**Recomendación:** el siguiente milestone natural es el Agente CFO
(control económico consolidado). El Orquestador y el Agente CEO no
requieren trabajo adicional salvo que se decida perseguir autonomía
real más adelante, lo cual sería una decisión de alcance nueva que
merece su propia ADR antes de empezar.
