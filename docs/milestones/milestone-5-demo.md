# Milestone 5 Demo

**Ticket:** IVA-53 (Linear).

Plan completo:
[`docs/superpowers/plans/2026-09-16-amazona-milestone-5.md`](../superpowers/plans/2026-09-16-amazona-milestone-5.md).
Arquitectura:
[ADR 0003](../architecture/adr-0003-rls-deny-by-default.md)
(RLS deny-by-default — `legal_analyses` nace ya con RLS activado) y
[ADR 0004](../architecture/adr-0004-agent-capability-pairs-validate-vs-discover.md)
(pares de capacidades "validar uno" vs "descubrir muchos").

## Flujo completo: Investigación → Sourcing → Economics → Legal → Validación (Fase 3, Agentes 1-4)

```bash
# 1-3. Investigar, sourcear y analizar economía (Fase 3, Agentes 1-3 — sin cambios desde Milestone 2-4)
curl -s -X POST http://localhost:8000/api/research/runs \
  -H "Content-Type: application/json" -d '{"category": "accessories", "max_results": 5}'
curl -s -X POST http://localhost:8000/api/sourcing/runs \
  -H "Content-Type: application/json" \
  -d '{"product_id": "<product_id>", "category": "accessories", "destination_region": "mexico", "max_results": 5}'
curl -s -X POST http://localhost:8000/api/economics/runs \
  -H "Content-Type: application/json" \
  -d '{"product_id": "<product_id>", "supplier_quote_id": "<quote_id>", "sale_price": 20.0}'

# 4. Analizar cumplimiento legal por mercado (Fase 3, Agente 4)
curl -s -X POST http://localhost:8000/api/legal/runs \
  -H "Content-Type: application/json" \
  -d '{"product_id": "<product_id>", "market": "eu"}'
# -> {"correlation_id": "...", "restricted": true, "recommendation": "NO_GO", "confidence": 0.95,
#     "data": {"required_certifications": ["REACH"], "known_risks": [...],
#     "recent_changes": [{"date": "2026-05-01", "description": "..."}],
#     "terms_and_conditions": "DRAFT TEMPLATE ...", "risks": [...], "evidence": [...]}}
# categoría real del producto (de Milestone 2) + mercado → normativa real simulada,
# no un valor de ejemplo hardcodeado.

# 5. Validar el conjunto completo a través del flujo CEO de Milestone 1
curl -s -X POST http://localhost:8000/api/objectives \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Validate <candidate> full compliance chain",
    "created_by": "owner@amazona.local",
    "context": {
      "product_validation": {"estimated_monthly_searches": <demand_signal*15000>, "competition_level": "<competition_level>"},
      "supplier_sourcing": {"unit_cost": <unit_landed_cost>, "lead_time_days": <lead_time_days>, "supplier_verified": <verified>},
      "finance_validation": {"unit_cost": <unit_landed_cost>, "sale_price": <sale_price>, "monthly_unit_sales": <base.monthly_unit_sales>, "monthly_fixed_costs": <monthly_fixed_costs>},
      "legal_validation": {"restricted_category": <restricted>, "requires_certification": <bool(required_certifications)>, "certification_available": false}
    }
  }'

curl -s -X POST http://localhost:8000/api/objectives/<objective_id>/run
```

O desde el Control Center: **Research** (categoría `accessories`) → *Find
suppliers* → **Sourcing** → *Analyze economics* → **Economics** → *Check
legal compliance* → **Legal** (mercado `eu`) → *Run analysis* → ver el
informe (certificaciones requeridas, riesgos, cambios normativos
recientes, borrador de T&C) → *Validate this analysis* → salta a **CEO**
con `legal_validation` precargado desde el resultado real → *Create &
run objective*.

Los cinco runs (investigación, sourcing, análisis económico, análisis
legal y validación) tienen `correlation_id` distintos y son los cinco
100% reconstruibles vía `GET /api/audit?correlation_id=` — cubierto por
`backend/tests/e2e/test_legal_compliance_to_validation_flow.py`.

**Verificado manualmente en el navegador** (Control Center + backend
contra una base SQLite local de desarrollo): con `accessories` en
mercado `eu` (restringido por REACH en el fixture, sin certificación),
el informe legal devolvió `NO_GO`/`restricted=true`, y al validar, la
decisión final del CEO fue **`NO_GO`/`REJECTED`** con
`legal_status=BLOCKED` — el análisis real bloquea el objetivo
exactamente igual que lo haría una categoría restringida real,
demostrando que el reemplazo del placeholder cambia el resultado, no
solo el texto de la UI. Verificado también a 375px de ancho (mobile).

## El placeholder `restricted_category` (pedido explícito de este milestone)

Desde Milestone 1, `context.legal_validation` en la página CEO era un
valor de ejemplo tecleado a mano (`{restricted_category: false}`) — el
mismo problema que tenían `supplier_sourcing`/`finance_validation`
antes de que Sourcing/Economics aparecieran para rellenarlos con datos
reales. Este milestone aplica exactamente ese mecanismo ya establecido:

- La página **Legal** calcula `restricted`/`required_certifications`
  reales con `LegalComplianceAgent`.
- El botón *Validate this analysis* precarga
  `context.legal_validation` (`restricted_category`,
  `requires_certification`, `certification_available`) con esos
  valores reales.
- **No se toca el contrato de `LegalAgent` ni de
  `decision_engine.py`** — se sustituye *quién produce el valor* (un
  humano adivinando vs. un agente que analizó datos reales), igual que
  ya se hizo para `supplier_sourcing`/`finance_validation` en
  Milestone 3/4.

## Cómo encaja el Agente 4 (ADR 0004 aplicada)

- `LegalAgent` (Milestone 1, capability `legal_validation`): valida un
  único conjunto de banderas ya dado dentro del grafo de tareas de un
  objetivo — sin cambios en este milestone.
- `LegalComplianceAgent` (Milestone 5, capability
  `legal_compliance_analysis`): analiza normativa/certificaciones por
  categoría×mercado, riesgos (incluyendo riesgo de importación
  transfronterizo si el proveedor sourceado no está verificado),
  cambios normativos recientes simulados, y genera un borrador de T&C —
  a través de su propio flujo (`/api/legal`, página "Legal"). A
  diferencia del Agente 3, el Agente 4 **no requiere** un
  `SupplierQuote` previo — un producto puede analizarse legalmente
  antes de tener proveedor sourceado.
- **Fuente de datos:** a diferencia del Agente 3 (que solo hacía
  aritmética sobre datos ya reales), el Agente 4 sí necesita su propio
  *mock provider* — `MockRegulatoryDirectory`
  (`backend/app/ai/mock_regulatory_directory.py`) — porque no existe
  ningún dato de normativa dentro del sistema todavía. Datos simulados,
  no normativa real vigente.

Los 8 agentes coexisten registrados en `build_default_agent_manager()`.

## Base de datos: tabla `legal_analyses`

`legal_analyses` vincula un `Product` (y, opcionalmente, un
`SupplierQuote` cuando ya existe sourcing) a un informe legal por
mercado (restringido, recomendación, desglose completo de
certificaciones/riesgos/cambios normativos/T&C en `data`). RLS
activado en su propia migración
(`9c0db4c85343_add_legal_analyses_table.py`), mismo patrón que
`supplier_quotes`/`economic_analyses`.

**Verificado contra Supabase real.** `alembic upgrade head` se ejecutó
contra el proyecto `amazona` (`5264d502182d → 9c0db4c85343`), y
`SELECT relrowsecurity FROM pg_class WHERE relname = 'legal_analyses'`
confirma `true`. `get_advisors` (linter de seguridad de Supabase)
reporta **0 hallazgos** tras la migración.

## Verificar todo en local

```bash
cd backend && ruff check . && mypy app && pytest       # 273 tests
cd apps/control-center && npm run lint && npx next typegen && npx tsc --noEmit && npm test && npm run build
```
