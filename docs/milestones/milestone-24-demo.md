# Milestone 24 Demo

**Origen:** `docs/design/AMAZONA_handoff_backend_paneles_pendientes.md`
§2 — reemplaza el gráfico "Ventas/margen 30 días" que Milestone 19 dejó
explícitamente fuera del Panel general por falta de un ledger de ventas
real. **Sin ADR nueva** — endpoint de solo lectura, agregación, sin
decisión de arquitectura.

## Qué se entrega

### Backend — `GET /api/economics/analyses/timeseries?days=30`

Nuevo endpoint en `api/economics.py`: agrupa `EconomicAnalysis` por día
(`func.date(created_at)`, portable entre SQLite y PostgreSQL —
verificado con tests contra SQLite) y devuelve, por día, recuento de
análisis, margen medio y precio de venta medio. `days` acotado
(`Query(ge=1, le=365)`, default 30).

La comparación `created_at >= since` usa un `since` **naive UTC**
(`datetime.now(UTC).replace(tzinfo=None)`), no aware — mismo matiz ya
documentado en `api/approvals.py::_as_aware_utc`: SQLite pierde el
`tzinfo` al recuperar un `DateTime(timezone=True)`, así que comparar con
un límite *aware* habría sido frágil entre dialectos. Toda marca de
tiempo del esquema es UTC por convención, con o sin `tzinfo` explícito.

4 tests nuevos en `tests/integration/test_economics_api.py`: lista vacía
sin análisis, agregación correcta de 2 análisis del mismo día en un solo
bucket (recuento y promedio verificados), y el acotamiento de `days`
(422 fuera de rango).

### Frontend — "Actividad económica — últimos 30 días" en `/dashboard`

- `EconomicsTimeseriesPoint` + `api.getEconomicsTimeseries()` en
  `lib/api.ts`.
- **`EconomicsActivityChart`** (nuevo, `components/economics-activity-chart.tsx`):
  gráfico de barras construido siguiendo la skill de dataviz del
  proyecto — un solo eje, una sola serie (sin necesidad de leyenda),
  barra ≤24px con extremo redondeado de 4px anclado a la línea base,
  hueco de 2px entre barras, tooltip por barra con hit-target ampliado
  (toda la altura del gráfico, no solo el píxel pintado), y un toggle
  **"Ver tabla"** — la vista de tabla accesible que la skill exige para
  todo gráfico (nunca solo el SVG). Título honesto: "Actividad
  económica" en vez de "Ventas", con la aclaración explícita en el copy
  de que no representa ingresos ejecutados; `DataProvenanceBadge
  status="verified"` en la cabecera (son cifras reales, no una
  estimación).
- Sustituye directamente el hueco documentado en `milestone-19-demo.md`
  ("Decisión de alcance — sin gráfico Ventas/margen").

## Decisión de alcance

No se construyó un selector de rango de fechas (la skill de dataviz lo
recomienda para dashboards con filtros) — el propio ticket pide
específicamente "últimos 30 días" como valor fijo, y el endpoint ya
acepta `days` por si un panel futuro quiere exponerlo; añadir el control
de UI ahora habría sido alcance no pedido.

## Verificación

```bash
cd backend && ruff check . && mypy app && pytest       # 491 tests (+3 nuevos), sin regresiones
cd apps/control-center && npm run lint && npx next typegen && npx tsc --noEmit && npm test && npm run build
```

**Verificado visualmente** (paso 7 de la skill de dataviz: "renderízalo
y míralo"): dado que el backend real no se levantó (apunta a Supabase de
producción), se montó temporalmente una ruta de desarrollo
(`app/preview-chart/page.tsx`, **eliminada antes de cerrar el
milestone** — confirmado con `git status` que no quedó rastreada) que
importaba el componente real `EconomicsActivityChart` con datos de
muestra de forma (30 puntos, incluyendo un día en cero como caso de
borde). Capturado por screenshot: barras con geometría correcta, sin
solapamiento de etiquetas; hover confirmado (tooltip con fecha/recuento/
margen/precio, barra iluminada); toggle "Ver tabla" confirmado
(`get_page_text` mostró las 30 filas, incluida la fila en cero sin
romper el layout).

## Qué sigue

Milestone 25 — IncidentCard v1 (CRUD manual sobre el modelo `Incident`
ya existente).
