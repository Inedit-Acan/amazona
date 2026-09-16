# Milestone 6 Demo

**Ticket:** IVA-54 (Linear).

Plan completo:
[`docs/superpowers/plans/2026-09-16-amazona-milestone-6.md`](../superpowers/plans/2026-09-16-amazona-milestone-6.md).
Arquitectura:
[ADR 0003](../architecture/adr-0003-rls-deny-by-default.md)
(RLS deny-by-default — `storefronts` nace ya con RLS activado) y
[ADR 0004](../architecture/adr-0004-agent-capability-pairs-validate-vs-discover.md)
(convención de capacidades, aplicada como estilo aunque este agente no
tiene contraparte de Milestone 1 — ver más abajo).

## Decisión de alcance (enunciado ambiguo, interpretación documentada)

El enunciado de Milestone 6 era amplio ("generar tiendas online, crear
landing pages, integrar pasarelas de pago, optimizar conversión,
gestionar catálogo"). Interpretación adoptada, con el mismo espíritu de
Milestone 1 ("sin dinero real, pedidos, proveedores ni impuestos
reales") aplicado a e-commerce:

- **Tiendas/landing pages** → generación determinista de contenido
  (slug, titular, subtitular, bullets, CTA) a partir de datos reales —
  no se despliega ninguna tienda real, no hay hosting ni dominio real.
- **Pasarelas de pago** → un *plan* de integración determinista por
  mercado (pasarela recomendada + checklist), siempre en modo
  simulado/test. Pasar a modo real está explícitamente marcado como
  `requires_human_approval=True` — nunca automático.
- **Optimización de conversión** → consejos deterministas derivados de
  datos reales ya persistidos (margen del Agente 3, competencia del
  Agente 1) — no hay A/B testing real ni tráfico real todavía.
- **Gestión de catálogo** → una entrada de catálogo por producto+mercado
  (SKU, precio, categoría, estado legal, lead time), persistida.
- **Veredicto "listo para lanzar":** el Agente 5 es el primero cuyo
  resultado depende explícitamente de que los Agentes 3 (económico) y 4
  (legal) no hayan devuelto `NO_GO` para el mismo producto/mercado.

## Diferencia con los Agentes 2-4: sin contraparte de Milestone 1

A diferencia de `SupplierAgent`/`FinanceAgent`/`LegalAgent`, **Milestone
1 nunca tuvo un agente de e-commerce** — no hay ningún par de
capacidades "validar-uno"/"descubrir-muchos" que preservar aquí. El
Agente 5 sigue el *estilo* de ADR 0004 (vive fuera del grafo fijo del
planner/`decision_engine.py`, expone su propio flujo, nunca sustituye
la aprobación humana) pero es la primera capability nueva sin gemelo.

## Flujo completo: Investigación → Sourcing → Economics → Legal → Ecommerce (Fase 3, Agentes 1-5)

```bash
# 1-3. Investigar, sourcear y analizar economía (sin cambios desde Milestone 2-4)
curl -s -X POST http://localhost:8000/api/research/runs \
  -H "Content-Type: application/json" -d '{"category": "electronics", "max_results": 5}'
curl -s -X POST http://localhost:8000/api/sourcing/runs \
  -H "Content-Type: application/json" \
  -d '{"product_id": "<product_id>", "category": "electronics", "destination_region": "mexico", "max_results": 5}'
curl -s -X POST http://localhost:8000/api/economics/runs \
  -H "Content-Type: application/json" \
  -d '{"product_id": "<product_id>", "supplier_quote_id": "<quote_id>", "sale_price": 20.0}'

# 4. Analizar cumplimiento legal (sin cambios desde Milestone 5)
curl -s -X POST http://localhost:8000/api/legal/runs \
  -H "Content-Type: application/json" \
  -d '{"product_id": "<product_id>", "market": "us", "certification_available": true}'

# 5. Generar la tienda/landing page (Fase 3, Agente 5)
curl -s -X POST http://localhost:8000/api/ecommerce/runs \
  -H "Content-Type: application/json" \
  -d '{"product_id": "<product_id>", "market": "us"}'
# -> {"correlation_id": "...", "launch_status": "READY|NEEDS_REVIEW|BLOCKED",
#     "recommendation": "GO|REVIEW|NO_GO", "data": {"landing_page_copy": {...},
#     "payment_gateway_plan": {"gateway": "...", "mode": "test",
#     "requires_human_approval": true, "checklist": [...]},
#     "catalog_entry": {"sku": ..., "price": 20.0, "lead_time_days": ...},
#     "conversion_tips": [...], "risks": [...], "evidence": [...]}}
```

O desde el Control Center: **Research** → *Find suppliers* → **Sourcing**
→ *Analyze economics* → **Economics** → *Check legal compliance* →
**Legal** (con "Required certifications already held" marcado si aplica)
→ *Run analysis* → *Generate storefront* → **Ecommerce** → ver el
borrador de tienda (copy, catálogo, plan de pasarela, consejos de
conversión) y su `launch_status`.

Los cinco runs tienen `correlation_id` distintos, todos reconstruibles
vía `GET /api/audit?correlation_id=` — cubierto por
`backend/tests/e2e/test_ecommerce_storefront_to_launch_flow.py`, que
verifica tanto el camino sano (`READY`) como el camino bloqueado por un
análisis legal `NO_GO` (`BLOCKED`) — la tienda nunca se marca lista
para lanzar sobre un producto legalmente bloqueado o económicamente
inviable.

**Verificado manualmente en el navegador** (Control Center + backend
contra una base SQLite local de desarrollo): con `electronics` en
mercado `eu` y certificación marcada como disponible (legal `GO`), el
Agente 5 generó una tienda `READY` con landing page, catálogo, y plan
de pasarela de pago con su checklist y el aviso de aprobación humana
para pasar a producción real. Verificado también a 375px de ancho
(mobile).

## Fuentes/generadores deterministas

- `backend/app/ecommerce/content.py`: `generate_store_slug`,
  `generate_landing_page_copy` (maneja precio ausente con "TBD"),
  `generate_payment_gateway_plan` (por mercado, siempre modo test,
  siempre `requires_human_approval=True`), `generate_conversion_tips`
  (basados en margen/competencia reales). Documentados como
  placeholders, mismo estándar que `MockTrendsProvider`/
  `estimate_logistics_cost`/`terms_template.py`.

## Base de datos: tabla `storefronts`

`storefronts` vincula un `Product` a una tienda generada por mercado
(`launch_status`, recomendación, desglose completo en `data`). RLS
activado en su propia migración
(`3e7d4898bef2_add_storefronts_table.py`), mismo patrón que las tablas
de los milestones anteriores.

**Verificado contra Supabase real.** `alembic upgrade head` se ejecutó
contra el proyecto `amazona` (`9c0db4c85343 → 3e7d4898bef2`), y
`SELECT relrowsecurity FROM pg_class WHERE relname = 'storefronts'`
confirma `true`. `get_advisors` (linter de seguridad de Supabase)
reporta **0 hallazgos** tras la migración.

## Verificar todo en local

```bash
cd backend && ruff check . && mypy app && pytest       # 303 tests
cd apps/control-center && npm run lint && npx next typegen && npx tsc --noEmit && npm test && npm run build
```
