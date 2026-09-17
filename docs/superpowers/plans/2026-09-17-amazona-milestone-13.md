# AMAZONA Milestone 13 Implementation Plan

> **Para agentes que ejecuten este plan:** implementar tarea por tarea con
> TDD, commits pequeños, y revisión después de cada tarea — igual que
> Milestone 1-12.

**Tickets:** IVA-31 (Fase 4.3, "Validar casos reales de productos") +
IVA-32 (Fase 4.4, "Ajustar errores y optimizar rendimiento") — Linear,
proyecto "Fase 4 — Integración y pruebas".

**Objetivo:** correr el `PipelineOrchestrator` (Milestone 12) contra el
espacio combinatorio real de categorías/mercados/precios que el sistema
ya soporta, encontrar y corregir lo que falle o rinda mal, y dejar esa
validación como test de regresión permanente — no solo un script
desechable de investigación.

**Depende de:** Milestone 12 (`PipelineOrchestrator`, ADR 0005).

**Ninguna ADR nueva** — todo lo encontrado en la investigación previa
son correcciones a nivel de implementación (índices, un generador de
slug, una consulta N+1), no decisiones de arquitectura que afecten
contratos entre componentes.

## Investigación previa (resumen)

Se corrió el pipeline completo contra las 3 categorías × 3 mercados
soportados × varios precios × 2 regiones de destino (54 combinaciones) y
se inspeccionó el código en busca de gaps reales. Hallazgos:

1. **Bug real confirmado:** `generate_store_slug()`
   (`backend/app/ecommerce/content.py`) deriva el slug únicamente de
   `product_name`. Como `ResearchService` crea un `Product` nuevo en
   cada ejecución del pipeline, dos ejecuciones para la misma categoría
   eligen el mismo candidato top del fixture (mismo nombre) y generan
   dos `Storefront` con el mismo `store_slug` — sin ninguna restricción
   en BD que lo detecte. Reproducido empíricamente.
2. **Gap real confirmado:** ninguno de los 12 modelos tiene un índice
   explícito más allá de la PK. `product_id` en 8 tablas consultadas
   constantemente por "última fila para este producto", y
   `correlation_id` en `audit_log` (usado directamente por
   `GET /api/audit?correlation_id=`, que crece 10 filas por cada
   ejecución del pipeline), son actualmente full table scans.
3. **Gap real confirmado:** `CFOService.run_generation()` (ejecutado
   como noveno paso de **cada** ejecución del pipeline) carga
   `EconomicAnalysis`/`MarketingCampaign` completas con `.all()` y
   deduplica en Python — el coste crece linealmente con el catálogo
   histórico total, no con el producto de esta ejecución.
4. **0 excepciones no controladas, 0 estados inesperados** en las 54
   combinaciones — el pipeline en sí es correcto; no se encontró ningún
   caso donde `market`/`destination_region` desconocidos rompan algo
   (ambos caen a valores conservadores documentados, `legal_compliance`
   ya emite un riesgo explícito "insufficient regulatory data..." — no
   hace falta tocarlo).
5. **Gap de cobertura de test:** el barrido no encontró ningún precio
   que produzca `recommendation="REVIEW"` en economics (solo `GO`/
   `NO_GO`) — falta un test que ejercite específicamente esa rama.

## Decisión de alcance

- El fix de `store_slug` usa `product_id` (ya conocido por el servicio)
  como sufijo determinista — **no** se añade una restricción `UNIQUE` en
  BD, porque el propio patrón del proyecto (cada agente crea una fila
  nueva por ejecución, conservando historial) permite legítimamente
  volver a generar el storefront del mismo producto/mercado más de una
  vez; una restricción `UNIQUE` estricta rompería ese patrón. El fix
  correcto es que el slug identifique al producto real, no solo a su
  nombre — con eso, la única colisión posible es entre dos productos
  reales distintos con el mismo `product_id` truncado, estadísticamente
  despreciable con UUIDs.
- Los índices son puramente aditivos (no cambian ningún contrato de
  consulta ni comportamiento) — se añaden vía migración +
  `index=True` en los modelos para que `Base.metadata.create_all`
  (usado por todos los tests con SQLite in-memory) los reproduzca
  también.
- La optimización de `CFOService` reemplaza el `.all()` + dedup en
  Python por una consulta SQL "última fila por clave" (subquery
  `MAX(created_at)` + join) — funciona igual en SQLite (tests) y
  Postgres (Supabase). El test suite existente de CFO
  (`test_cfo_service.py`) debe seguir pasando sin cambios: es la prueba
  de que el comportamiento no cambia, solo el coste.
- No se amplía el dataset de `MockTrendsProvider`/`MockRegulatoryDirectory`
  (añadir categorías/mercados nuevos es una decisión de contenido, no
  una corrección de bug) — IVA-31 se satisface formalizando el barrido
  ya ejecutado como test de regresión permanente sobre el espacio
  combinatorio real que el sistema ya soporta, más un test dedicado a la
  rama `REVIEW` (buscada en tiempo de ejecución por precio decreciente,
  no un número mágico frágil).

## Restricciones globales (heredadas)

- Tests antes que implementación. Commit por tarea completada.
- Ningún test de Milestone 1-12 cambia de resultado, salvo los que
  aserten literalmente sobre el valor de `store_slug`/`sku` (ninguno lo
  hace hoy fuera de `test_ecommerce_content.py`, que se actualiza en la
  Tarea 1).
- Toda migración nueva es aditiva (índices, sin cambios de columna).

---

## Sección A — Corrección: `store_slug` único por producto

### Tarea 1: `generate_store_slug` incluye `product_id`

**Files:**
- Modify: `backend/app/ecommerce/content.py`
- Modify: `backend/app/agents/ecommerce_storefront.py` (input schema +
  ambos call sites: `catalog_entry["sku"]` y `data["store_slug"]`)
- Modify: `backend/app/ecommerce/service.py` (pasar `product_id` real)
- Modify: `backend/tests/unit/test_ecommerce_content.py`
- Modify: `backend/tests/unit/test_ecommerce_storefront_agent.py`
  (`_base_input` incluye `product_id`)
- Create/Modify: test de colisión en
  `backend/tests/integration/test_pipeline_orchestrator_service.py` (o
  nuevo archivo): correr el pipeline dos veces para la misma categoría,
  verificar que los dos `store_slug` son distintos.

- [ ] Test: `generate_store_slug(name, product_id)` es determinista para
      el mismo par, y distinto para el mismo nombre con `product_id`
      distinto.
- [ ] Test: dos ejecuciones del pipeline para `category="home"` generan
      dos `Storefront` con `store_slug` distinto.
- [ ] Implementar.
- [ ] Commit: `fix: derive store slug from product id to prevent cross-product collisions`

---

## Sección B — Rendimiento: índices

### Tarea 2: Índices en columnas de búsqueda frecuente

**Files:**
- Modify: `backend/app/db/models/product_analysis.py`,
  `supplier_quote.py`, `economic_analysis.py`, `legal_analysis.py`,
  `storefront.py`, `marketplace_listing.py`, `marketing_campaign.py`,
  `operations_record.py`, `pipeline_run.py` (añadir `index=True` a
  `product_id`)
- Modify: `backend/app/db/models/audit.py` (añadir `index=True` a
  `correlation_id`)
- Create: Alembic migration (`op.create_index` para cada tabla)
- Create: `backend/tests/integration/test_db_indexes.py`

- [ ] Test: cada tabla objetivo tiene un índice sobre la columna
      esperada (inspeccionar `Base.metadata.tables[...].indexes`, no
      hace falta tocar una BD real).
- [ ] Implementar; aplicar la migración a Supabase real y confirmar con
      `pg_indexes` que los 10 índices existen.
- [ ] Commit: `perf: add indexes on product_id and correlation_id lookup columns`

---

## Sección C — Rendimiento: CFO sin cargar tablas completas

### Tarea 3: `CFOService` usa una consulta "última fila por clave" en SQL

**Files:**
- Modify: `backend/app/cfo/service.py`

- [ ] Test: el test suite existente de `test_cfo_service.py` pasa sin
      modificarse (prueba de no regresión de comportamiento).
- [ ] Test nuevo: con muchos productos (p. ej. 20) y varias filas
      históricas por producto, el reporte solo cuenta la más reciente de
      cada uno (mismo test que ya existe pero a mayor escala, para
      verificar que la consulta SQL agrupa correctamente, no solo con 1-2
      filas).
- [ ] Implementar reemplazando `_latest_per_key` por dos subqueries
      `MAX(created_at)` + join (una para `EconomicAnalysis` por
      `product_id`, otra para `MarketingCampaign` por
      `(product_id, market)`). Eliminar `_latest_per_key` si queda sin uso.
- [ ] Commit: `perf: replace full-table scan with a grouped latest-row query in CFOService`

---

## Sección D — Validación: formalizar el barrido como regresión

### Tarea 4: Cobertura combinatoria real + rama REVIEW

**Files:**
- Create: `backend/tests/integration/test_pipeline_realistic_catalog_coverage.py`

- [ ] Test parametrizado: las 3 categorías × 3 mercados soportados,
      precio saludable ($50) → `COMPLETED`, sin excepción.
- [ ] Test parametrizado: las 3 categorías, precio muy bajo ($0.50) →
      economics `NO_GO` siempre.
- [ ] Test: búsqueda en tiempo de ejecución (precio decreciente desde un
      punto saludable) hasta encontrar `recommendation="REVIEW"` en
      economics — cierra el gap de cobertura de la rama `REVIEW`
      encontrado en la investigación, sin hardcodear un precio frágil.
- [ ] Test: `destination_region` desconocida completa igualmente
      (`COMPLETED`), usando el fallback conservador documentado.
- [ ] Commit: `test: formalize realistic category/market pipeline coverage`

---

## Sección E — Cierre

### Tarea 5: Doc de milestone

**Files:**
- Create: `docs/milestones/milestone-13-demo.md`

- [ ] Documentar la investigación, las 3 correcciones, la validación
      combinatoria, y el conteo final de tests + verificación de índices
      contra Supabase real.
- [ ] Commit: `docs: close milestone 13 (IVA-31 + IVA-32)`

---

## Definition of Done — Milestone 13

1. `generate_store_slug` incluye `product_id`; dos ejecuciones del
   pipeline para la misma categoría ya no colisionan.
2. 10 índices nuevos (9 `product_id` + 1 `correlation_id`) existen tanto
   en los modelos SQLAlchemy como en Supabase real, verificados.
3. `CFOService.run_generation()` ya no carga tablas completas — usa una
   consulta SQL agrupada, con el mismo comportamiento observable que antes.
4. El espacio combinatorio real (3 categorías × 3 mercados × precios
   límite) es un test de regresión permanente, incluyendo la rama
   `REVIEW` de economics.
5. `docs/milestones/milestone-13-demo.md` documenta el milestone.
6. Ningún test de Milestone 1-12 cambia de resultado salvo los
   explícitamente actualizados en la Tarea 1.
