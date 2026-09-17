# Milestone 21 Demo

**Origen:** `docs/design/AMAZONA_sistema_de_diseno_visual.md` §9.4 —
"resto de paneles, reutilizando los componentes de §4 en cada uno".
Primer milestone del "resto de paneles" (Investigación, Proveedores,
Economía, Legal, Marketing, Operaciones, Finanzas y control), agrupados
aquí porque comparten exactamente el mismo patrón de código (formulario
→ ejecutar agente → card de resultado con un mapa de color de estado
duplicado). **Sin ADR nueva.**

## Investigación previa

Survey de las 8 páginas restantes de Fase 3 (`research`, `sourcing`,
`economics`, `legal`, `marketing`, `operations`, `cfo`) más `agents`,
`status`, `projects`, `projects/[id]`, `audit`. Resultado: estas últimas
5 **ya estaban limpias** — usan `StatusChip` desde su creación, sin
mapas de color duplicados; no se tocaron. Las 5 primeras (economics,
legal, marketing, operations, cfo) repetían el mismo problema que ya se
resolvió una vez en Milestone 18 para `ecommerce`: un `Record<string,
string>` de clases de color por estado, redefinido de forma casi
idéntica en cada archivo, en vez de `StatusChip`. `research` y
`sourcing` no muestran un chip de estado único (listan candidatos, no
tienen un solo resultado con status) — no había nada que consolidar
ahí.

## Qué se entrega

- **`StatusChip`** (`components/status-chip.tsx`) gana 3 estados que
  faltaban en su vocabulario: `HEALTHY`, `AT_RISK`, `CRITICAL` (salud
  financiera del CFO — antes solo cubiertos por el mapa local de
  `cfo/page.tsx`).
- **`RiskList`** (nuevo, `components/risk-list.tsx`): el bloque "Risks"
  (título + lista roja) aparecía copiado y pegado, carácter por
  carácter, en 6 archivos (`ecommerce`, `economics`, `legal`,
  `marketing`, `operations`, `cfo`). Un componente de 10 líneas lo
  reemplaza en los 6 sitios.
- `economics/page.tsx`, `legal/page.tsx`, `marketing/page.tsx`,
  `operations/page.tsx`, `cfo/page.tsx`: los mapas de color locales
  (`RECOMMENDATION_STYLES`, `CAMPAIGN_STATUS_STYLES`,
  `OPERATIONS_STATUS_STYLES`, `HEALTH_STATUS_STYLES`) se eliminan a
  favor de `<StatusChip status={...} />` — incluye el listado "Recent
  reports" de `cfo/page.tsx`, que también coloreaba cada fila a mano.
- `marketing/page.tsx`: el bloque "Performance estimate" mostraba
  `data_origin` como texto plano (mismo patrón que ya se corrigió en
  `ecommerce` en Milestone 18) — ahora usa `<DataProvenanceBadge
  status="estimated" tooltip={data_origin} />`.

## Decisión de alcance

No se construyeron los componentes/paneles que la especificación pide
pero que requerirían datos que el backend no expone hoy (radar de
oportunidades con eje "Futuro"/"Regulación"/"Escalabilidad", mapa global
de proveedores, funnel de conversión real, Workflow Builder visual,
CFO Copilot conversacional, Service Map, etc.). Igual que en Milestone 19
(`dashboard`), construir esas piezas exigiría backend nuevo o datos
fabricados — ninguna de las dos cosas es "aplicar el sistema de diseño
visual". Este milestone se limita a lo que sí tiene datos reales
detrás: consolidar estado/riesgo/procedencia en los componentes
compartidos ya construidos.

No se tradujo el copy de estas páginas al español — a diferencia de
`dashboard`/`ceo` (paneles con especificación detallada en español en
v0.5 §3-4), el resto de paneles no tiene esa especificación línea por
línea, y traducir todo el copy técnico existente es un cambio de alcance
distinto (localización) al de este milestone.

## Verificación

```bash
cd apps/control-center && npm run lint && npx next typegen && npx tsc --noEmit && npm test && npm run build
```

No se tocó `backend/`. Verificado en el navegador embebido: `/cfo`
renderiza sin errores de consola propios de la aplicación.

## Qué sigue

Quedan por tratar visualmente: `research`, `sourcing` (ya heredan la
paleta, sin más cambios pendientes identificados), y construir los
componentes de mayor especificidad que sí tienen datos reales
disponibles — `AgentCard` dedicado para `/agents` (hoy usa markup
inline con `Card`+`Badge`), `ProjectHealth` para `/projects`,
`CorrelationTrace`/`EvidenceBadge` para `/audit`, `ServiceMap`/
`QueueStatus`/`IncidentCard` para `/status`. Se abordará en un milestone
siguiente si Ivan confirma que vale la pena la inversión adicional dado
que estas páginas ya son funcionales y coherentes con la paleta.
