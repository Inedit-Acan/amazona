# Milestone 13 Demo

**Tickets:** IVA-31 (Fase 4.3) + IVA-32 (Fase 4.4) — Linear, proyecto
"Fase 4 — Integración y pruebas".

Plan completo:
[`docs/superpowers/plans/2026-09-17-amazona-milestone-13.md`](../superpowers/plans/2026-09-17-amazona-milestone-13.md).
**Sin ADR nueva** — todo lo corregido es implementación (índices, un
generador de slug, una consulta), no un cambio de arquitectura entre
componentes.

## Investigación previa (resumen)

Se corrió el `PipelineOrchestrator` (Milestone 12) contra las 3
categorías × 3 mercados soportados × varios precios × 2 regiones de
destino (54 combinaciones) y se inspeccionó el código en busca de gaps
reales. Resultado: **0 excepciones no controladas, 0 estados
inesperados** — el pipeline en sí ya era correcto. Se encontraron 3 gaps
reales de implementación (no de diseño) y 1 gap de cobertura de test:

1. `generate_store_slug()` derivaba el slug solo de `product_name`.
   Como cada ejecución del pipeline crea un `Product` nuevo, dos
   ejecuciones para la misma categoría eligen el mismo candidato top del
   fixture (mismo nombre) y generaban dos `Storefront` con el mismo
   `store_slug`, sin ninguna restricción en BD que lo detectara.
2. Ninguno de los 12 modelos tenía un índice explícito más allá de la
   PK — cada "última fila para este producto" (patrón usado en los 8
   servicios de Fase 3) y `GET /api/audit?correlation_id=` (que crece 10
   filas por cada ejecución del pipeline) eran full table scans.
3. `CFOService.run_generation()` — ejecutado como noveno paso de **cada**
   ejecución del pipeline — cargaba `EconomicAnalysis`/`MarketingCampaign`
   completas con `.all()` y deduplicaba en Python; el coste crecía con
   el catálogo histórico total, no con el producto de esta ejecución.
4. El barrido no encontró ningún precio que produjera
   `recommendation="REVIEW"` en economics (solo `GO`/`NO_GO`) — gap de
   cobertura de test, no un bug.

## Correcciones

- **`store_slug` único por producto:** `generate_store_slug` ahora
  incluye `product_id` (primeros 8 caracteres como sufijo determinista).
  Se decidió **no** añadir una restricción `UNIQUE` en BD: el propio
  patrón del proyecto (cada agente crea una fila nueva por ejecución,
  conservando historial) permite legítimamente regenerar el storefront
  del mismo producto/mercado más de una vez, y una restricción estricta
  rompería ese patrón. El fix correcto es que el slug identifique al
  producto real, no solo su nombre.
- **10 índices nuevos** (`product_id` en las 8 tablas de Fase 3 más
  `pipeline_runs`, `correlation_id` en `audit_log`) — puramente
  aditivos, sin cambio de comportamiento observable.
- **`CFOService` sin cargar tablas completas:** reemplazadas las dos
  consultas `.all()` + dedup en Python por dos consultas SQL "última
  fila por clave" (subquery `MAX(created_at)` agrupada + join) — mismo
  resultado, coste ligado al número de productos/campañas distintos, no
  al historial total. El suite de tests existente de CFO
  (`test_cfo_service.py`, 8 tests previos) pasa sin modificarse, más un
  test nuevo a mayor escala (20 productos, 2 mercados cada uno) que
  confirma el `GROUP BY` agrupa correctamente.

## Validación formalizada como regresión permanente

`backend/tests/integration/test_pipeline_realistic_catalog_coverage.py`
(nuevo): las 3 categorías × 3 mercados soportados completan sin error;
un precio muy bajo siempre produce `NO_GO` en economics sin detener la
cadena (ADR 0005); una búsqueda en tiempo de ejecución (precio
decreciente) encuentra la rama `REVIEW` de economics, cerrando el gap de
cobertura sin hardcodear un número frágil; una región de destino y un
mercado desconocidos completan igualmente con los fallbacks
conservadores ya documentados.

## Verificado manualmente

Corriendo el backend real contra una base SQLite local: dos ejecuciones
consecutivas del pipeline para `category=electronics` produjeron
storefronts con slugs `smart-water-bottle-a0adb8e2-store` y
`smart-water-bottle-aa766510-store` — mismo nombre de producto, slugs
distintos.

**Verificado contra Supabase real.** La migración de índices se aplicó
contra el proyecto `amazona` (`81219be53fb3 → 075bc06fedad`), y
`SELECT indexname, tablename FROM pg_indexes WHERE indexname LIKE 'ix_%'`
confirma los 10 índices nuevos presentes. `get_advisors` (linter de
seguridad de Supabase) reporta **0 hallazgos** tras la migración.

## Verificar todo en local

```bash
cd backend && ruff check . && mypy app && pytest       # 465 tests
cd apps/control-center && npm run lint && npx next typegen && npx tsc --noEmit && npm test && npm run build
```

## Qué queda para el resto de Fase 4

- **IVA-33 (Milestone 14):** controles humanos críticos sobre el
  pipeline ya automatizado y validado.
- **IVA-34 (Milestone 15):** documentación completa del sistema, cierre
  de Fase 4.
