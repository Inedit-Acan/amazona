# AMAZONA Milestone 9 Implementation Plan

> **Para agentes que ejecuten este plan:** implementar tarea por tarea con
> TDD, commits pequeños, y revisión después de cada tarea — igual que
> Milestone 1-8.

**Ticket:** IVA-57 (Linear).

**Objetivo:** cerrar la Fase 3 del roadmap con el octavo y último agente
operativo: **Agente 8, Operaciones y Atención al Cliente**. Dado un
producto ya investigado, sourceado, con análisis económico, legal,
tienda, listing de marketplace y campaña (Agentes 1-7, todos ya
persistidos), simula el procesamiento de un pedido (con seguimiento),
coordina con el proveedor real (lead time/verificación), define una
política de devoluciones, y triaje un ticket de atención al cliente de
ejemplo decidiendo si lo resuelve la IA o si escala a un humano —
produciendo un informe operativo por producto×mercado.

**Depende de:** Milestone 8 completo, [ADR 0001](../../architecture/adr-0001-orchestrator-vs-ceo.md),
[ADR 0002](../../architecture/adr-0002-agent-messaging-protocol.md),
[ADR 0003](../../architecture/adr-0003-rls-deny-by-default.md), y
[ADR 0004](../../architecture/adr-0004-agent-capability-pairs-validate-vs-discover.md).

## Decisión de alcance (enunciado ambiguo, interpretación documentada)

No hay pedidos ni clientes reales en el sistema todavía (ningún
milestone anterior creó una tabla `orders` o `customers`). Interpretación
adoptada para este milestone:

- **"Procesar pedidos"** → el agente simula UN pedido de ejemplo por
  producto×mercado (id de pedido determinista, cantidad fija, estado),
  no un sistema de checkout/carrito real ni pedidos de clientes reales.
- **"Coordinar con proveedores"** → reutiliza el lead time y estado de
  verificación **reales** del `SupplierQuote` (Agente 2) para estimar
  una fecha de entrega y marcar riesgos de coordinación — no hay
  mensajería real con el proveedor.
- **"Hacer seguimiento"** → una línea de tiempo de seguimiento
  determinista (pedido → procesando → enviado → en reparto →
  entregado) con offsets de día derivados del lead time real — no hay
  integración con ninguna transportista real.
- **"Gestionar devoluciones"** → una política de devoluciones
  determinista por mercado (ventana de elegibilidad, tarifa de
  reposición, estimación de reembolso a partir del precio de venta
  real del Agente 3) — no hay procesamiento de devoluciones reales.
- **"Atención al cliente (IA + humano)"** → triaje determinista de UN
  ticket de ejemplo: se clasifica como resoluble por IA o se marca para
  escalar a un humano, usando el estado legal/de restricción real
  (Agente 4) como criterio — no hay chatbot real ni sistema de tickets
  real integrado.
- Todos los datos generados son deterministas y están documentados como
  placeholders, mismo estándar que el resto del proyecto.

## Cómo encaja con lo ya construido (Agentes 1-7)

- **Patrón agente/servicio:** `OperationsAgent` es puro/sin DB.
  `OperationsService` resuelve `product_id` + `market` → `Product` (M2,
  requerido), el `SupplierQuote` más reciente (M3, opcional, lead
  time/verificación), el `EconomicAnalysis` más reciente (M4, opcional
  pero crítico, precio/recomendación), el `LegalAnalysis` más reciente
  del mercado (M5, opcional pero crítico, restricción), y el
  `MarketingCampaign` más reciente del mercado (M8... M7 — el agente
  inmediatamente anterior, enlazado igual que cada agente previo
  enlazó al inmediatamente anterior) — arma el `task_input`, invoca al
  agente, persiste.
- **Veredicto `operations_status`:** mismo patrón de tres niveles que
  los Agentes 5, 6 y 7 — `NO_GO` de Economía o Legal bloquean
  (`operations_status="BLOCKED"`, no se procesan pedidos de un producto
  inviable o legalmente bloqueado); datos previos incompletos ⇒
  `NEEDS_REVIEW`; todo despejado ⇒ `READY`.
- **API + auditoría + `correlation_id`:** mismo patrón que los
  endpoints anteriores.
- **Capability:** `operations_fulfillment_management`. Igual que los
  Agentes 5, 6 y 7, no hay contraparte "validar-uno" de Milestone 1 —
  Milestone 1 nunca tuvo un agente de operaciones/atención al cliente.

## Restricciones globales (heredadas)

- Sin pedidos reales, sin clientes reales, sin integración real de
  CRM/sistema de tickets/chatbot/transportista.
- Los datos de pedido/seguimiento/devolución/ticket son deterministas,
  documentados como placeholders.
- El Agente 8 nunca procesa un pedido real ni resuelve un ticket real;
  es puramente informativo/generativo.
- El núcleo de decisión determinista no se toca — el Agente 8 no se
  cablea en el grafo de tareas del planner.
- Toda tabla nueva nace con RLS activado en su propia migración (ADR 0003).
- Tests antes que implementación. Commit por tarea completada.
- Ningún test de Milestone 1-8 cambia de resultado (salvo el conteo
  total de agentes, que sube de 11 a 12 — el octavo y último operativo
  de Fase 3).

---

## Estructura de archivos (adiciones sobre Milestone 8)

```text
backend/
├── app/
│   ├── operations/
│   │   ├── fulfillment.py       # order id/tracking, política de devoluciones, triaje de ticket
│   │   └── service.py           # OperationsService
│   ├── agents/
│   │   └── operations.py        # Agente 8 — capability operations_fulfillment_management
│   ├── api/
│   │   └── operations.py
│   └── db/models/
│       └── operations_record.py # tabla operations_records
├── alembic/versions/              # nueva migración incremental
└── tests/
    ├── unit/
    │   ├── test_operations_fulfillment.py
    │   └── test_operations_agent.py
    ├── integration/
    │   ├── test_operations_record_model.py
    │   ├── test_operations_service.py
    │   └── test_operations_api.py
    └── e2e/
        └── test_operations_to_full_chain_flow.py

apps/control-center/
├── app/
│   └── operations/page.tsx      # pedido simulado + seguimiento + devoluciones + ticket
├── lib/api.ts                   # +createOperationsRun, tipos
└── components/nav-items.ts      # +"Operations"
```

---

## Sección A — Generadores deterministas de fulfillment

### Tarea 1: `fulfillment.py` — pedido, seguimiento, devoluciones, triaje de ticket

**Files:**
- Create: `backend/app/operations/fulfillment.py`
- Create: `backend/tests/unit/test_operations_fulfillment.py`

**Produces:**

```python
def generate_order_id(*, product_id: str, market: str) -> str
def generate_order_tracking(*, lead_time_days: int | None) -> dict
    # {"stages": [{"stage": "order_placed", "day_offset": 0}, ...]}
    # usa un lead time por defecto documentado si lead_time_days es None.
def generate_return_policy(*, market: str, sale_price: float | None) -> dict
    # {"eligibility_window_days", "restocking_fee_percent", "refund_estimate"}
def classify_support_ticket(*, restricted: bool | None, legal_recommendation: str | None) -> dict
    # {"ticket_type", "ai_resolvable", "escalation_reason"}
```

- [ ] Test: `generate_order_id` es determinista y varía por
      producto/mercado.
- [ ] Test: `generate_order_tracking` con `lead_time_days=None` usa un
      valor por defecto documentado, sin fallar; con un valor real, las
      etapas reflejan ese lead time.
- [ ] Test: `generate_return_policy` calcula `refund_estimate` a partir
      de `sale_price` real cuando existe, y devuelve `None` si no.
- [ ] Test: `classify_support_ticket` marca `ai_resolvable=False` con
      una razón de escalado cuando `restricted=True` o
      `legal_recommendation` no es `"GO"`; `ai_resolvable=True` en caso
      contrario.
- [ ] Implementar.
- [ ] Commit: `feat: add deterministic order fulfillment, returns, and support triage generators`

---

## Sección B — Agente 8

### Tarea 2: `OperationsAgent` — capability `operations_fulfillment_management`

**Files:**
- Create: `backend/app/agents/operations.py`
- Create: `backend/tests/unit/test_operations_agent.py`
- Modify: `backend/app/agents/registry.py`

```python
class OperationsInput(BaseModel):
    product_name: str
    category: str
    market: str
    sale_price: float | None = None
    lead_time_days: int | None = None
    supplier_verified: bool | None = None
    economic_recommendation: str | None = None
    legal_recommendation: str | None = None
    restricted: bool | None = None
```

- [ ] Test: `economic_recommendation="NO_GO"` o
      `legal_recommendation="NO_GO"` ⇒ `operations_status="BLOCKED"`.
- [ ] Test: datos previos incompletos ⇒ `operations_status="NEEDS_REVIEW"`.
- [ ] Test: todo despejado ⇒ `operations_status="READY"`,
      `recommendation="GO"`, `data` incluye `order` (con
      `tracking.stages`), `supplier_coordination`, `return_policy`,
      `support_ticket_example`.
- [ ] Test: proveedor no verificado ⇒ riesgo explícito de coordinación.
- [ ] Test: `restricted=True` ⇒ `support_ticket_example.ai_resolvable`
      es `False` con razón de escalado.
- [ ] Implementar reutilizando `app/operations/fulfillment.py`.
- [ ] Registrar en `build_default_agent_manager()` como
      `agent-operations-1`, capability
      `operations_fulfillment_management`.
- [ ] Commit: `feat: add operations and customer service agent`

**Acceptance:** `AgentResult` válido (ADR 0002); los 11 agentes
existentes siguen pasando sus tests sin modificarse.

---

## Sección C — Persistencia y API

### Tarea 3: Tabla `operations_records` (con RLS desde su propia migración)

**Files:**
- Create: `backend/app/db/models/operations_record.py`
- Modify: `backend/app/db/models/__init__.py`
- Create: Alembic migration
- Create: `backend/tests/integration/test_operations_record_model.py`

**Esquema:**
- id, product_id (FK `products.id`), marketing_campaign_id (FK
  `marketing_campaigns.id`, nullable), market, operations_status,
  recommendation, confidence, data (JSON — pedido/seguimiento,
  coordinación con proveedor, política de devoluciones, ejemplo de
  ticket, riesgos, evidencia), correlation_id, created_at/updated_at.

- [ ] Test: crear con `product_id` válido, verificar persistencia.
- [ ] Test: FK inválida levanta `IntegrityError`.
- [ ] Implementar modelo + migración; aplicar a Supabase real y
      confirmar `relrowsecurity=true` + `get_advisors` en 0 vía MCP.
- [ ] Commit: `feat: add operations records table with rls enabled`

---

### Tarea 4: `OperationsService` — resuelve los 7 agentes anteriores y persiste

**Files:**
- Create: `backend/app/operations/service.py`
- Create: `backend/tests/integration/test_operations_service.py`

- [ ] Test: usa la categoría real del `Product`, lead
      time/verificación real del `SupplierQuote`, precio/recomendación
      real del `EconomicAnalysis`, recomendación/restricción legal real
      del mercado correcto, y enlaza la `MarketingCampaign` más
      reciente del mismo mercado si existe.
- [ ] Test: `product_id` inexistente ⇒ `NotFoundError`.
- [ ] Test: funciona (con `NEEDS_REVIEW`) sin ningún dato previo de
      M3/M4/M5/M7.
- [ ] Test: usa el `LegalAnalysis`/`MarketingCampaign` del mercado
      correcto cuando hay varios mercados (no mezcla).
- [ ] Test: auditoría con `correlation_id` (acción `operations.run`).
- [ ] Commit: `feat: add operations service resolving all seven prior agents`

---

### Tarea 5: API de operaciones

**Files:**
- Create: `backend/app/api/operations.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/integration/test_operations_api.py`

**Produces:**
- `POST /api/operations/runs` → `{product_id, market}`, ejecuta y
  persiste, devuelve el informe operativo.
- `GET /api/operations/runs/{correlation_id}` → reconstruido desde DB.
- `GET /api/products/{product_id}/operations` → historial.

- [ ] Test: creación exitosa devuelve `order`, `supplier_coordination`,
      `return_policy`, `support_ticket_example`, `operations_status`.
- [ ] Test: reconstrucción por `correlation_id` idéntica.
- [ ] Test: 404 claro para producto inexistente.
- [ ] Commit: `feat: add operations api`

---

## Sección D — Control Center

### Tarea 6: Página "Operations"

**Files:**
- Create: `apps/control-center/app/operations/page.tsx`
- Modify: `apps/control-center/lib/api.ts`
- Modify: `apps/control-center/components/nav-items.ts`
- Modify: `apps/control-center/app/marketing/page.tsx` (botón "Simulate
  operations")

**Produces:** formulario (producto + mercado) que dispara la
generación y pinta el pedido simulado con su línea de tiempo de
seguimiento, coordinación con el proveedor, política de devoluciones,
el ticket de ejemplo (IA vs humano), y `operations_status`.

- [ ] Verificar en navegador (desktop + mobile) con datos reales del
      backend.
- [ ] Commit: `feat: add operations page`

**Acceptance:** desde "Marketing" se puede pasar a "Operations" y ver
el informe operativo, cerrando el loop de los 8 agentes de Fase 3.

---

## Sección E — Verificación end-to-end

### Tarea 7: E2E — flujo completo de 8 agentes + doc de cierre + advisor de seguridad

**Files:**
- Create: `backend/tests/e2e/test_operations_to_full_chain_flow.py`
- Create: `docs/milestones/milestone-9-demo.md`

**Escenario:** Research → ... → Marketing → Operations, verificando:
1. con los 7 agentes anteriores en estado saludable, el informe
   operativo queda `READY`, con seguimiento derivado del lead time
   real y ticket de ejemplo resoluble por IA;
2. con una categoría restringida (legal `NO_GO` o `restricted=True`),
   el ticket de ejemplo escala a un humano y/o el informe queda
   `BLOCKED`;
3. los 8 `correlation_id` son distintos y reconstruibles.

- [ ] Escribir el test, correr, verificar que pasa.
- [ ] Documentar en `docs/milestones/milestone-9-demo.md` (mismo
      formato que Milestone 2-8), incluyendo una valoración de qué
      queda pendiente en Fase 3 tras cerrar los 8 agentes operativos
      (Agente 9 Orquestador ya cubierto por `CEOOrchestrator`/ADR 0001;
      si el Agente CEO/Agente CFO necesitan desarrollo explícito como
      agentes propios o siguen como capas/lógica dentro del
      Orquestador).
- [ ] Ejecutar `get_advisors` (seguridad) contra el proyecto Supabase
      real tras la migración de la Tarea 3, documentar 0 hallazgos.
- [ ] Commit: `test: verify operations flow end to end and close fase 3`

---

## Definition of Done — Milestone 9

1. `operations_records` es una tabla real, con RLS activado desde su
   propia migración, verificada contra Supabase real.
2. El Agente 8 (`OperationsAgent`, capability
   `operations_fulfillment_management`) simula pedido + seguimiento,
   coordinación con proveedor real, política de devoluciones, y triaje
   de atención al cliente IA/humano — con un veredicto que respeta los
   `NO_GO` de los Agentes 3 y 4.
3. `OperationsService` integra datos reales de los 7 agentes
   anteriores, sin mezclar mercados.
4. Existe una API de operaciones auditada con `correlation_id`.
5. El Control Center tiene una página "Operations" que cierra el loop
   completo de los 8 agentes operativos de Fase 3.
6. El flujo E2E demuestra el camino `READY` (IA resuelve el ticket) y
   un camino con escalado a humano/bloqueo.
7. El linter de seguridad de Supabase sigue en verde tras la migración.
8. `docs/milestones/milestone-9-demo.md` documenta el milestone,
   incluyendo una valoración explícita de qué queda pendiente en
   Fase 3 (Orquestador, Agente CEO, Agente CFO) para decidir el
   siguiente milestone.
9. Ningún test de Milestone 1-8 cambia de resultado (salvo el conteo
   de agentes, actualizado explícitamente).
