# Milestone 10 Demo

**Ticket:** IVA-58 (Linear).

Arquitectura: [ADR 0003](../architecture/adr-0003-rls-deny-by-default.md)
(RLS deny-by-default — `cfo_reports` nace ya con RLS activado) y
[ADR 0004](../architecture/adr-0004-agent-capability-pairs-validate-vs-discover.md)
(convención de capacidades, aplicada como estilo — sin contraparte de
Milestone 1, igual que los Agentes 5-8). Este milestone construye el
**Agente CFO**, identificado como el hueco abierto en el cierre de la
Fase 3 (ver la sección "Cierre de Fase 3" de
[`milestone-9-demo.md`](milestone-9-demo.md)).

## Decisión de alcance (enunciado ambiguo, interpretación documentada)

- **"Informe agregado"** → un reporte persistido y consultable
  (`cfo_reports`), generado bajo demanda vía `POST /api/cfo/runs` — no un
  dashboard en vivo. Misma interpretación que decisiones de alcance
  anteriores.
- **"Reservas de BudgetEngine"** → se agregan `Budget`/`BudgetAllocation`
  (Milestone 1), pero, tal como señaló el propio cierre de Milestone 9,
  hoy nada escribe en `budget_allocations`/`financial_events` (el
  orquestador solo usa un `BudgetState` en memoria por objetivo). El
  informe del CFO agrega estas tablas igualmente (queda listo para cuando
  se persistan) y **expone esto explícitamente como riesgo** en cada
  reporte ("no budget reservations recorded yet: ...") en lugar de
  tratarlo como un bug a resolver en este milestone.
- **Restricción de Verifactu** → fuera de alcance: no existe ningún
  módulo de facturación en el repositorio. El Agente CFO solo agrega
  datos ya persistidos por otros agentes; nunca crea ni modifica
  facturas. Esto queda documentado como *assumption* explícita en el
  propio `CFOAgent` y no se implementó ninguna integración de
  facturación real — se deja como trabajo futuro fuera de este
  milestone, igual que otros agentes documentan sus límites de simulación
  (p. ej. Operations con "sin integración de transportista real").

**Diferencia clave frente a los 8 agentes de Fase 3:** todos ellos operan
por producto (y, la mayoría, por mercado). El Agente CFO es
**catálogo-completo** — cada ejecución agrega todos los productos,
campañas y presupuestos existentes. Por eso su tabla no tiene FK a
`products` (no hay un único producto padre) y su API no tiene un listado
`/api/products/{id}/cfo`; en su lugar expone `GET /api/cfo/runs` (todos
los reportes) y usa `data.included_economic_analysis_ids`/
`data.included_marketing_campaign_ids` para la trazabilidad de qué filas
concretas entraron en cada agregación.

## Flujo completo

```bash
# Generar datos de catálogo con Agentes 1-3 (repetir por producto)
curl -s -X POST http://localhost:8000/api/research/runs \
  -H "Content-Type: application/json" -d '{"category": "home", "max_results": 1}'
curl -s -X POST http://localhost:8000/api/sourcing/runs \
  -H "Content-Type: application/json" \
  -d '{"product_id": "<product_id>", "category": "home", "destination_region": "mexico", "max_results": 5}'
curl -s -X POST http://localhost:8000/api/economics/runs \
  -H "Content-Type: application/json" \
  -d '{"product_id": "<product_id>", "supplier_quote_id": "<quote_id>", "sale_price": 50.0}'
# ... repetir para varios productos, con precios distintos (algunos GO, algunos NO_GO)

# Generar el informe de salud financiera consolidado (Milestone 10, Agente CFO)
curl -s -X POST http://localhost:8000/api/cfo/runs
# -> {"correlation_id": "...", "financial_health_status": "HEALTHY|AT_RISK|CRITICAL|NEEDS_REVIEW",
#     "recommendation": "GO|REVIEW|NO_GO", "confidence": 0.6,
#     "data": {"total_products_analyzed": 2, "go_count": 1, "no_go_count": 1,
#     "no_go_ratio": 0.5, "budget_utilization": null, "total_campaigns": 0,
#     "risks": ["elevated risk concentration: 50% of analyzed products are NO_GO",
#     "no budget reservations recorded yet: ..."], ...}}

curl -s http://localhost:8000/api/cfo/runs/<correlation_id>
curl -s http://localhost:8000/api/cfo/runs
```

O desde el Control Center: **Research → ... → Marketing** (crear datos
reales para varios productos) → **CFO** → *Generate financial health
report* → ver el estado agregado (HEALTHY/AT_RISK/CRITICAL/NEEDS_REVIEW),
la recomendación, el desglose GO/REVIEW/NO_GO, campañas activas y
presupuesto, y los riesgos detectados.

El run del CFO tiene su propio `correlation_id`, reconstruible vía
`GET /api/audit?correlation_id=` — cubierto por
`backend/tests/e2e/test_cfo_aggregation_flow.py`, que agrega 3 productos
(2 GO, 1 NO_GO) más una campaña activa y verifica que el reporte agregado
refleje exactamente esos números.

**Verificado manualmente en el navegador** (Control Center + backend
contra una base SQLite local de desarrollo): con un producto `home` GO a
$50 y un producto `accessories` NO_GO a $1, el informe mostró
`AT_RISK`/`REVIEW` con confianza 60%, "2 total — 1 GO, 0 REVIEW, 1 NO_GO
(50% NO_GO)", y los dos riesgos esperados (concentración de riesgo
elevada y ausencia de reservas de presupuesto persistidas). Verificado
también a 375px de ancho (mobile) — el layout no desborda y el contenido
se mantiene legible.

## Base de datos: tabla `cfo_reports`

`cfo_reports` no tiene FK a `products` (agregación catálogo-completo). RLS
activado en su propia migración
(`0f533b205aef_add_cfo_reports_table.py`), mismo patrón que las tablas de
los milestones anteriores.

**Verificado contra Supabase real.** `alembic upgrade head` se ejecutó
contra el proyecto `amazona` (`833c46295739 → 0f533b205aef`), y
`SELECT relrowsecurity FROM pg_class WHERE relname = 'cfo_reports'`
confirma `true`. `get_advisors` (linter de seguridad de Supabase) reporta
**0 hallazgos** tras la migración.

## Verificar todo en local

```bash
cd backend && ruff check . && mypy app && pytest       # 418 tests
cd apps/control-center && npm run lint && npx next typegen && npx tsc --noEmit && npm test && npm run build
```

---

## Cierre: las tres capas del README quedan cubiertas

Con este milestone, las tres capas que el README original lista al mismo
nivel — Orquestador, Agente CEO, Agente CFO — están todas atendidas:

- **Orquestador (Agente 9):** `CEOOrchestrator`, sin cambios desde
  Milestone 2 (ADR 0001).
- **Agente CEO:** `planner.py` + `decision_engine.py`, sin cambios desde
  Milestone 1 (ADR 0001) — sigue sin necesitar promoción a agente
  direccionable, según el criterio que la propia ADR 0001 fijó
  (autonomía real, que ningún milestone ha requerido todavía).
- **Agente CFO:** construido en este milestone — consolida
  `EconomicAnalysis` + `MarketingCampaign` + reservas de `BudgetEngine` en
  un informe de salud financiera catálogo-completo, siguiendo el mismo
  patrón de tabla+migración+RLS+API+página que los 8 agentes de Fase 3.

No se identifica ningún hueco abierto adicional en el diseño de tres
capas del README original. Trabajo futuro razonable (no bloqueante):
persistir de verdad las reservas de `BudgetEngine` en
`budget_allocations`/`financial_events` (hoy el CFO agrega esas tablas
pero están vacías), e integrar un software de facturación certificado
Verifactu si el proyecto decide abordar facturación — ambos fuera del
alcance de este milestone.
