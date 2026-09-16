# Milestone 7 Demo

**Ticket:** IVA-55 (Linear).

Plan completo:
[`docs/superpowers/plans/2026-09-16-amazona-milestone-7.md`](../superpowers/plans/2026-09-16-amazona-milestone-7.md).
Arquitectura:
[ADR 0003](../architecture/adr-0003-rls-deny-by-default.md)
(RLS deny-by-default — `marketplace_listings` nace ya con RLS activado)
y [ADR 0004](../architecture/adr-0004-agent-capability-pairs-validate-vs-discover.md)
(convención de capacidades, aplicada como estilo — sin contraparte de
Milestone 1, igual que el Agente 5).

## Cumplimiento de la política de datos de Amazon SP-API

Restricción obligatoria del proyecto (`README.md`): **"Amazon SP-API:
prohibido usar sus datos para entrenar modelos."** Este es el primer
milestone que trata datos propios de un vendedor de Amazon (listings,
comisiones, competencia, políticas de categoría) — exactamente el tipo
de dato que en un sistema real vendría de la SP-API.

**Cómo se cumple:** no hay ninguna integración real con SP-API en este
milestone (sin cuenta de vendedor, sin credenciales). Todo dato de
competencia/comisión/política es simulado, generado por
`MockMarketplaceDirectory` (`backend/app/ai/mock_marketplace_directory.py`),
un módulo aislado cuyo docstring cita esta restricción explícitamente.
Cada bloque de análisis de competencia incluye un campo
`data_origin: "simulated_not_sp_api"` — tanto en la respuesta del
agente como en lo persistido en `marketplace_listings.data` — para que
sea imposible confundirlo con datos reales de SP-API ahora o si en el
futuro se integra la API real. Ningún componente de este proyecto
entrena modelos con ningún dato, así que el cumplimiento práctico es
marcar el origen y aislar el módulo, dejando la puerta cerrada por
diseño.

## Decisión de alcance (enunciado ambiguo, interpretación documentada)

- **Crear/optimizar listings** → contenido determinista (título,
  bullets, keywords de backend) — no se publica nada real en Amazon ni
  en ninguna plataforma.
- **Gestionar inventario (sin stock)** → un bloque informativo
  (`tracking_enabled: false`, método de fulfillment simulado) —
  explícitamente sin números de stock real.
- **Analizar competencia** → datos simulados marcados `data_origin`
  (ver arriba).
- **Controlar comisiones** → cálculo real del margen neto tras
  comisión de referencia + tarifa de fulfillment simuladas, usando el
  coste aterrizado y precio de venta **reales** del Agente 3.
- **Cumplir políticas de plataforma** → directorio mock de políticas
  por categoría×plataforma (aprobación de categoría, prohibiciones),
  mismo espíritu que `MockRegulatoryDirectory` del Agente 4 pero para
  reglas de la plataforma, no de un gobierno.
- **Plataformas modeladas:** solo `amazon` en este milestone. El
  esquema/API ya soporta un campo `platform` para "y otros" sin cambios
  de contrato; cualquier categoría×plataforma no modelada devuelve
  `REVIEW`.

## Flujo completo: Investigación → ... → Marketplace (Fase 3, Agentes 1-6)

```bash
# 1-5. Investigar, sourcear, analizar economía, legal y generar tienda (sin cambios desde Milestone 2-6)
curl -s -X POST http://localhost:8000/api/research/runs \
  -H "Content-Type: application/json" -d '{"category": "home", "max_results": 5}'
curl -s -X POST http://localhost:8000/api/sourcing/runs \
  -H "Content-Type: application/json" \
  -d '{"product_id": "<product_id>", "category": "home", "destination_region": "mexico", "max_results": 5}'
curl -s -X POST http://localhost:8000/api/economics/runs \
  -H "Content-Type: application/json" \
  -d '{"product_id": "<product_id>", "supplier_quote_id": "<quote_id>", "sale_price": 20.0}'
curl -s -X POST http://localhost:8000/api/legal/runs \
  -H "Content-Type: application/json" \
  -d '{"product_id": "<product_id>", "market": "us", "certification_available": true}'
curl -s -X POST http://localhost:8000/api/ecommerce/runs \
  -H "Content-Type: application/json" -d '{"product_id": "<product_id>", "market": "us"}'

# 6. Generar/optimizar el listing de marketplace (Fase 3, Agente 6)
curl -s -X POST http://localhost:8000/api/marketplace/runs \
  -H "Content-Type: application/json" \
  -d '{"product_id": "<product_id>", "market": "us", "platform": "amazon"}'
# -> {"correlation_id": "...", "listing_status": "READY|NEEDS_REVIEW|BLOCKED",
#     "data": {"listing_content": {...}, "competition_analysis": {..., "data_origin":
#     "simulated_not_sp_api"}, "commission_breakdown": {"net_margin_per_unit": ...},
#     "inventory_policy": {"tracking_enabled": false, ...}, "policy": {...}}}
```

O desde el Control Center: **Research** → *Find suppliers* → **Sourcing**
→ *Analyze economics* → **Economics** → *Check legal compliance* →
**Legal** → *Generate storefront* → **Ecommerce** → *Optimize
marketplace listing* → **Marketplace** → ver el listing, análisis de
competencia (marcado como simulado), comisiones/margen neto real, y
política de inventario.

Los seis runs tienen `correlation_id` distintos, todos reconstruibles
vía `GET /api/audit?correlation_id=` — cubierto por
`backend/tests/e2e/test_marketplace_listing_to_launch_flow.py`, que
verifica tanto el camino sano (`READY`, con `data_origin` marcado) como
el camino de revisión por aprobación de categoría pendiente
(`NEEDS_REVIEW`, categoría `electronics` en el fixture de Amazon).

**Verificado manualmente en el navegador** (Control Center + backend
contra una base SQLite local de desarrollo): con `home` en mercado
`us`, todo el pipeline de 6 agentes produjo un listing `READY` con
título/bullets/keywords reales, competencia simulada marcada
`simulated_not_sp_api`, y un margen neto por unidad de `$9.66`
(precio real menos coste aterrizado real menos comisión de referencia
15% menos tarifa de fulfillment $4.00/unidad). Verificado también a
375px de ancho (mobile).

## Base de datos: tabla `marketplace_listings`

`marketplace_listings` vincula un `Product` (y, opcionalmente, un
`Storefront` del mismo mercado) a un listing generado por
mercado×plataforma. RLS activado en su propia migración
(`bcad811a07e4_add_marketplace_listings_table.py`), mismo patrón que
las tablas de los milestones anteriores.

**Verificado contra Supabase real.** `alembic upgrade head` se ejecutó
contra el proyecto `amazona` (`3e7d4898bef2 → bcad811a07e4`), y
`SELECT relrowsecurity FROM pg_class WHERE relname = 'marketplace_listings'`
confirma `true`. `get_advisors` (linter de seguridad de Supabase)
reporta **0 hallazgos** tras la migración.

## Verificar todo en local

```bash
cd backend && ruff check . && mypy app && pytest       # 334 tests
cd apps/control-center && npm run lint && npx next typegen && npx tsc --noEmit && npm test && npm run build
```
