# Milestone 16 Demo

**Origen:** `docs/design/AMAZONA_handoff_fusion_marketplace_y_pipeline.md`,
Tarea 1 — no es un ticket de Linear, es la primera de las dos fusiones de
contenido pedidas antes de aplicar el sistema de diseño visual. **Sin ADR
nueva** — es la ejecución de una decisión de arquitectura ya aprobada en
`docs/design/AMAZONA_cambio_arquitectura_eliminacion_modulo_mercado.md`,
no una decisión nueva.

## Qué se entrega

Fusión de `/marketplace` dentro de `/ecommerce` ("Tienda y canales de
venta") como canal, sin perder ninguna capacidad ni tocar los modelos de
datos (`storefront.py`/`marketplace_listing.py` se quedan como estaban —
el handoff no pedía fusionar tablas).

### Backend — una única fuente de verdad económica

Investigación previa (handoff, Tarea 1.1) encontró que
`marketplace/service.py` **no delegaba** en `economics/service.py` para
el costo unitario: derivaba `unit_landed_cost` invirtiendo
algebraicamente `EconomicAnalysis.margin_percent`
(`sale_price * (1 - margin_percent)`, ya persistido y redondeado) en vez
de leer `SupplierQuote.total_landed_cost_per_unit` — el mismo dato real
que ya usa `economics/service.py:55`. Dos caminos distintos al mismo
número.

- `backend/app/marketplace/service.py`: ahora resuelve `SupplierQuote`
  vía `economic_analysis.supplier_quote_id` (FK no nula) y usa
  `quote.total_landed_cost_per_unit` directamente.
- `backend/app/economics/channel_commission.py` (nuevo):
  `compute_channel_net_margin()` — la aritmética de comisión de canal
  (referral fee + fulfillment fee → margen neto), antes inlineada en
  `agents/marketplace_listing.py:66-74`, ahora vive en el dominio
  Economía y rentabilidad, que es quien la especificación
  (`AMAZONA_cambio_arquitectura_eliminacion_modulo_mercado.md`, tabla de
  redistribución) asigna como dueño de "comisiones del marketplace,
  costes del canal y margen neto". `agents/marketplace_listing.py` la
  importa; misma fórmula, mismo comportamiento.
- `api/marketplace.py` **no se retira** (handoff Tarea 1.4): el
  `PipelineOrchestrator` lo invoca en proceso y el frontend fusionado
  sigue llamando `POST /api/marketplace/runs` desde la pestaña Amazon —
  queda como API interna sin página propia.

### Frontend — un solo panel con pestañas de canal

`apps/control-center/app/ecommerce/page.tsx` gana un selector de canal
(`Tienda propia` / `Amazon`, componente `Tabs` ya instalado) que
comparte `productId`/`market` entre pestañas. El botón "Optimize
marketplace listing" cambia de pestaña in-place en vez de navegar; el
botón "Plan marketing campaign" de la pestaña Amazon sigue navegando a
`/marketing` (ese panel no se fusiona). `app/marketplace/page.tsx` se
elimina.

## Verificación

```bash
cd backend && ruff check . && mypy app && pytest       # 488 tests, sin regresiones
cd apps/control-center && npm run lint && npx next typegen && npx tsc --noEmit && npm test && npm run build
```

Verificado además en el navegador embebido contra el dev server real
(`preview_start`): la pestaña "Amazon" renderiza el formulario de
listing correcto al cambiar, la barra lateral ya no muestra ningún
enlace a `/marketplace`, y no hay errores en consola ni en el servidor.

`grep -rn "/marketplace"` en `apps/control-center` solo encuentra las
llamadas legítimas a `/api/marketplace/runs` (backend, se mantiene) y el
comentario histórico en `nav-items.ts` — ningún `router.push`/`Link`
colgante hacia la ruta eliminada.

## Qué queda para la Fase 1

- Tipos duplicados `Storefront`/`MarketplaceListing` (`lib/api.ts`) y
  estilos `LAUNCH_STATUS_STYLES`/`LISTING_STATUS_STYLES` (idénticos,
  definidos dos veces) — deliberadamente no tocados aquí; se resuelven
  en Milestone 18 (`StatusChip` compartido), para no mezclar la fusión
  funcional con el trabajo de componentes del sistema de diseño.
- **Milestone 17:** fusión de `/pipeline` dentro de `/approvals`
  (Tarea 2 del mismo handoff).
