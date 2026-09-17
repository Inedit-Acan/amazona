# Nota de handoff para Claude Code — Fusión de Marketplace y Pipeline en el menú aprobado

## Contexto

El menú principal de `apps/control-center` (`components/nav-items.ts`) ya se
actualizó a las 15 entradas del "Orden final del menú principal"
(`docs/design/AMAZONA_especificacion_paneles_aprobados_parte2.md`, §2),
con las etiquetas en español aprobadas. Esa parte ya está hecha.

Dos rutas existentes quedaron **fuera del menú pero sin borrar**, porque su
contenido todavía no se ha fusionado en el panel que le corresponde:

- `/marketplace` → debe fusionarse en **Tienda y canales de venta** (`/ecommerce`).
- `/pipeline` → debe fusionarse en **Aprobaciones** (`/approvals`).

Esta nota describe esas dos fusiones. Es trabajo de código (backend +
frontend), no de diseño visual — el sistema de diseño (paleta, 2.5D, grafo
3D) es la siguiente fase y no se toca aquí.

---

## Tarea 1 — Marketplace → Tienda y canales de venta

### Qué dice la especificación aprobada

`docs/design/AMAZONA_cambio_arquitectura_eliminacion_modulo_mercado.md` es
la decisión arquitectónica: "Mercado" (que ya se había renombrado
internamente a Marketplace) deja de ser pantalla independiente. Los
marketplaces pasan a ser **canales configurables dentro de "Tienda y
canales de venta"** (ejemplo en el documento: Tienda propia, Amazon
España, Amazon Francia, Google Shopping, TikTok Shop, eBay, Miravia...),
cada uno con su propia subvista (listing, precio, comisión estimada,
margen neto, fulfillment, estado), no como módulo de menú aparte.

La especificación visual del panel (`AMAZONA_especificacion_paneles_
aprobados_v0.5.md`, §9 "Panel 7 — Tienda y canales de venta", en concreto
§9.4 "Canales" y §9.8 "Configuración por mercado") es la referencia de
cómo debe verse esa fusión una vez tenga estilo — pero la estructura de
datos/rutas puede resolverse ya, sin esperar al sistema de diseño.

### Estado actual del código

- Backend: `backend/app/ecommerce/{service.py,content.py}` y
  `backend/app/marketplace/{service.py,listing_content.py}` son dos
  servicios separados, con sus propias tablas
  (`db/models/storefront.py` vs `db/models/marketplace_listing.py`) y sus
  propias rutas (`api/ecommerce.py`, `api/marketplace.py`).
- Frontend: `app/ecommerce/page.tsx` y `app/marketplace/page.tsx` son dos
  páginas separadas, ambas ya conectadas a su API real (no son mockups).

### Qué hacer

1. **No fusionar los modelos de datos a ciegas.** Antes de tocar backend,
   comprobar si `marketplace/service.py` calcula comisión/margen por su
   cuenta o si ya delegan en `economics/service.py`. El principio rector
   del documento de arquitectura es "una única fuente de verdad
   económica": si hay cálculo de comisión duplicado fuera de Economía y
   rentabilidad, moverlo allí es parte de esta tarea, no un efecto
   secundario a ignorar.
2. **Frontend: unificar en una sola página** `app/ecommerce/page.tsx` con
   un selector/tabs de canal ("Tienda propia" + un tab por marketplace
   activo), reutilizando los datos que hoy sirve `marketplace/service.py`
   vía su misma API (no hace falta que el merge de backend esté terminado
   para mover la UI — puede seguir llamando a los dos endpoints existentes
   desde una sola pantalla mientras se decide si vale la pena fusionar los
   servicios).
3. **Eliminar `app/marketplace/page.tsx`** una vez su contenido esté
   cubierto por la nueva vista de `/ecommerce`, y actualizar cualquier
   `router.push("/marketplace...")` o enlace interno que quede (buscar con
   grep en `apps/control-center` — por ejemplo el patrón de handoff por
   query params que ya usa `ceo/page.tsx` con research/sourcing/economics/
   legal/marketing podría tener o necesitar un caso para marketplace).
4. Decidir si `api/marketplace.py` se retira o se deja como API interna
   sin página propia (otros servicios podrían seguir llamándola).

### Criterios de aceptación

- Un solo ítem de menú visible para tienda/canales; sin ruta `/marketplace`
  enlazada desde ningún sitio del Control Center.
- Ninguna comisión ni margen se calcula dos veces en dos servicios
  distintos.
- Los tests existentes de la cadena completa
  (`test_operations_to_full_chain_flow.py` y similares) siguen pasando.

---

## Tarea 2 — Pipeline → Aprobaciones

### Qué dice la especificación aprobada y las ADR

El panel **Aprobaciones** (`parte2.md` §7) es, según la "Arquitectura
final de responsabilidad" (§10), el dueño funcional de **Decisión
humana**. `docs/architecture/adr-0006-pipeline-human-controls.md`
introdujo, fuera de esa especificación de paneles (es posterior/paralela),
dos piezas nuevas:

- `PipelineReview` (`db/models/pipeline_review.py`): revisión pendiente
  cuando una ejecución del pipeline sale de riesgo (`PARTIAL`, `NO_GO`,
  `BLOCKED`, CFO en `AT_RISK`/`CRITICAL`). Se resuelve con
  `POST /api/pipeline/reviews/{id}/approve` o `/reject` — la propia ADR
  dice explícitamente que es "el mismo patrón aprobar/rechazar... que
  `api/approvals.py`".
- `PipelineKillSwitch` (`db/models/pipeline_kill_switch.py`): interruptor
  operativo único (enabled/reason/updated_by), vía
  `POST /api/pipeline/kill-switch`.

Hoy ambos viven en `app/pipeline/page.tsx`, con su propio ítem de menú
("Pipeline") que no está en los 15 aprobados.

### Qué hacer

1. **Revisiones de pipeline → dentro de Aprobaciones.** La forma más
   fiel a la especificación es que `PipelineReview` aparezca como un tipo
   más de entrada en la "Bandeja principal" de Aprobaciones (§7.4) —
   mismo componente de bandeja/priorización que ya usa `Approval`, no una
   tabla aparte. Si el modelo de datos difiere demasiado para compartir
   componente de fila sin trabajo extra, como mínimo debe vivir como
   pestaña dentro de la misma página `/approvals`, nunca como ruta de
   menú independiente.
2. **Kill switch — decisión abierta, no la resuelvo yo aquí:** es un
   control operativo, no una decisión en cola, así que no encaja del todo
   en "bandeja de aprobaciones". Dos opciones razonables:
   - (a) vive en Aprobaciones igualmente, como un control fijo en la
     cabecera de esa página (es control humano, y el dueño de "Decisión
     humana" es Aprobaciones); o
   - (b) vive en Estado (`/status`), ya que es infraestructura/operación
     del sistema, no una métrica comercial — aunque §13.1 de `parte2.md`
     dice "Estado monitoriza infraestructura; no contiene métricas
     comerciales", lo cual no descarta un control, solo métricas.
   Recomiendo (a) por coherencia con la ADR (ambas piezas se introdujeron
   juntas como "control humano sobre el pipeline"), pero es una decisión
   de producto — confirmar con Ivan antes de implementar, y dejarla
   escrita como adenda a la ADR-0006 o una ADR-0007 corta una vez decidida.
3. Eliminar `app/pipeline/page.tsx` y el ítem de menú (ya quitado de
   `nav-items.ts`) una vez su contenido esté cubierto en `/approvals`.
   Los endpoints de backend (`api/pipeline.py`) no cambian.

### Criterios de aceptación

- Ninguna ruta `/pipeline` enlazada desde el Control Center.
- Una revisión de pipeline en riesgo es visible y accionable
  (approve/reject) desde la misma pantalla donde hoy se ven las
  aprobaciones normales.
- El kill switch sigue siendo operable por un humano desde algún panel
  del Control Center — el cual, no ambos.

---

## Fuera de alcance en esta nota

El sistema de diseño visual (paleta negro/verde esmeralda, estética 2.5D,
grafo 3D real para Director ejecutivo, `DataProvenanceBadge` y los demás
componentes comunes de §15.2/§13.2 de las dos especificaciones) es la
fase siguiente y se define en un documento aparte.

## Referencias

- `docs/design/AMAZONA_especificacion_paneles_aprobados_v0.5.md`
- `docs/design/AMAZONA_especificacion_paneles_aprobados_parte2.md`
- `docs/design/AMAZONA_cambio_arquitectura_eliminacion_modulo_mercado.md`
- `docs/architecture/adr-0005-fase-3-pipeline-orchestrator.md`
- `docs/architecture/adr-0006-pipeline-human-controls.md`
- `apps/control-center/components/nav-items.ts` (ya actualizado)
