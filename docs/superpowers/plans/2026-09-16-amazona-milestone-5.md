# AMAZONA Milestone 5 Implementation Plan

> **Para agentes que ejecuten este plan:** implementar tarea por tarea con
> TDD, commits pequeños, y revisión después de cada tarea — igual que
> Milestone 1-4.

**Ticket:** IVA-53 (Linear).

**Objetivo:** continuar la Fase 3 del roadmap con el cuarto agente
operativo: **Agente 4, Legal y Compliance**. Dado un producto ya
investigado (Agente 1) y, cuando exista, un proveedor ya sourceado
(Agente 2) y un análisis económico (Agente 3), analiza la normativa
vigente por mercado, revisa requisitos/certificaciones de producto,
evalúa riesgos legales, genera un borrador de términos y condiciones, y
deja constancia de cambios normativos recientes simulados — produciendo
un informe legal y checklist de cumplimiento por producto y mercado.

**Depende de:** Milestone 4 completo, [ADR 0001](../../architecture/adr-0001-orchestrator-vs-ceo.md),
[ADR 0002](../../architecture/adr-0002-agent-messaging-protocol.md),
[ADR 0003](../../architecture/adr-0003-rls-deny-by-default.md), y
[ADR 0004](../../architecture/adr-0004-agent-capability-pairs-validate-vs-discover.md).

## Cómo encaja con lo ya construido (Agentes 1-3)

- **Fuente de datos:** igual que el Agente 3, el Agente 4 no necesita
  datos de mercado reales — pero sí necesita un **directorio mock de
  normativa por categoría×mercado** (`MockRegulatoryDirectory`, en el
  mismo espíritu que `MockTrendsProvider`/`MockSupplierDirectory`),
  porque a diferencia del Agente 3 (que solo hacía aritmética sobre
  datos ya reales), aquí no existe ningún dato previo en el sistema
  sobre normativa — hay que simular esa fuente igual que se simuló
  tendencias/proveedores.
- **Patrón agente/servicio:** `LegalComplianceAgent` es puro/sin DB.
  `LegalComplianceService` resuelve `product_id` (→ categoría real vía
  `Product`) y, si existen, el `SupplierQuote` más reciente (región de
  origen/verificación — relevante para riesgo de importación) y el
  `EconomicAnalysis` más reciente (valor declarado de aduana,
  puramente informativo) del producto, arma el `task_input`, invoca al
  agente, persiste.
- **API + auditoría + `correlation_id`:** mismo patrón que
  `/api/research`, `/api/sourcing`, `/api/economics`.
- **Capability, ADR 0004:** `LegalAgent` (Milestone 1, capability
  `legal_validation`) sigue validando un único conjunto de banderas ya
  dado (`restricted_category`, `requires_certification`,
  `certification_available`) dentro del grafo de tareas de un
  objetivo — **sin cambios**. El Agente 4 es la contraparte
  "descubre/analiza muchos" para el dominio legal: capability nueva
  `legal_compliance_analysis`.
- **El fix del placeholder `restricted_category` (pedido explícito de
  este milestone):** desde Milestone 1, `context.legal_validation` en
  la página CEO era un valor de ejemplo tecleado a mano
  (`{restricted_category: false}`), igual que `supplier_sourcing` y
  `finance_validation` lo eran antes de que Sourcing/Economics
  aparecieran para rellenarlos con datos reales vía el mismo mecanismo
  de *handoff* por query params. Este milestone aplica exactamente ese
  mecanismo ya establecido: la página "Legal" calcula
  `restricted`/`required_certifications` reales con el Agente 4, y el
  botón "Validate this analysis" precarga `context.legal_validation`
  con esos valores reales — **no se toca el contrato de `LegalAgent`
  ni de `decision_engine.py`**, se sustituye *quién produce el valor*
  (un humano adivinando vs. un agente que analizó datos reales), igual
  que ya se hizo para `supplier_sourcing`/`finance_validation`.
- **E2E:** se añade un test nuevo de 5 pasos (Research → Sourcing →
  Economics → Legal → Validation) en vez de modificar los E2E
  existentes.

## Restricciones globales (heredadas)

- Sin dinero real, pedidos, proveedores ni impuestos/normativa reales.
- El directorio de normativa y la plantilla de términos y condiciones
  son deterministas y están documentados explícitamente como
  *placeholders* — **no son asesoría legal real**, mismo disclaimer que
  ya lleva `LegalAgent` desde Milestone 1 ("informational screening
  only, not legal advice").
- El Agente 4 nunca ejecuta una publicación ni compromete un T&C real;
  es puramente informativo. Publicar unos términos y condiciones reales
  sigue pasando por el flujo de aprobación existente.
- El núcleo de decisión determinista no se toca — el Agente 4 no se
  cablea en el grafo de tareas del planner.
- Toda tabla nueva nace con RLS activado en su propia migración (ADR 0003).
- Tests antes que implementación. Commit por tarea completada.
- Ningún test de Milestone 1-4 cambia de resultado (salvo el conteo
  total de agentes, que sube de 7 a 8, y las páginas de Sourcing/
  Economics/CEO, que ganan un puente adicional sin perder los actuales).

---

## Estructura de archivos (adiciones sobre Milestone 4)

```text
backend/
├── app/
│   ├── ai/
│   │   └── mock_regulatory_directory.py   # normativa/certificaciones por categoría×mercado
│   ├── legal/
│   │   ├── terms_template.py              # generador determinista de T&C (placeholder)
│   │   └── service.py                     # LegalComplianceService
│   ├── agents/
│   │   └── legal_compliance.py            # Agente 4 — capability legal_compliance_analysis
│   ├── api/
│   │   └── legal.py
│   └── db/models/
│       └── legal_analysis.py              # tabla legal_analyses
├── alembic/versions/                       # nueva migración incremental
└── tests/
    ├── unit/
    │   ├── test_mock_regulatory_directory.py
    │   ├── test_terms_template.py
    │   └── test_legal_compliance_agent.py
    ├── integration/
    │   ├── test_legal_analysis_model.py
    │   ├── test_legal_compliance_service.py
    │   └── test_legal_api.py
    └── e2e/
        └── test_legal_compliance_to_validation_flow.py

apps/control-center/
├── app/
│   └── legal/page.tsx           # informe legal + checklist + puente a validación
├── lib/api.ts                   # +createLegalAnalysisRun, tipos
└── components/nav-items.ts      # +"Legal"
```

---

## Sección A — Fuentes mock: normativa por categoría×mercado + plantilla de T&C

### Tarea 1: `MockRegulatoryDirectory` — requisitos por categoría×mercado

**Files:**
- Create: `backend/app/ai/mock_regulatory_directory.py`
- Create: `backend/tests/unit/test_mock_regulatory_directory.py`

**Produces:** fuente determinista y fixture-driven (sin red) que simula,
para cada par (categoría, mercado), si la categoría está restringida,
qué certificaciones exige, riesgos legales conocidos, y una lista de
cambios normativos recientes simulados.

- [ ] Test: misma consulta (categoría, mercado) → mismo resultado.
- [ ] Test: par desconocido devuelve `None` (no una excepción, no un
      resultado inventado).
- [ ] Test: al menos una combinación del dataset tiene
      `restricted=True` con certificaciones requeridas — para poder
      probar el camino BLOCKED del agente.
- [ ] Implementar con un dataset fixture embebido cubriendo
      `electronics`/`home`/`accessories` × `us`/`eu`/`mx`.
- [ ] Commit: `feat: add mock regulatory requirements directory`

**Acceptance:** cero llamadas de red; el dataset documenta en un
comentario que los datos son simulados, no normativa real vigente.

---

### Tarea 2: Plantilla determinista de términos y condiciones

**Files:**
- Create: `backend/app/legal/terms_template.py`
- Create: `backend/tests/unit/test_terms_template.py`

**Produces:** `generate_terms_and_conditions(*, category: str, market: str,
product_name: str) -> str` — plantilla de texto determinista,
claramente marcada como borrador/placeholder, no un documento legal
real.

- [ ] Test: mismo input → mismo texto.
- [ ] Test: el texto incluye `product_name`, `category` y `market`.
- [ ] Test: el texto incluye un disclaimer explícito de que es una
      plantilla, no asesoría legal.
- [ ] Implementar.
- [ ] Commit: `feat: add deterministic terms and conditions template generator`

**Acceptance:** función pura, sin dependencias externas.

---

## Sección B — Agente 4

### Tarea 3: `LegalComplianceAgent` — capability `legal_compliance_analysis`

**Files:**
- Create: `backend/app/agents/legal_compliance.py`
- Create: `backend/tests/unit/test_legal_compliance_agent.py`
- Modify: `backend/app/agents/registry.py`

**Produces:** dado un input ya resuelto (categoría, mercado, nombre de
producto, si ya se tiene la certificación requerida, y opcionalmente
región de origen/verificación del proveedor), calcula
restricción/certificaciones/riesgos/cambios normativos/T&C.

```python
class LegalComplianceInput(BaseModel):
    category: str
    market: str
    product_name: str
    certification_available: bool = False
    supplier_verified: bool | None = None
    origin_region: str | None = None
```

- [ ] Test: categoría restringida + certificación requerida no
      disponible ⇒ `status=BLOCKED`, `recommendation="NO_GO"` (mismo
      patrón que `LegalAgent`).
- [ ] Test: certificación requerida pero no disponible, categoría NO
      restringida ⇒ `recommendation="REVIEW"`.
- [ ] Test: sin certificación requerida, sin riesgos ⇒
      `recommendation="GO"`.
- [ ] Test: proveedor no verificado + origen declarado generan un
      riesgo adicional explícito ("cross-border compliance risk").
- [ ] Test: hay cambios normativos recientes en el dataset ⇒ aparecen
      como riesgo explícito.
- [ ] Test: par (categoría, mercado) desconocido ⇒ `COMPLETED` +
      `REVIEW` + riesgo de datos insuficientes (mismo patrón que los
      Agentes 1-3 sin datos).
- [ ] Test: `data` incluye `terms_and_conditions` generado por la
      Tarea 2.
- [ ] Implementar reutilizando `MockRegulatoryDirectory` +
      `generate_terms_and_conditions`.
- [ ] Registrar en `build_default_agent_manager()` como
      `agent-legal-compliance-1`, capability `legal_compliance_analysis`
      — **sin tocar** `agent-legal-1` (`legal_validation`).
- [ ] Commit: `feat: add legal compliance analysis agent`

**Acceptance:** `AgentResult` válido (ADR 0002); los 7 agentes
existentes siguen pasando sus tests sin modificarse.

---

## Sección C — Persistencia y API

### Tarea 4: Tabla `legal_analyses` (con RLS desde su propia migración)

**Files:**
- Create: `backend/app/db/models/legal_analysis.py`
- Modify: `backend/app/db/models/__init__.py`
- Create: Alembic migration (mismo patrón `DO $$ ... ENABLE ROW LEVEL
  SECURITY ... $$` que `60efd4316cac`/`5264d502182d`)
- Create: `backend/tests/integration/test_legal_analysis_model.py`

**Esquema:**
- id, product_id (FK `products.id`), supplier_quote_id (FK
  `supplier_quotes.id`, nullable — no todo análisis legal tiene un
  proveedor sourceado todavía), market, analysis_type (default
  `"legal_compliance"`), restricted (bool), recommendation, confidence,
  data (JSON — certificaciones, riesgos, cambios normativos, T&C,
  evidencia), correlation_id, created_at/updated_at.

- [ ] Test: crear con `product_id` válido (y `supplier_quote_id`
      opcionalmente `None`), verificar persistencia.
- [ ] Test: FK inválida levanta `IntegrityError`.
- [ ] Implementar modelo + migración; aplicar a Supabase real y
      confirmar `relrowsecurity=true` + `get_advisors` en 0 vía MCP,
      igual que en Milestone 4.
- [ ] Commit: `feat: add legal analyses table with rls enabled`

---

### Tarea 5: `LegalComplianceService` — resuelve datos reales y persiste

**Files:**
- Create: `backend/app/legal/service.py`
- Create: `backend/tests/integration/test_legal_compliance_service.py`

**Produces:** dado `product_id` + `market` (+ `certification_available`
opcional), busca el `Product` para la categoría real, el
`SupplierQuote` más reciente del producto (si existe) para
región/verificación, el `EconomicAnalysis` más reciente (si existe,
solo para enriquecer evidencia con el valor declarado), arma el
`task_input`, invoca al agente, persiste, audita
(`legal.run`).

- [ ] Test: usa la categoría real del `Product`, no un valor por
      defecto.
- [ ] Test: si existe un `SupplierQuote`, el análisis usa su región y
      verificación reales.
- [ ] Test: `product_id` inexistente ⇒ `NotFoundError`.
- [ ] Test: funciona igual sin `SupplierQuote`/`EconomicAnalysis`
      previos (no son obligatorios, a diferencia de
      `supplier_quote_id` en el Agente 3).
- [ ] Test: auditoría con `correlation_id`.
- [ ] Commit: `feat: add legal compliance service resolving real product and sourcing data`

---

### Tarea 6: API de análisis legal

**Files:**
- Create: `backend/app/api/legal.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/integration/test_legal_api.py`

**Produces:**
- `POST /api/legal/runs` → `{product_id, market,
  certification_available?}`, ejecuta y persiste, devuelve el informe.
- `GET /api/legal/runs/{correlation_id}` → reconstruido desde DB.
- `GET /api/products/{product_id}/legal` → historial de análisis legal
  para un producto (el checklist de cumplimiento acumulado).

- [ ] Test: creación exitosa devuelve certificaciones/riesgos/T&C y
      `recommendation`.
- [ ] Test: reconstrucción por `correlation_id` idéntica.
- [ ] Test: 404 claro para producto inexistente.
- [ ] Commit: `feat: add legal compliance analysis api`

---

## Sección D — Control Center

### Tarea 7: Página "Legal" + reemplazo real del placeholder `restricted_category`

**Files:**
- Create: `apps/control-center/app/legal/page.tsx`
- Modify: `apps/control-center/lib/api.ts`
- Modify: `apps/control-center/components/nav-items.ts`
- Modify: `apps/control-center/app/economics/page.tsx` (botón "Check
  legal compliance" junto a "Validate this analysis")
- Modify: `apps/control-center/app/ceo/page.tsx` (`buildInitialState`
  lee `restricted`/`required_certifications`/`certification_available`
  de query params y rellena `context.legal_validation` con ellos —
  **sustituyendo el placeholder** `{restricted_category: false}`
  hardcodeado desde Milestone 1 cuando el handoff viene de Legal)

**Produces:** formulario (producto + mercado) que dispara el análisis
y pinta certificaciones requeridas, riesgos, cambios normativos
recientes y el borrador de T&C, con recomendación; botón "Validate
this analysis" que salta a CEO con `legal_validation` precargado desde
el resultado real.

- [ ] Verificar en navegador (desktop + mobile) con datos reales del
      backend.
- [ ] Commit: `feat: add legal page and replace restricted_category placeholder with real analysis`

**Acceptance:** desde "Economics" (o directamente desde "Research") se
puede pasar a "Legal", ver el informe, y pasar a validación con
`legal_validation` poblado por datos reales — cerrando el loop
Investigación → Sourcing → Análisis Económico → Legal → Validación.

---

## Sección E — Verificación end-to-end

### Tarea 8: E2E — flujo completo de 5 pasos + doc de cierre + advisor de seguridad

**Files:**
- Create: `backend/tests/e2e/test_legal_compliance_to_validation_flow.py`
- Create: `docs/milestones/milestone-5-demo.md`

**Escenario:** Research → Sourcing → Economics → Legal → Validation,
verificando 5 `correlation_id` distintos, cada uno reconstruible, y
que la evidencia de `legal_validation` en la decisión final refleja el
resultado real del Agente 4 (no el placeholder `{restricted_category:
false}` de Milestone 1).

- [ ] Escribir el test, correr, verificar que pasa.
- [ ] Documentar en `docs/milestones/milestone-5-demo.md` (mismo
      formato que Milestone 2/3/4).
- [ ] Ejecutar `get_advisors` (seguridad) contra el proyecto Supabase
      real tras la migración de la Tarea 4, documentar 0 hallazgos.
- [ ] Commit: `test: verify legal compliance to validation flow end to end`

---

## Definition of Done — Milestone 5

1. `legal_analyses` es una tabla real, con RLS activado desde su
   propia migración, verificada contra Supabase real.
2. El Agente 4 (`LegalComplianceAgent`, capability
   `legal_compliance_analysis`) analiza normativa/certificaciones por
   categoría×mercado, evalúa riesgos, y genera un borrador de T&C — sin
   tocar `LegalAgent`.
3. `LegalComplianceService` resuelve `product_id`/`market` (y,
   opcionalmente, sourcing/economics previos) a datos reales.
4. Existe una API de análisis legal auditada con `correlation_id`.
5. El Control Center tiene una página "Legal" que conecta el loop
   completo de 4 agentes con Validación.
6. **El placeholder `restricted_category` de Milestone 1 se sustituye
   por análisis real** cuando el handoff viene de la página Legal —
   sin cambiar el contrato de `LegalAgent`/`decision_engine.py`.
7. El flujo E2E de 5 pasos es reproducible y trazable.
8. El linter de seguridad de Supabase sigue en verde tras la migración.
9. `docs/milestones/milestone-5-demo.md` documenta el milestone en el
   mismo formato que Milestone 2/3/4.
10. Ningún test de Milestone 1-4 cambia de resultado (salvo el conteo
    de agentes, actualizado explícitamente).
