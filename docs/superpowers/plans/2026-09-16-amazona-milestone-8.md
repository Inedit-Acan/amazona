# AMAZONA Milestone 8 Implementation Plan

> **Para agentes que ejecuten este plan:** implementar tarea por tarea con
> TDD, commits pequeños, y revisión después de cada tarea — igual que
> Milestone 1-7.

**Ticket:** IVA-56 (Linear).

**Objetivo:** continuar la Fase 3 del roadmap con el séptimo agente
operativo: **Agente 7, Marketing y Adquisición de Clientes**. Dado un
producto ya investigado, sourceado, con análisis económico, legal,
tienda y listing de marketplace (Agentes 1-6, todos ya persistidos),
diseña una campaña publicitaria (Meta/Google), segmenta audiencias,
genera creatividades (copy + brief de imagen), estima rendimiento (ROI
simulado), y recomienda presupuesto — produciendo una propuesta de
campaña lista para validar.

**Depende de:** Milestone 7 completo, [ADR 0001](../../architecture/adr-0001-orchestrator-vs-ceo.md),
[ADR 0002](../../architecture/adr-0002-agent-messaging-protocol.md),
[ADR 0003](../../architecture/adr-0003-rls-deny-by-default.md), y
[ADR 0004](../../architecture/adr-0004-agent-capability-pairs-validate-vs-discover.md).

## Hallazgo clave: este agente conecta con un mecanismo que ya existe desde Milestone 1

Al revisar `app/ceo/orchestrator.py` antes de diseñar este agente se
encontró que el flujo de aprobación de gasto simulado
(`requests_simulated_spend` / `spend_action` / `spend_amount` en el
`context` de un `Objective`, que dispara `BudgetEngine.authorize()` y
crea una fila `Approval` pendiente de un humano) **ya existe desde
Milestone 1**, y su valor de ejemplo hardcodeado desde entonces era
literalmente `spend_action: "launch_marketing_campaign"`,
`spend_amount: 150.0` — un placeholder inventado a falta de un agente
real de marketing. Este milestone cierra ese hueco exactamente igual
que Milestone 5 cerró el de `restricted_category`: el Agente 7 calcula
un presupuesto diario real recomendado, y el puente "Validate this
campaign" hacia la página CEO precarga `spend_amount` con ese valor
real (y mantiene `spend_action="launch_marketing_campaign"`,
`requests_simulated_spend=true`) — **sin tocar** el motor de
presupuesto ni el `decision_engine.py`, sustituyendo solo *quién*
produce el número.

## Decisión de alcance (enunciado ambiguo, interpretación documentada)

- **"Diseñar campañas (Meta, Google, etc.)"** → una propuesta de
  campaña determinista por producto×mercado×plataforma (objetivo de
  campaña, presupuesto diario recomendado) — no se crea ninguna
  campaña real en Meta Ads Manager ni Google Ads, no hay credenciales
  ni llamadas a esas APIs.
- **"Segmentar audiencias"** → 2-3 segmentos deterministas derivados de
  categoría/nivel de competencia real (Agente 1) — no hay datos reales
  de audiencia de ninguna plataforma.
- **"Generar creatividades (texto/imagen)"** → copy de anuncio
  (titular, texto principal, CTA) determinista **y un brief de imagen
  en texto** (descripción, estilo, dimensiones recomendadas) — este
  milestone **no genera una imagen real** (no hay integración con
  ningún modelo de generación de imágenes); el "creativo de imagen" es
  una especificación para que un humano o una herramienta de diseño la
  produzca, documentado explícitamente como tal.
- **"Analizar rendimiento (ROI)"** → estimación determinista de
  CTR/CPC/tasa de conversión/ROAS por categoría×plataforma, marcada
  como simulada (no hay integración real con Meta/Google Ads APIs) —
  mismo estándar de placeholder que el resto del proyecto.
- **"Optimizar presupuesto"** → una recomendación determinista
  (subir/mantener/bajar presupuesto) basada en el ROAS proyectado real
  — no hay un optimizador multi-plataforma en este milestone (cada run
  del agente cubre un producto×mercado×plataforma; comparar entre
  plataformas queda para un futuro milestone si se pide).
- **Presupuesto/gasto:** siempre simulado — `daily_budget` es un
  número que el agente recomienda y que, si el usuario valida la
  campaña, entra al mecanismo de aprobación humana ya existente desde
  Milestone 1 (nunca se ejecuta un cargo real).

## Cómo encaja con lo ya construido (Agentes 1-6)

- **Patrón agente/servicio:** `MarketingCampaignAgent` es puro/sin DB.
  `MarketingCampaignService` resuelve `product_id` + `market` (+
  `platform`, default `"meta"`; + `daily_budget`, default `20.0`) →
  `Product` (M2, requerido), la `ProductAnalysis` de investigación más
  reciente (M2, opcional, competencia), el `SupplierQuote` más reciente
  (M3, opcional, lead time — riesgo informativo si es muy largo antes
  de escalar gasto), el `EconomicAnalysis` más reciente (M4, opcional
  pero crítico, precio/margen/recomendación), el `LegalAnalysis` más
  reciente del mercado (M5, opcional pero crítico), y el
  `MarketplaceListing` más reciente del mercado (M6, opcional,
  informativo) — arma el `task_input`, invoca al agente, persiste.
- **Veredicto `campaign_status`:** mismo patrón de tres niveles que los
  Agentes 5 y 6 — `NO_GO` de Economía o Legal, o ROAS proyectado por
  debajo de 1.0 (el gasto publicitario no se recupera), bloquean la
  campaña (`campaign_status="BLOCKED"`); datos previos incompletos
  ⇒ `NEEDS_REVIEW`; todo despejado ⇒ `READY`.
- **API + auditoría + `correlation_id`:** mismo patrón que los
  endpoints anteriores.
- **Capability:** `marketing_campaign_planning`. Igual que los Agentes
  5 y 6, no hay contraparte "validar-uno" de Milestone 1 — Milestone 1
  nunca tuvo un agente de marketing (solo una cadena de texto de
  ejemplo, ver arriba).

## Restricciones globales (heredadas)

- Sin gasto publicitario real, sin credenciales de Google/Meta/TikTok
  Ads, sin campañas reales creadas en ninguna plataforma.
- Los datos de rendimiento/audiencia/creatividad son deterministas,
  documentados como placeholders.
- El Agente 7 nunca lanza una campaña real; es puramente
  informativo/generativo. Comprometerse con un gasto real sigue
  pasando por el flujo de aprobación humana ya existente desde
  Milestone 1 — sin excepciones nuevas.
- El núcleo de decisión determinista no se toca — el Agente 7 no se
  cablea en el grafo de tareas del planner.
- Toda tabla nueva nace con RLS activado en su propia migración (ADR 0003).
- Tests antes que implementación. Commit por tarea completada.
- Ningún test de Milestone 1-7 cambia de resultado (salvo el conteo
  total de agentes, que sube de 10 a 11).

---

## Estructura de archivos (adiciones sobre Milestone 7)

```text
backend/
├── app/
│   ├── ai/
│   │   └── mock_ad_performance_directory.py  # CTR/CPC/conversión por categoría×plataforma
│   ├── marketing/
│   │   ├── creative.py          # segmentos de audiencia, copy+brief de imagen, tip de presupuesto
│   │   └── service.py           # MarketingCampaignService
│   ├── agents/
│   │   └── marketing_campaign.py    # Agente 7 — capability marketing_campaign_planning
│   ├── api/
│   │   └── marketing.py
│   └── db/models/
│       └── marketing_campaign.py    # tabla marketing_campaigns
├── alembic/versions/                 # nueva migración incremental
└── tests/
    ├── unit/
    │   ├── test_mock_ad_performance_directory.py
    │   ├── test_marketing_creative.py
    │   └── test_marketing_campaign_agent.py
    ├── integration/
    │   ├── test_marketing_campaign_model.py
    │   ├── test_marketing_campaign_service.py
    │   └── test_marketing_api.py
    └── e2e/
        └── test_marketing_campaign_to_validation_flow.py

apps/control-center/
├── app/
│   └── marketing/page.tsx       # propuesta de campaña + puente desde Marketplace + puente a CEO
├── lib/api.ts                   # +createMarketingCampaignRun, tipos
└── components/nav-items.ts      # +"Marketing"
```

---

## Sección A — Fuentes mock y generadores de creatividad

### Tarea 1: `MockAdPerformanceDirectory` — CTR/CPC/conversión por categoría×plataforma

**Files:**
- Create: `backend/app/ai/mock_ad_performance_directory.py`
- Create: `backend/tests/unit/test_mock_ad_performance_directory.py`

**Produces:** fuente determinista y fixture-driven (sin red, sin
credenciales de Meta/Google Ads) que simula, para cada par (categoría,
plataforma): `avg_cpc`, `avg_ctr`, `conversion_rate`. Marcado
`data_origin: "simulated_ad_performance_estimate"`.

- [ ] Test: misma consulta → mismo resultado.
- [ ] Test: par (categoría, plataforma) desconocido devuelve `None`.
- [ ] Test: cada combinación conocida incluye `data_origin`.
- [ ] Implementar con dataset fixture cubriendo
      `electronics`/`home`/`accessories` × `meta`/`google`.
- [ ] Commit: `feat: add mock ad performance estimate directory`

---

### Tarea 2: Generadores deterministas de audiencia, creatividad y presupuesto

**Files:**
- Create: `backend/app/marketing/creative.py`
- Create: `backend/tests/unit/test_marketing_creative.py`

**Produces:**

```python
def generate_audience_segments(*, category: str, competition_level: str | None) -> list[dict]
def generate_ad_creative(*, product_name: str, category: str, sale_price: float | None) -> dict
    # {"headline", "primary_text", "cta", "image_brief"} — image_brief es
    # texto (descripción/estilo/dimensiones), nunca una imagen generada.
def recommend_budget_action(*, projected_roas: float | None) -> str
```

- [ ] Test: `generate_audience_segments` devuelve 2-3 segmentos con
      forma consistente, determinista.
- [ ] Test: `generate_ad_creative` incluye el nombre del producto y un
      `image_brief` en texto (no una imagen ni una URL).
- [ ] Test: `recommend_budget_action` sugiere subir presupuesto con
      ROAS alto, bajarlo/pausar con ROAS bajo, y "insufficient data"
      con `None`.
- [ ] Implementar.
- [ ] Commit: `feat: add deterministic audience, creative, and budget recommendation generators`

---

## Sección B — Agente 7

### Tarea 3: `MarketingCampaignAgent` — capability `marketing_campaign_planning`

**Files:**
- Create: `backend/app/agents/marketing_campaign.py`
- Create: `backend/tests/unit/test_marketing_campaign_agent.py`
- Modify: `backend/app/agents/registry.py`

```python
class MarketingCampaignInput(BaseModel):
    product_name: str
    category: str
    market: str
    platform: str = "meta"
    daily_budget: float = 20.0
    sale_price: float | None = None
    economic_recommendation: str | None = None
    legal_recommendation: str | None = None
    marketplace_listing_status: str | None = None
    lead_time_days: int | None = None
    competition_level: str | None = None
```

- [ ] Test: `economic_recommendation="NO_GO"` o
      `legal_recommendation="NO_GO"` ⇒ `campaign_status="BLOCKED"`.
- [ ] Test: ROAS proyectado < 1.0 (con `sale_price` bajo y CPC/tasa de
      conversión desfavorables) ⇒ `campaign_status="BLOCKED"`, riesgo
      explícito de ROAS negativo.
- [ ] Test: datos previos incompletos ⇒ `campaign_status="NEEDS_REVIEW"`.
- [ ] Test: todo despejado ⇒ `campaign_status="READY"`,
      `recommendation="GO"`, `data` incluye `audience_segments`,
      `ad_creative` (con `image_brief` en texto), `performance_estimate`
      (con `data_origin`), `budget_recommendation`.
- [ ] Test: `marketplace_listing_status="BLOCKED"` genera un riesgo
      informativo pero no bloquea por sí solo la campaña.
- [ ] Test: `lead_time_days` largo (> 45 días) genera un riesgo de
      preparación de inventario antes de escalar gasto.
- [ ] Test: categoría×plataforma desconocida ⇒ `REVIEW` con riesgo de
      datos insuficientes.
- [ ] Implementar reutilizando `MockAdPerformanceDirectory` +
      `app/marketing/creative.py`.
- [ ] Registrar en `build_default_agent_manager()` como
      `agent-marketing-campaign-1`, capability
      `marketing_campaign_planning`.
- [ ] Commit: `feat: add marketing campaign planning agent`

**Acceptance:** `AgentResult` válido (ADR 0002); los 10 agentes
existentes siguen pasando sus tests sin modificarse.

---

## Sección C — Persistencia y API

### Tarea 4: Tabla `marketing_campaigns` (con RLS desde su propia migración)

**Files:**
- Create: `backend/app/db/models/marketing_campaign.py`
- Modify: `backend/app/db/models/__init__.py`
- Create: Alembic migration (mismo patrón `DO $$ ... ENABLE ROW LEVEL
  SECURITY ... $$`)
- Create: `backend/tests/integration/test_marketing_campaign_model.py`

**Esquema:**
- id, product_id (FK `products.id`), marketplace_listing_id (FK
  `marketplace_listings.id`, nullable), market, platform,
  daily_budget, campaign_status, recommendation, confidence, data
  (JSON — segmentos, creatividad, estimación de rendimiento con
  `data_origin`, recomendación de presupuesto, riesgos, evidencia),
  correlation_id, created_at/updated_at.

- [ ] Test: crear con `product_id` válido, verificar persistencia.
- [ ] Test: FK inválida levanta `IntegrityError`.
- [ ] Implementar modelo + migración; aplicar a Supabase real y
      confirmar `relrowsecurity=true` + `get_advisors` en 0 vía MCP.
- [ ] Commit: `feat: add marketing campaigns table with rls enabled`

---

### Tarea 5: `MarketingCampaignService` — resuelve los 6 agentes anteriores y persiste

**Files:**
- Create: `backend/app/marketing/service.py`
- Create: `backend/tests/integration/test_marketing_campaign_service.py`

- [ ] Test: usa la categoría real del `Product`, precio/margen/
      recomendación reales del `EconomicAnalysis`, recomendación legal
      real del mercado correcto, lead time real del `SupplierQuote`, y
      enlaza el `MarketplaceListing` más reciente del mismo mercado si
      existe.
- [ ] Test: `product_id` inexistente ⇒ `NotFoundError`.
- [ ] Test: funciona (con `NEEDS_REVIEW`) sin ningún dato previo de
      M3/M4/M5/M6.
- [ ] Test: usa el `LegalAnalysis`/`MarketplaceListing` del mercado
      correcto cuando hay varios mercados (no mezcla).
- [ ] Test: auditoría con `correlation_id` (acción `marketing.run`).
- [ ] Commit: `feat: add marketing campaign service resolving all six prior agents`

---

### Tarea 6: API de campañas de marketing

**Files:**
- Create: `backend/app/api/marketing.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/integration/test_marketing_api.py`

**Produces:**
- `POST /api/marketing/runs` → `{product_id, market, platform?,
  daily_budget?}`, ejecuta y persiste, devuelve la propuesta de
  campaña.
- `GET /api/marketing/runs/{correlation_id}` → reconstruido desde DB.
- `GET /api/products/{product_id}/campaigns` → historial.

- [ ] Test: creación exitosa devuelve `audience_segments`,
      `ad_creative`, `performance_estimate`, `budget_recommendation`,
      `campaign_status`.
- [ ] Test: reconstrucción por `correlation_id` idéntica.
- [ ] Test: 404 claro para producto inexistente.
- [ ] Commit: `feat: add marketing campaign api`

---

## Sección D — Control Center

### Tarea 7: Página "Marketing" + reemplazo real del placeholder `spend_amount`

**Files:**
- Create: `apps/control-center/app/marketing/page.tsx`
- Modify: `apps/control-center/lib/api.ts`
- Modify: `apps/control-center/components/nav-items.ts`
- Modify: `apps/control-center/app/marketplace/page.tsx` (botón "Plan
  marketing campaign")
- Modify: `apps/control-center/app/ceo/page.tsx` (`buildInitialState`
  lee `spend_amount` de query params y sustituye el
  `150.0` hardcodeado desde Milestone 1 cuando el handoff viene de
  Marketing; `spend_action` se mantiene `"launch_marketing_campaign"`,
  ya correcto desde Milestone 1)

**Produces:** formulario (producto + mercado + plataforma +
presupuesto diario) que dispara la generación y pinta segmentos de
audiencia, creatividad (copy + brief de imagen), estimación de
rendimiento, recomendación de presupuesto, y `campaign_status`; botón
"Validate this campaign" que salta a CEO con `spend_amount` real
precargado.

- [ ] Verificar en navegador (desktop + mobile) con datos reales del
      backend.
- [ ] Commit: `feat: add marketing page and replace spend_amount placeholder with real recommendation`

**Acceptance:** desde "Marketplace" se puede pasar a "Marketing", ver
la propuesta de campaña, y validarla con un `spend_amount` real —
cerrando el loop de los 7 agentes y conectando con el mecanismo de
aprobación de gasto de Milestone 1.

---

## Sección E — Verificación end-to-end

### Tarea 8: E2E — flujo completo de 7 agentes + doc de cierre + advisor de seguridad

**Files:**
- Create: `backend/tests/e2e/test_marketing_campaign_to_validation_flow.py`
- Create: `docs/milestones/milestone-8-demo.md`

**Escenario:** Research → Sourcing → Economics → Legal → Ecommerce →
Marketplace → Marketing → Validation, verificando:
1. con los 6 agentes anteriores en estado saludable, la campaña queda
   `READY`, y al validar, la decisión del CEO pasa por `HUMAN_APPROVAL`
   con un `Approval` cuyo `amount` es el presupuesto real recomendado
   (no `150.0`);
2. con un análisis económico o legal `NO_GO`, la campaña queda
   `BLOCKED`;
3. los 7 `correlation_id` (+ el de validación) son distintos y
   reconstruibles.

- [ ] Escribir el test, correr, verificar que pasa.
- [ ] Documentar en `docs/milestones/milestone-8-demo.md` (mismo
      formato que Milestone 2-7), incluyendo la sección sobre el
      hallazgo del mecanismo de aprobación de gasto de Milestone 1.
- [ ] Ejecutar `get_advisors` (seguridad) contra el proyecto Supabase
      real tras la migración de la Tarea 4, documentar 0 hallazgos.
- [ ] Commit: `test: verify marketing campaign to validation flow end to end`

---

## Definition of Done — Milestone 8

1. `marketing_campaigns` es una tabla real, con RLS activado desde su
   propia migración, verificada contra Supabase real.
2. El Agente 7 (`MarketingCampaignAgent`, capability
   `marketing_campaign_planning`) genera segmentos de audiencia,
   creatividad (copy + brief de imagen en texto), estimación de
   rendimiento simulada marcada por origen, y recomendación de
   presupuesto — con un veredicto que respeta los `NO_GO` de los
   Agentes 3 y 4 y un ROAS proyectado insuficiente.
3. `MarketingCampaignService` integra datos reales de los 6 agentes
   anteriores, sin mezclar mercados.
4. Existe una API de campañas auditada con `correlation_id`.
5. El Control Center tiene una página "Marketing" que cierra el loop
   de 7 agentes.
6. **El placeholder `spend_amount=150.0`** de Milestone 1 se sustituye
   por el presupuesto real recomendado cuando el handoff viene de
   Marketing — sin tocar el motor de presupuesto ni `decision_engine.py`.
7. El flujo E2E demuestra el camino `READY` → `HUMAN_APPROVAL` con
   `Approval.amount` real, y el camino `BLOCKED`.
8. El linter de seguridad de Supabase sigue en verde tras la migración.
9. `docs/milestones/milestone-8-demo.md` documenta el milestone.
10. Ningún test de Milestone 1-7 cambia de resultado (salvo el conteo
    de agentes, actualizado explícitamente).
