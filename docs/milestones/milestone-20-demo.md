# Milestone 20 Demo

**Origen:** `docs/design/AMAZONA_sistema_de_diseno_visual.md` §8-9.3 —
"Director ejecutivo, el de mayor riesgo técnico de la Fase 2 (librería
nueva, WebGL, fallback); conviene abordarlo con margen". Especificación
funcional: `AMAZONA_especificacion_paneles_aprobados_v0.5.md` §4.
**Sin ADR nueva.**

## Qué se entrega

### `AgentGraph3D` — el único componente 3D real de toda la aplicación

`components/graph3d/` (nuevo):

- **`graph-state.ts`** — única fuente de verdad de la estructura del
  grafo (11 nodos: CEO, 7 agentes conceptuales, Decision Engine,
  Aprobar/Rechazar; consumida tanto por la escena 3D como por el
  fallback 2D, sin duplicar la topología). El estado de cada nodo se
  deriva de datos reales, no simulados: `deriveGraphState(decision)`
  lee `Decision.evidence` (mismo patrón que ya usa `approval-card.tsx`
  vía `finance_validation`/`legal_validation`) — **hallazgo importante
  de la investigación previa**: `backend/app/ceo/orchestrator.py`
  (`SPECIALIST_TASK_NAMES`) solo produce evidencia para 4 de los 7
  agentes conceptuales de la spec (Product Hunter, Supplier Finder,
  CFO/Finanzas, Legal) — Market Analyst, Marketing y E-commerce
  pertenecen al `PipelineOrchestrator` de Fase 3, una capa de
  orquestación deliberadamente separada (ADR 0001, ADR 0005). Esos 3
  nodos se mantienen en el grafo (la spec pide el roster conceptual
  completo) pero permanentemente `idle` en esta página — nunca se
  simulan como activos.
- **`scene3d.tsx`** — React Three Fiber + drei: nodos como esferas con
  `meshStandardMaterial` emissive (color/intensidad por estado, pulso
  animado vía `useFrame` en nodos activos), aristas con `Line`
  (glow/opacidad según si está "encendida"), etiquetas vía `Html` de
  drei (DOM real, no textura de fuente — evita depender de una fuente
  cargada por CDN), `OrbitControls` con zoom/drag moderado
  (`minDistance`/`maxDistance`/`maxPolarAngle`, sin pan). Click en un
  nodo actualiza el panel de detalle (nombre, rol, `StatusChip`).
- **`agent-graph-2d-fallback.tsx`** — mismo modelo de nodos/aristas
  renderizado con `reactflow` (layout fijo por columnas/filas, sin
  animación), mismo mapeo de color por estado (`node-colors.ts`,
  compartido entre las dos implementaciones).
- **`use-graph-fallback.ts`** — decide 3D vs. 2D: sin soporte WebGL, o
  `prefers-reduced-motion: reduce` (§6 del doc de diseño). Usa
  `useSyncExternalStore` (no `useState`+`useEffect`) porque es el patrón
  correcto de React para leer una capacidad del entorno que no cambia
  tras el montaje — evita el lint de "setState síncrono en efecto".

### `app/ceo/page.tsx` — envuelto, no reescrito

Conservando exactamente la lógica de envío existente (Milestone 1):

- El grafo se monta como pieza central nueva, encima del formulario.
- El contexto JSON (`textarea` de configuración fixture) pasa a vivir
  detrás de un desplegable **"Contexto avanzado"**, colapsado por
  defecto — la "regla principal" del panel (v0.5 §4.3: "el usuario no
  debería trabajar directamente con JSON en el flujo normal").
- **Cambio de comportamiento necesario, no opcional:** el código
  original navegaba a `/projects/{id}` inmediatamente tras `runObjective`
  — el grafo nunca habría tenido datos que mostrar. Ahora la página se
  queda tras ejecutar, muestra "Resumen de misión" (estado, confianza,
  score, `runResult.rationale` — todos campos reales de `RunResult`,
  ninguno inventado) y un botón explícito "Ver proyecto" en vez de
  redirigir sin preguntar.
- **"Vista previa de ejecución" con datos reales**, no fabricados:
  tras el run se llama también `api.getDecision(result.id)` (mismo id,
  confirmado en `backend/app/api/objectives.py`) para obtener
  `evidence`, y `api.listAgentExecutions()` filtrado por
  `correlation_id === result.correlation_id` (mismo correlation_id
  compartido entre `Decision` y `AgentExecutionLog`, confirmado en
  `orchestrator.py`) — dos endpoints ya existentes que ningún panel
  consumía hasta ahora.

## Verificación

```bash
cd apps/control-center && npm run lint && npx next typegen && npx tsc --noEmit && npm test && npm run build
```

**Verificado en vivo en el navegador embebido** (el paso de mayor riesgo
de todo el milestone):

- El canvas 3D renderiza los 11 nodos y las conexiones correctamente
  (capturado por screenshot).
- Drag sobre el canvas rota la cámara (`OrbitControls` funcional,
  confirmado comparando dos screenshots antes/después del drag).
- Click en el nodo CEO abre el panel de detalle con su rol real y
  `StatusChip` "PENDING" (estado `idle` correctamente mapeado, sin
  ejecución todavía).
- Sin errores de consola propios de la aplicación (solo
  `ERR_CONNECTION_REFUSED` esperado — no se levantó el backend real
  contra Supabase).
- El fallback 2D no se verificó en vivo (este navegador soporta WebGL,
  así que nunca se activó) — se apoya en `tsc`/`build` en verde y en
  que comparte el mismo modelo de datos ya probado del 3D.

## Qué sigue

Con la base compartida, el panel general y el panel de mayor riesgo
técnico completos, el resto de paneles (Milestone 21 en adelante) siguen
el patrón descrito en el plan de esta fase: aplicar la paleta ya
heredada, sustituir markup ad-hoc por los componentes compartidos, y
construir los componentes específicos de cada panel que aún falten.
