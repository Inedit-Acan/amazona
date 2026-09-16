# AMAZONA Milestone 7 Implementation Plan

> **Para agentes que ejecuten este plan:** implementar tarea por tarea con
> TDD, commits pequeños, y revisión después de cada tarea — igual que
> Milestone 1-6.

**Ticket:** IVA-55 (Linear).

**Objetivo:** continuar la Fase 3 del roadmap con el sexto agente
operativo: **Agente 6, Marketplaces (Amazon y otros)**. Dado un producto
ya investigado, sourceado, con análisis económico, análisis legal y
tienda generada (Agentes 1-5, todos ya persistidos), crea/optimiza un
listing de marketplace, analiza competencia simulada, calcula el margen
neto tras comisiones de la plataforma, evalúa cumplimiento de políticas
de plataforma, y produce una estrategia de marketplace por producto —
sin gestión de stock real (no hay inventario físico en este sistema).

**Depende de:** Milestone 6 completo, [ADR 0001](../../architecture/adr-0001-orchestrator-vs-ceo.md),
[ADR 0002](../../architecture/adr-0002-agent-messaging-protocol.md),
[ADR 0003](../../architecture/adr-0003-rls-deny-by-default.md), y
[ADR 0004](../../architecture/adr-0004-agent-capability-pairs-validate-vs-discover.md).

## Restricción obligatoria: política de datos de Amazon SP-API

Del `README.md` del proyecto: **"Amazon SP-API: prohibido usar sus
datos para entrenar modelos."** Este milestone es el primero que trata
temas propios de un vendedor de Amazon (listings, comisiones,
competencia, políticas de categoría) — exactamente el tipo de dato que
en un sistema real vendría de la SP-API. Como **no hay integración real
con SP-API** en este milestone (ver "Alcance" más abajo), todo dato de
competencia/comisión/política es simulado — pero se marca y aísla
explícitamente para que nunca se confunda con datos reales de SP-API ni
se use accidentalmente como tal en el futuro:

- Todo bloque de datos de competencia/comisión/política que produce el
  Agente 6 incluye un campo `data_origin: "simulated_not_sp_api"`
  explícito, tanto en el resultado del agente como en lo persistido en
  DB.
- La fuente mock vive en un módulo propio y aislado
  (`backend/app/ai/mock_marketplace_directory.py`) con un docstring que
  cita esta restricción explícitamente, igual que el resto de fuentes
  mock del proyecto (`MockTrendsProvider`, `MockSupplierDirectory`,
  `MockRegulatoryDirectory`).
- Nada en este sistema entrena modelos con ningún dato (no hay
  pipeline de entrenamiento en todo el proyecto), así que el
  cumplimiento práctico de esta tarea es: **marcar el origen y aislar
  el módulo**, para que si en el futuro se integra la SP-API real, sea
  imposible confundir ambas fuentes de datos por accidente.

## Decisión de alcance (enunciado ambiguo, interpretación documentada)

- **"Crear y optimizar listings"** → generación determinista de
  contenido de listing (título optimizado, bullet points, keywords de
  backend) a partir de datos reales — no se publica ningún listing
  real en Amazon ni en ninguna otra plataforma.
- **"Gestionar inventario (sin stock)"** → un bloque informativo de
  política de inventario (`tracking_enabled: false`,
  `fulfillment_method` simulado) — explícitamente **sin números de
  stock real**, tal como pide el enunciado.
- **"Analizar competencia"** → datos de competencia simulados
  (nº de competidores, precio medio, rating medio, dificultad de
  buy-box) por categoría×plataforma, marcados `data_origin` (ver
  arriba) — no hay scraping ni llamada real a ninguna API de
  marketplace.
- **"Controlar comisiones"** → cálculo determinista del margen neto
  tras comisión de referencia + tarifa de fulfillment simuladas por
  categoría×plataforma, usando el coste aterrizado y precio de venta
  **reales** del Agente 3.
- **"Cumplir políticas de plataforma"** → un directorio mock de
  políticas por categoría×plataforma (aprobación de categoría
  requerida, materiales prohibidos), en el mismo espíritu que
  `MockRegulatoryDirectory` del Agente 4 pero para reglas de la
  plataforma, no de un gobierno.
- **Plataformas modeladas en este milestone:** solo `amazon` (el
  dataset fixture cubre `electronics`/`home`/`accessories` ×
  `amazon`). "Y otros" queda como un `platform: str` de entrada ya
  soportado por el esquema/API, listo para extender el dataset a otras
  plataformas (Etsy, eBay, ...) sin cambios de contrato — cualquier
  combinación categoría×plataforma no modelada devuelve `REVIEW` con
  datos insuficientes, igual que categoría×mercado desconocido en el
  Agente 4.

## Cómo encaja con lo ya construido (Agentes 1-5)

- **Patrón agente/servicio:** `MarketplaceListingAgent` es puro/sin DB.
  `MarketplaceListingService` resuelve `product_id` + `market` (+
  `platform`, default `"amazon"`) → `Product` (M2, requerido), la
  `ProductAnalysis` de investigación más reciente (M2, opcional, nivel
  de competencia), el `EconomicAnalysis` más reciente (M4, opcional
  pero crítico para el cálculo de comisiones), el `LegalAnalysis` más
  reciente para ese mercado (M5, opcional pero crítico), y el
  `Storefront` más reciente para ese mercado (M6, opcional, para
  enlazar el listing con la tienda/catálogo ya generados) — arma el
  `task_input`, invoca al agente, persiste.
- **Veredicto `listing_status`:** mismo patrón que `launch_status` del
  Agente 5 — `NO_GO` de Economía o Legal, o una política de plataforma
  que prohíba la categoría, bloquean el listing
  (`listing_status="BLOCKED"`); margen neto tras comisiones negativo
  también bloquea (las comisiones se comen el margen real); aprobación
  de categoría pendiente o datos previos incompletos ⇒
  `NEEDS_REVIEW`; todo despejado ⇒ `READY`.
- **API + auditoría + `correlation_id`:** mismo patrón que los
  endpoints anteriores.
- **Capability:** `marketplace_listing_optimization`. Igual que el
  Agente 5, no hay una contraparte "validar-uno" de Milestone 1 que
  preservar — Milestone 1 no tenía ningún agente de marketplace.

## Restricciones globales (heredadas)

- Sin dinero real, cuentas de vendedor reales, ni llamadas a SP-API
  reales.
- Los datos de competencia/comisión/política son deterministas,
  documentados como placeholders, y marcados `data_origin` (ver
  restricción SP-API arriba).
- El Agente 6 nunca publica un listing real ni gestiona stock real; es
  puramente informativo/generativo.
- El núcleo de decisión determinista no se toca — el Agente 6 no se
  cablea en el grafo de tareas del planner.
- Toda tabla nueva nace con RLS activado en su propia migración (ADR 0003).
- Tests antes que implementación. Commit por tarea completada.
- Ningún test de Milestone 1-6 cambia de resultado (salvo el conteo
  total de agentes, que sube de 9 a 10).

---

## Estructura de archivos (adiciones sobre Milestone 6)

```text
backend/
├── app/
│   ├── ai/
│   │   └── mock_marketplace_directory.py  # competencia/comisiones/políticas por categoría×plataforma
│   ├── marketplace/
│   │   ├── listing_content.py   # generador determinista de título/bullets/keywords
│   │   └── service.py           # MarketplaceListingService
│   ├── agents/
│   │   └── marketplace_listing.py   # Agente 6 — capability marketplace_listing_optimization
│   ├── api/
│   │   └── marketplace.py
│   └── db/models/
│       └── marketplace_listing.py   # tabla marketplace_listings
├── alembic/versions/                 # nueva migración incremental
└── tests/
    ├── unit/
    │   ├── test_mock_marketplace_directory.py
    │   ├── test_listing_content.py
    │   └── test_marketplace_listing_agent.py
    ├── integration/
    │   ├── test_marketplace_listing_model.py
    │   ├── test_marketplace_listing_service.py
    │   └── test_marketplace_api.py
    └── e2e/
        └── test_marketplace_listing_to_launch_flow.py

apps/control-center/
├── app/
│   └── marketplace/page.tsx     # listing generado + competencia + comisiones + puente desde Ecommerce
├── lib/api.ts                   # +createMarketplaceListingRun, tipos
└── components/nav-items.ts      # +"Marketplace"
```

---

## Sección A — Fuentes mock y generador de contenido

### Tarea 1: `MockMarketplaceDirectory` — competencia, comisiones y políticas por categoría×plataforma

**Files:**
- Create: `backend/app/ai/mock_marketplace_directory.py`
- Create: `backend/tests/unit/test_mock_marketplace_directory.py`

**Produces:** fuente determinista y fixture-driven (sin red, sin
SP-API real) que simula, para cada par (categoría, plataforma):
competencia (`nº competidores`, `precio medio`, `rating medio`,
`dificultad de buy-box`), comisión (`referral_fee_percent`,
`fulfillment_fee_per_unit`), y política de plataforma
(`approval_required`, `prohibited`, `notes`). Cada bloque de
competencia incluye `data_origin: "simulated_not_sp_api"`.

- [ ] Test: misma consulta → mismo resultado.
- [ ] Test: par (categoría, plataforma) desconocido devuelve `None`.
- [ ] Test: al menos una combinación tiene `approval_required=True`
      (para probar el camino `NEEDS_REVIEW`/`BLOCKED`).
- [ ] Test: el bloque de competencia de cada combinación conocida
      incluye `data_origin="simulated_not_sp_api"`.
- [ ] Implementar con dataset fixture cubriendo
      `electronics`/`home`/`accessories` × `amazon`.
- [ ] Commit: `feat: add mock marketplace competition/commission/policy directory`

**Acceptance:** cero llamadas de red; el docstring del módulo cita
explícitamente la restricción de SP-API del README.

---

### Tarea 2: Generador determinista de contenido de listing

**Files:**
- Create: `backend/app/marketplace/listing_content.py`
- Create: `backend/tests/unit/test_listing_content.py`

**Produces:** `generate_listing_content(*, product_name: str, category: str,
sale_price: float | None, competition: dict | None) -> dict` — título,
bullet points, keywords de backend, deterministas.

- [ ] Test: mismo input → mismo resultado.
- [ ] Test: el título incluye el nombre del producto.
- [ ] Test: maneja `sale_price=None` sin fallar (precio "TBD").
- [ ] Implementar.
- [ ] Commit: `feat: add deterministic marketplace listing content generator`

---

## Sección B — Agente 6

### Tarea 3: `MarketplaceListingAgent` — capability `marketplace_listing_optimization`

**Files:**
- Create: `backend/app/agents/marketplace_listing.py`
- Create: `backend/tests/unit/test_marketplace_listing_agent.py`
- Modify: `backend/app/agents/registry.py`

```python
class MarketplaceListingInput(BaseModel):
    product_name: str
    category: str
    market: str
    platform: str = "amazon"
    sale_price: float | None = None
    unit_landed_cost: float | None = None
    economic_recommendation: str | None = None
    legal_recommendation: str | None = None
    competition_level: str | None = None
```

- [ ] Test: `economic_recommendation="NO_GO"` o `legal_recommendation=
      "NO_GO"` o política `prohibited=True` ⇒ `listing_status="BLOCKED"`,
      `recommendation="NO_GO"`.
- [ ] Test: margen neto tras comisiones negativo (comisión alta +
      margen ya ajustado) ⇒ `listing_status="BLOCKED"`, riesgo explícito
      de que las comisiones absorben el margen.
- [ ] Test: política requiere aprobación de categoría ⇒
      `listing_status="NEEDS_REVIEW"`.
- [ ] Test: todo despejado ⇒ `listing_status="READY"`,
      `recommendation="GO"`, `data` incluye `listing_content`,
      `competition_analysis` (con `data_origin`), `commission_breakdown`
      (con margen neto real), `inventory_policy`
      (`tracking_enabled=False`).
- [ ] Test: categoría×plataforma desconocida ⇒ `REVIEW` con riesgo de
      datos insuficientes.
- [ ] Test: sin `sale_price`/`unit_landed_cost` ⇒ no calcula margen
      neto (lo deja `None`), no falla.
- [ ] Implementar reutilizando `MockMarketplaceDirectory` +
      `generate_listing_content`.
- [ ] Registrar en `build_default_agent_manager()` como
      `agent-marketplace-listing-1`, capability
      `marketplace_listing_optimization`.
- [ ] Commit: `feat: add marketplace listing optimization agent`

**Acceptance:** `AgentResult` válido (ADR 0002); los 9 agentes
existentes siguen pasando sus tests sin modificarse.

---

## Sección C — Persistencia y API

### Tarea 4: Tabla `marketplace_listings` (con RLS desde su propia migración)

**Files:**
- Create: `backend/app/db/models/marketplace_listing.py`
- Modify: `backend/app/db/models/__init__.py`
- Create: Alembic migration (mismo patrón `DO $$ ... ENABLE ROW LEVEL
  SECURITY ... $$`)
- Create: `backend/tests/integration/test_marketplace_listing_model.py`

**Esquema:**
- id, product_id (FK `products.id`), storefront_id (FK
  `storefronts.id`, nullable), market, platform, listing_status,
  recommendation, confidence, data (JSON — listing content, análisis
  de competencia con `data_origin`, desglose de comisiones,
  política de inventario, riesgos, evidencia), correlation_id,
  created_at/updated_at.

- [ ] Test: crear con `product_id` válido, verificar persistencia.
- [ ] Test: FK inválida levanta `IntegrityError`.
- [ ] Implementar modelo + migración; aplicar a Supabase real y
      confirmar `relrowsecurity=true` + `get_advisors` en 0 vía MCP.
- [ ] Commit: `feat: add marketplace listings table with rls enabled`

---

### Tarea 5: `MarketplaceListingService` — resuelve los 5 agentes anteriores y persiste

**Files:**
- Create: `backend/app/marketplace/service.py`
- Create: `backend/tests/integration/test_marketplace_listing_service.py`

- [ ] Test: usa la categoría real del `Product`, el margen/precio real
      del `EconomicAnalysis`, el estado legal real del `LegalAnalysis`
      del mercado correcto, y enlaza el `Storefront` más reciente del
      mismo mercado si existe.
- [ ] Test: `product_id` inexistente ⇒ `NotFoundError`.
- [ ] Test: funciona (con `NEEDS_REVIEW`) sin ningún dato previo de
      M3/M4/M5/M6.
- [ ] Test: usa el `LegalAnalysis`/`Storefront` del mercado correcto
      cuando hay varios mercados para el mismo producto (no mezcla).
- [ ] Test: auditoría con `correlation_id` (acción `marketplace.run`).
- [ ] Commit: `feat: add marketplace listing service resolving all five prior agents`

---

### Tarea 6: API de listing de marketplace

**Files:**
- Create: `backend/app/api/marketplace.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/integration/test_marketplace_api.py`

**Produces:**
- `POST /api/marketplace/runs` → `{product_id, market, platform?}`,
  ejecuta y persiste, devuelve el listing generado.
- `GET /api/marketplace/runs/{correlation_id}` → reconstruido desde DB.
- `GET /api/products/{product_id}/marketplace-listings` → historial.

- [ ] Test: creación exitosa devuelve `listing_content`,
      `competition_analysis`, `commission_breakdown`, `listing_status`.
- [ ] Test: reconstrucción por `correlation_id` idéntica.
- [ ] Test: 404 claro para producto inexistente.
- [ ] Commit: `feat: add marketplace listing api`

---

## Sección D — Control Center

### Tarea 7: Página "Marketplace"

**Files:**
- Create: `apps/control-center/app/marketplace/page.tsx`
- Modify: `apps/control-center/lib/api.ts`
- Modify: `apps/control-center/components/nav-items.ts`
- Modify: `apps/control-center/app/ecommerce/page.tsx` (botón
  "Optimize marketplace listing")

**Produces:** formulario (producto + mercado + plataforma) que
dispara la generación y pinta el listing (título/bullets/keywords),
análisis de competencia (marcado como simulado), desglose de
comisiones con margen neto real, política de inventario, y
`listing_status`.

- [ ] Verificar en navegador (desktop + mobile) con datos reales del
      backend.
- [ ] Commit: `feat: add marketplace page`

**Acceptance:** desde "Ecommerce" se puede pasar a "Marketplace" y ver
el listing generado, cerrando el loop de los 6 agentes.

---

## Sección E — Verificación end-to-end

### Tarea 8: E2E — flujo completo de 6 agentes + doc de cierre + advisor de seguridad

**Files:**
- Create: `backend/tests/e2e/test_marketplace_listing_to_launch_flow.py`
- Create: `docs/milestones/milestone-7-demo.md`

**Escenario:** Research → Sourcing → Economics → Legal → Ecommerce →
Marketplace, verificando:
1. con los 5 agentes anteriores en estado saludable, el listing queda
   `READY`, con `data_origin` marcado en el análisis de competencia;
2. con una categoría que requiere aprobación de plataforma (o un
   análisis legal `NO_GO`), el listing queda `NEEDS_REVIEW`/`BLOCKED`;
3. los 6 `correlation_id` son distintos y reconstruibles.

- [ ] Escribir el test, correr, verificar que pasa.
- [ ] Documentar en `docs/milestones/milestone-7-demo.md` (mismo
      formato que Milestone 2-6), incluyendo una sección explícita
      sobre cómo se cumple/aísla la restricción de datos de SP-API.
- [ ] Ejecutar `get_advisors` (seguridad) contra el proyecto Supabase
      real tras la migración de la Tarea 4, documentar 0 hallazgos.
- [ ] Commit: `test: verify marketplace listing optimization flow end to end`

---

## Definition of Done — Milestone 7

1. `marketplace_listings` es una tabla real, con RLS activado desde su
   propia migración, verificada contra Supabase real.
2. El Agente 6 (`MarketplaceListingAgent`, capability
   `marketplace_listing_optimization`) genera listing, análisis de
   competencia (marcado `data_origin`), desglose de comisiones con
   margen neto real, política de inventario informativa, y un
   veredicto que respeta los `NO_GO` de los Agentes 3 y 4 y las
   políticas de plataforma.
3. `MarketplaceListingService` integra datos reales de los 5 agentes
   anteriores, sin mezclar mercados.
4. Existe una API de listing auditada con `correlation_id`.
5. El Control Center tiene una página "Marketplace" que cierra el loop
   de 6 agentes.
6. **Ningún dato simulado de tipo SP-API se confunde con datos reales**
   — todo está marcado `data_origin` y aislado en un módulo propio,
   documentado explícitamente.
7. El flujo E2E demuestra tanto el camino `READY` como un camino
   bloqueado/en revisión.
8. El linter de seguridad de Supabase sigue en verde tras la migración.
9. `docs/milestones/milestone-7-demo.md` documenta el milestone,
   incluyendo la sección de cumplimiento de la política de SP-API.
10. Ningún test de Milestone 1-6 cambia de resultado (salvo el conteo
    de agentes, actualizado explícitamente).
