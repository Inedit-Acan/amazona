# Nota de handoff — Backend para lo que quedó deliberadamente fuera (Milestones 19–22)

## Contexto

Milestones 19, 21 y 22 dejaron fuera, de forma explícita y documentada,
piezas de la especificación de paneles que exigían datos que el backend
no expone hoy: el gráfico "Ventas/margen 30 días" (Panel general), el
radar de oportunidades (Investigación), y `IncidentCard`/`QueueStatus`/
`VersionCard` (catálogo compartido). En cada caso, la razón registrada
fue la misma: construirlo sin backend real habría significado fabricar
datos, que es justo lo que el sistema de diseño prohíbe (§3 de
`AMAZONA_sistema_de_diseno_visual.md`).

Investigué el estado real de cada pieza en el backend (`backend/app/`)
para separar lo que es un arreglo pequeño de lo que exige diseño de
datos nuevo, y lo que directamente no tiene ninguna base real hoy y no
debería construirse todavía. Resultado: **4 piezas construibles, 1 que
recomiendo no construir por ahora.**

---

## 1. VersionCard — arreglo pequeño, no diseño nuevo

`db/models/agent.py::Agent` ya tiene `version`, `cost_profile`,
`latency_profile`. El registro en memoria (`agents/registry.py`) también
asigna `version="1.0.0"` a cada agente al arrancar
(`build_default_agent_manager`). El problema es únicamente que
`api/agents.py::AgentOut` (el modelo Pydantic de respuesta) no serializa
esos campos — los tiene disponibles y los descarta.

**Tarea:** añadir `version` (y opcionalmente `cost_profile`) a `AgentOut`
y al list comprehension de `list_agents()`. Sin migración, sin tabla
nueva. `VersionCard` en `/agents` pasa a mostrarlo con
`provenance="verified"` (es literalmente el valor que ya asigna el
registro, no una estimación).

## 2. "Actividad económica — últimos 30 días" (no "Ventas") — Panel general

No existe ningún ledger de ventas ni pedidos recurrentes — AMAZONA sigue
en Fase 3 (validación/discovery), ningún paso cobra dinero de verdad
(confirmado en ADR-0006). Fabricar una serie de "ventas" sería inventar
datos. Pero **sí existe** una serie temporal real y con marca de tiempo
genuina: cada `EconomicAnalysis` (`db/models/economic_analysis.py`) tiene
`created_at`, `sale_price` y `margin_percent` reales, uno por cada
análisis económico ejecutado.

**Tarea:** nuevo endpoint de solo lectura,
`GET /api/economics/analyses/timeseries?days=30`, que agrupa
`EconomicAnalysis` por día y devuelve recuento de análisis, margen medio
y precio de venta medio de ese día. En el frontend, el gráfico se llama
**"Actividad económica"**, no "Ventas/margen" — es honesto sobre qué mide
(decisiones analizadas, no ingresos reales), con
`DataProvenanceBadge status="verified"` sobre las cifras (son reales),
pero dejando claro en el copy que no representa ventas ejecutadas.

**Explícitamente fuera:** un ledger de ventas real requiere un canal de
venta conectado de verdad (Amazon SP-API u otro) generando pedidos reales
— eso no existe todavía en la arquitectura. No construir un simulador de
pedidos solo para rellenar este gráfico.

## 3. Radar de oportunidades — Investigación

Hoy `ProductResearchAgent` (`agents/product_research.py`) y su fuente
`MockTrendsProvider` (`ai/mock_trends_provider.py`) solo calculan 2 ejes
reales: `demand_signal` y `competition_level` → `opportunity_score`. La
especificación pide un radar de 5 ejes (`v0.5.md` §5.4), incluyendo
"Futuro", "Regulación" y "Escalabilidad", que **no existen en ningún
sitio del sistema hoy** — ni como dato real ni como dato simulado.

**Tarea:** extender `MockTrendsProvider` con 3 dimensiones nuevas por
candidato (`future_outlook_signal`, `regulatory_risk_signal`,
`scalability_signal`), mismo patrón que ya usan `demand_signal`/
`competition_level` — valores fijos por fixture, deterministas, cero
llamada externa real. Esto **no es fabricar datos**: es el mismo patrón
ya aprobado y en producción para los otros dos ejes, simplemente
extendido. La diferencia con "inventar" es que quedan explícitamente
etiquetados como simulados (`DataProvenanceBadge status="simulated"`) en
el radar, igual que ya se hace con `demand_signal` en el resto de la
aplicación — nunca se presentan como hecho verificado.

`ProductResearchAgent.run()` pasa a incluir los 5 ejes en cada
`candidate`, y `ProductAnalysis.data` los persiste igual que hoy persiste
`demand_signal`/`competition_level`. El frontend consume
`RadarChart`/`components/radar-chart.tsx` (catálogo ya previsto en
parte2.md §13.2, sin construir aún) sobre ese `data`.

**Alternativa más barata**, si prefieres no tocar el agente todavía:
radar de 2 ejes (Demanda, Competencia) con los datos que ya existen,
dejando "Futuro/Regulación/Escalabilidad" para cuando haya una fuente
real o simulada que los sostenga. Lo dejo como tu decisión, no la tomo
por ti — dímelo cuando le pases esto a Claude Code.

## 4. IncidentCard — v1 manual, no automático

`db/models/incident.py::Incident` ya existe (title, description,
severity, status, resolved_at) pero, igual que `Policy` en su día
(ADR-0006), es un scaffold sin ningún camino de lectura/escritura — cero
API, cero código que cree una fila.

**Tarea v1 (recomendada para este milestone):** `api/incidents.py` con
`POST /api/incidents` (crear, campos: title/description/severity),
`POST /api/incidents/{id}/resolve`, `GET /api/incidents`. Es un registro
manual — un operador reporta y resuelve incidentes desde `/status`. Esto
es dato real (lo escribe una persona), no fabricado.

**Fuera de alcance de esta tarea:** creación automática de incidentes a
partir de señales del sistema (p. ej., backend caído más de N minutos
según `ServiceMap`, o una `PipelineReview` sin resolver demasiado
tiempo). Es una idea razonable, pero es un diseño de "cuándo se
considera esto un incidente" que merece su propia decisión, no colarlo
como efecto secundario de construir el CRUD básico.

## 5. QueueStatus — no construir todavía

`events/bus.py::InProcessEventBus` es pub/sub síncrono, en memoria, sin
cola real (sin backlog, sin profundidad, sin workers). No hay Celery,
Redis ni ningún sistema de tareas asíncronas en todo el backend.
Construir un `QueueStatus` hoy significaría o bien inventar métricas de
una cola que no existe, o bien introducir infraestructura de colas real
únicamente para alimentar un widget — ninguna de las dos cosas está
justificada por una necesidad real del sistema todavía.

**Recomendación:** no construir esta pieza en este milestone. Si en el
futuro se introduce una cola de tareas real por una razón funcional
(por ejemplo, mover `PipelineOrchestrator.run_pipeline()` fuera del hilo
de request), `QueueStatus` se construye entonces sobre esa
infraestructura real — eso sí sería una ADR nueva, no una nota de
handoff.

---

## Orden sugerido

1. VersionCard (trivial, sin riesgo).
2. Actividad económica 30 días (endpoint nuevo, sin tocar agentes).
3. IncidentCard v1 (CRUD nuevo, modelo ya existente).
4. Radar de oportunidades (toca el agente de investigación — más
   invasivo, dejar para el final).
5. QueueStatus: no incluir.

## Referencias

- `docs/milestones/milestone-19-demo.md`, `-21-demo.md`, `-22-demo.md`
  (decisiones de alcance originales que esta nota resuelve)
- `docs/design/AMAZONA_especificacion_paneles_aprobados_v0.5.md` (§3.2 KPIs, §5.4 radar)
- `docs/design/AMAZONA_especificacion_paneles_aprobados_parte2.md` (§13.2 catálogo, §9 Estado)
- `docs/architecture/adr-0006-pipeline-human-controls.md` (precedente sobre no resucitar scaffolds a ciegas — mismo razonamiento aplicado aquí a `Incident`)
