# AMAZONA Milestone 6 Implementation Plan

> **Para agentes que ejecuten este plan:** implementar tarea por tarea con
> TDD, commits pequeños, y revisión después de cada tarea — igual que
> Milestone 1-5.

**Ticket:** IVA-54 (Linear).

**Objetivo:** continuar la Fase 3 del roadmap con el quinto agente
operativo: **Agente 5, E-commerce y Webs de Venta**. Dado un producto ya
investigado (Agente 1), sourceado (Agente 2), con análisis económico
(Agente 3) y análisis legal (Agente 4) — todos ya persistidos — genera
una tienda/landing page lista para lanzar: copy de landing page, plan
de pasarela de pago (simulado), entrada de catálogo, y recomendaciones
de optimización de conversión, con un veredicto de "listo para lanzar"
que depende de que los análisis económico y legal previos no estén en
`NO_GO`.

**Depende de:** Milestone 5 completo, [ADR 0001](../../architecture/adr-0001-orchestrator-vs-ceo.md),
[ADR 0002](../../architecture/adr-0002-agent-messaging-protocol.md),
[ADR 0003](../../architecture/adr-0003-rls-deny-by-default.md), y
[ADR 0004](../../architecture/adr-0004-agent-capability-pairs-validate-vs-discover.md).

## Decisión de alcance (pedida explícitamente: interpretar y documentar)

El enunciado es amplio ("generar tiendas online, crear landing pages,
integrar pasarelas de pago, optimizar conversión, gestionar catálogo").
Interpretación adoptada para este milestone, con el mismo espíritu de
Milestone 1 ("sin dinero real, pedidos, proveedores ni impuestos
reales") aplicado a e-commerce:

- **"Generar tiendas online" / "crear landing pages"** → generación
  determinista de contenido (slug de tienda, copy de landing page:
  titular, subtitular, bullets, CTA) a partir de datos reales del
  producto — no se despliega ninguna tienda real (Shopify/WooCommerce/
  etc.), no hay hosting ni dominio real.
- **"Integrar pasarelas de pago"** → un *plan* de integración
  determinista por mercado (pasarela recomendada + checklist de pasos),
  siempre en modo simulado/test — **nunca** se conecta una cuenta real
  ni se procesa un cobro real. Pasar a modo real queda explícitamente
  marcado como una acción que requiere aprobación humana futura, nunca
  automática.
- **"Optimizar conversión"** → recomendaciones deterministas derivadas
  de datos reales ya persistidos (margen del Agente 3, nivel de
  competencia del Agente 1) — no hay A/B testing real ni tráfico real
  que analizar todavía.
- **"Gestionar catálogo"** → una entrada de catálogo por producto+mercado
  (SKU, precio, categoría, estado de cumplimiento, lead time) derivada
  de los 4 agentes anteriores, persistida — no un sistema de inventario
  completo.
- **Veredicto "listo para lanzar":** el Agente 5 es el primer agente
  cuyo resultado depende explícitamente de que los Agentes 3 y 4 no
  hayan devuelto `NO_GO` — si el análisis económico o legal más
  reciente del producto es `NO_GO`, el Agente 5 marca la tienda como
  `BLOCKED` y no genera un "listo para lanzar", igual que un negocio
  real no lanzaría una tienda para un producto inviable o bloqueado
  legalmente.

## Diferencia clave con los Agentes 2-4 (no hay contraparte "validar-uno")

A diferencia de los Agentes 2, 3 y 4 —que coexisten con un agente
"validar-uno" ya existente de Milestone 1 (`SupplierAgent`,
`FinanceAgent`, `LegalAgent`)—, **Milestone 1 nunca tuvo un agente de
e-commerce**. No hay ningún par de capacidades que preservar aquí; ADR
0004 (la convención de nombrado y reparto de responsabilidades) sigue
aplicando como *estilo* — el Agente 5 vive fuera del grafo fijo del
planner/`decision_engine.py`, expone su propio flujo de discovery, y
nunca sustituye la aprobación humana— pero no hay un "agente gemelo"
que dejar intacto, porque no existía nada previo en este dominio.

## Cómo encaja con lo ya construido (Agentes 1-4)

- **Fuente de datos:** el Agente 5 no necesita ningún *mock provider*
  de datos externos nuevos — reutiliza generadores de contenido
  deterministas (mismo espíritu que `terms_template.py` del Agente 4):
  copy de landing page, plan de pasarela de pago por mercado, consejos
  de conversión. Todo documentado como placeholder.
- **Patrón agente/servicio:** `EcommerceStorefrontAgent` es puro/sin
  DB. `EcommerceStorefrontService` resuelve `product_id` + `market` →
  `Product` (M2, requerido), la `ProductAnalysis` de investigación más
  reciente (M2, opcional, para nivel de competencia), el `SupplierQuote`
  más reciente (M3, opcional, para lead time), el `EconomicAnalysis`
  más reciente (M4, opcional pero crítico para precio/veredicto), y el
  `LegalAnalysis` más reciente para ese mercado (M5, opcional pero
  crítico para el veredicto) — arma el `task_input`, invoca al agente,
  persiste.
- **API + auditoría + `correlation_id`:** mismo patrón que los
  endpoints anteriores.
- **Capability:** `ecommerce_storefront_generation`.

## Restricciones globales (heredadas)

- Sin dinero real, tiendas reales, dominios reales, ni cobros reales.
- Los generadores de copy/pasarela/conversión son deterministas y
  están documentados explícitamente como *placeholders*.
- El Agente 5 nunca publica una tienda real ni activa una pasarela de
  pago real; es puramente informativo/generativo. Cualquier paso hacia
  producción real queda marcado como pendiente de aprobación humana.
- El núcleo de decisión determinista no se toca — el Agente 5 no se
  cablea en el grafo de tareas del planner.
- Toda tabla nueva nace con RLS activado en su propia migración (ADR 0003).
- Tests antes que implementación. Commit por tarea completada.
- Ningún test de Milestone 1-5 cambia de resultado (salvo el conteo
  total de agentes, que sube de 8 a 9).

---

## Estructura de archivos (adiciones sobre Milestone 5)

```text
backend/
├── app/
│   ├── ecommerce/
│   │   ├── content.py           # generadores deterministas: slug, landing copy,
│   │   │                        #   plan de pasarela de pago, consejos de conversión
│   │   └── service.py           # EcommerceStorefrontService
│   ├── agents/
│   │   └── ecommerce_storefront.py  # Agente 5 — capability ecommerce_storefront_generation
│   ├── api/
│   │   └── ecommerce.py
│   └── db/models/
│       └── storefront.py        # tabla storefronts
├── alembic/versions/              # nueva migración incremental
└── tests/
    ├── unit/
    │   ├── test_ecommerce_content.py
    │   └── test_ecommerce_storefront_agent.py
    ├── integration/
    │   ├── test_storefront_model.py
    │   ├── test_ecommerce_storefront_service.py
    │   └── test_ecommerce_api.py
    └── e2e/
        └── test_ecommerce_storefront_to_launch_flow.py

apps/control-center/
├── app/
│   └── ecommerce/page.tsx       # tienda generada + catálogo + puente desde Legal
├── lib/api.ts                   # +createStorefrontRun, tipos
└── components/nav-items.ts      # +"Ecommerce"
```

---

## Sección A — Generadores deterministas de contenido

### Tarea 1: `content.py` — slug, landing page, pasarela de pago, conversión

**Files:**
- Create: `backend/app/ecommerce/content.py`
- Create: `backend/tests/unit/test_ecommerce_content.py`

**Produces:** funciones puras:

```python
def generate_store_slug(product_name: str) -> str
def generate_landing_page_copy(*, product_name: str, category: str, sale_price: float | None,
                                 competition_level: str | None) -> dict
def generate_payment_gateway_plan(market: str) -> dict   # gateway sugerida (test mode) + checklist
def generate_conversion_tips(*, margin_percent: float | None, competition_level: str | None) -> list[str]
```

- [ ] Test: `generate_store_slug` es determinista, en minúsculas, sin
      espacios ni caracteres especiales.
- [ ] Test: `generate_landing_page_copy` incluye el nombre del
      producto y, si `sale_price` es `None`, un placeholder explícito
      ("price TBD") en vez de fallar.
- [ ] Test: `generate_payment_gateway_plan` siempre marca
      `requires_human_approval=True` para pasar a modo real, para
      cualquier mercado conocido (`us`/`eu`/`mx`).
- [ ] Test: `generate_payment_gateway_plan` con mercado desconocido
      devuelve un plan genérico, no una excepción.
- [ ] Test: `generate_conversion_tips` devuelve un consejo distinto
      cuando el margen es bajo (`<0.2`) frente a cuando es saludable.
- [ ] Implementar.
- [ ] Commit: `feat: add deterministic ecommerce content generators`

**Acceptance:** funciones puras, sin DB ni red; el plan de pasarela de
pago documenta explícitamente que es simulado y que ir a producción
real requiere aprobación humana.

---

## Sección B — Agente 5

### Tarea 2: `EcommerceStorefrontAgent` — capability `ecommerce_storefront_generation`

**Files:**
- Create: `backend/app/agents/ecommerce_storefront.py`
- Create: `backend/tests/unit/test_ecommerce_storefront_agent.py`
- Modify: `backend/app/agents/registry.py`

```python
class EcommerceStorefrontInput(BaseModel):
    product_name: str
    category: str
    market: str
    sale_price: float | None = None
    margin_percent: float | None = None
    economic_recommendation: str | None = None
    legal_recommendation: str | None = None
    restricted: bool | None = None
    lead_time_days: int | None = None
    competition_level: str | None = None
```

- [ ] Test: `economic_recommendation="NO_GO"` o
      `legal_recommendation="NO_GO"` ⇒ `launch_status="BLOCKED"`,
      `recommendation="NO_GO"`, riesgo explícito indicando cuál de los
      dos bloqueó.
- [ ] Test: sin análisis económico o legal previos (`None`) ⇒
      `launch_status="NEEDS_REVIEW"`, `recommendation="REVIEW"`, riesgo
      de datos insuficientes (mismo patrón que Agentes 1-4).
- [ ] Test: `economic_recommendation="REVIEW"` (sin bloqueo) ⇒
      `launch_status="NEEDS_REVIEW"`, `recommendation="REVIEW"`.
- [ ] Test: ambos `"GO"` ⇒ `launch_status="READY"`,
      `recommendation="GO"`, y `data` incluye `landing_page_copy`,
      `payment_gateway_plan`, `catalog_entry`, `conversion_tips`.
- [ ] Test: `catalog_entry` refleja `sale_price`/`lead_time_days`
      reales pasados, no valores por defecto.
- [ ] Implementar reutilizando `app/ecommerce/content.py`.
- [ ] Registrar en `build_default_agent_manager()` como
      `agent-ecommerce-storefront-1`, capability
      `ecommerce_storefront_generation`.
- [ ] Commit: `feat: add ecommerce storefront generation agent`

**Acceptance:** `AgentResult` válido (ADR 0002); los 8 agentes
existentes siguen pasando sus tests sin modificarse.

---

## Sección C — Persistencia y API

### Tarea 3: Tabla `storefronts` (con RLS desde su propia migración)

**Files:**
- Create: `backend/app/db/models/storefront.py`
- Modify: `backend/app/db/models/__init__.py`
- Create: Alembic migration (mismo patrón `DO $$ ... ENABLE ROW LEVEL
  SECURITY ... $$` que las migraciones anteriores)
- Create: `backend/tests/integration/test_storefront_model.py`

**Esquema:**
- id, product_id (FK `products.id`), market, store_slug,
  launch_status (`READY|NEEDS_REVIEW|BLOCKED`), recommendation,
  confidence, data (JSON — landing page copy, plan de pasarela,
  catálogo, consejos de conversión, riesgos, evidencia),
  correlation_id, created_at/updated_at.

- [ ] Test: crear con `product_id` válido, verificar persistencia.
- [ ] Test: FK inválida levanta `IntegrityError`.
- [ ] Implementar modelo + migración; aplicar a Supabase real y
      confirmar `relrowsecurity=true` + `get_advisors` en 0 vía MCP.
- [ ] Commit: `feat: add storefronts table with rls enabled`

---

### Tarea 4: `EcommerceStorefrontService` — resuelve los 4 agentes anteriores y persiste

**Files:**
- Create: `backend/app/ecommerce/service.py`
- Create: `backend/tests/integration/test_ecommerce_storefront_service.py`

**Produces:** dado `product_id` + `market`, resuelve `Product`
(requerido), la `ProductAnalysis` de investigación más reciente
(opcional), el `SupplierQuote` más reciente (opcional), el
`EconomicAnalysis` más reciente (opcional), y el `LegalAnalysis` más
reciente para ese mercado (opcional), arma el `task_input`, invoca al
agente, persiste, audita (`ecommerce.run`).

- [ ] Test: con los 4 agentes anteriores ya corridos para el mismo
      producto, el resultado usa sus datos reales (precio, margen,
      lead time, nivel de competencia, estado legal).
- [ ] Test: `product_id` inexistente ⇒ `NotFoundError`.
- [ ] Test: funciona (con `REVIEW`) sin ningún dato previo de M3/M4/M5.
- [ ] Test: usa el `LegalAnalysis` del mercado correcto cuando hay
      análisis legales de varios mercados para el mismo producto (no
      mezcla mercados).
- [ ] Test: auditoría con `correlation_id`.
- [ ] Commit: `feat: add ecommerce storefront service resolving all four prior agents`

---

### Tarea 5: API de generación de tienda

**Files:**
- Create: `backend/app/api/ecommerce.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/integration/test_ecommerce_api.py`

**Produces:**
- `POST /api/ecommerce/runs` → `{product_id, market}`, ejecuta y
  persiste, devuelve la tienda generada.
- `GET /api/ecommerce/runs/{correlation_id}` → reconstruido desde DB.
- `GET /api/products/{product_id}/storefronts` → historial de tiendas
  generadas para un producto.

- [ ] Test: creación exitosa devuelve landing page copy, plan de
      pasarela, catálogo y `launch_status`.
- [ ] Test: reconstrucción por `correlation_id` idéntica.
- [ ] Test: 404 claro para producto inexistente.
- [ ] Commit: `feat: add ecommerce storefront generation api`

---

## Sección D — Control Center

### Tarea 6: Página "Ecommerce"

**Files:**
- Create: `apps/control-center/app/ecommerce/page.tsx`
- Modify: `apps/control-center/lib/api.ts`
- Modify: `apps/control-center/components/nav-items.ts`
- Modify: `apps/control-center/app/legal/page.tsx` (botón "Generate
  storefront" junto a "Validate this analysis")

**Produces:** formulario (producto + mercado) que dispara la
generación y pinta el copy de landing page, el plan de pasarela de
pago (con su checklist y el aviso de aprobación humana), la entrada de
catálogo, los consejos de conversión, y el `launch_status`.

- [ ] Verificar en navegador (desktop + mobile) con datos reales del
      backend.
- [ ] Commit: `feat: add ecommerce page`

**Acceptance:** desde "Legal" se puede pasar a "Ecommerce" y ver la
tienda generada, cerrando el loop de los 5 agentes.

---

## Sección E — Verificación end-to-end

### Tarea 7: E2E — flujo completo de 5 agentes + doc de cierre + advisor de seguridad

**Files:**
- Create: `backend/tests/e2e/test_ecommerce_storefront_to_launch_flow.py`
- Create: `docs/milestones/milestone-6-demo.md`

**Escenario:** Research → Sourcing → Economics → Legal → Ecommerce,
verificando que:
1. con los 4 agentes anteriores en estado saludable (`GO`), el Agente 5
   devuelve `launch_status="READY"`;
2. con un análisis legal `NO_GO` (categoría restringida sin
   certificación, igual que en Milestone 5), el Agente 5 devuelve
   `launch_status="BLOCKED"` — la tienda nunca se marca lista para
   lanzar sobre un producto legalmente bloqueado;
3. los 5 `correlation_id` son distintos y reconstruibles.

- [ ] Escribir el test, correr, verificar que pasa.
- [ ] Documentar en `docs/milestones/milestone-6-demo.md` (mismo
      formato que Milestone 2-5).
- [ ] Ejecutar `get_advisors` (seguridad) contra el proyecto Supabase
      real tras la migración de la Tarea 3, documentar 0 hallazgos.
- [ ] Commit: `test: verify ecommerce storefront generation blocks on legal or economic no-go`

---

## Definition of Done — Milestone 6

1. `storefronts` es una tabla real, con RLS activado desde su propia
   migración, verificada contra Supabase real.
2. El Agente 5 (`EcommerceStorefrontAgent`, capability
   `ecommerce_storefront_generation`) genera landing page, plan de
   pasarela de pago (simulado, con aprobación humana requerida para
   producción real), entrada de catálogo, y consejos de conversión —
   con un veredicto de lanzamiento que respeta los `NO_GO` de los
   Agentes 3 y 4.
3. `EcommerceStorefrontService` integra datos reales de los 4 agentes
   anteriores, sin mezclar mercados.
4. Existe una API de generación de tienda auditada con
   `correlation_id`.
5. El Control Center tiene una página "Ecommerce" que cierra el loop
   de 5 agentes.
6. El flujo E2E demuestra tanto el camino `READY` como el `BLOCKED`.
7. El linter de seguridad de Supabase sigue en verde tras la migración.
8. `docs/milestones/milestone-6-demo.md` documenta el milestone en el
   mismo formato que Milestone 2-5, incluyendo la decisión de alcance
   explícita sobre pasarelas de pago/tiendas simuladas.
9. Ningún test de Milestone 1-5 cambia de resultado (salvo el conteo
   de agentes, actualizado explícitamente).
