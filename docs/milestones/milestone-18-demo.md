# Milestone 18 Demo

**Origen:** `docs/design/AMAZONA_sistema_de_diseno_visual.md`, primer paso
de la Fase 2 (sistema de diseño visual) — "base compartida primero: tokens
de color, `DataProvenanceBadge` y `StatusChip`, ajuste del shell" (§9.1).
**Sin ADR nueva** — es implementación de una identidad visual ya
aprobada, no una decisión de arquitectura.

## Qué se entrega

### Paleta (`apps/control-center/app/globals.css`)

AMAZONA no tiene modo claro (confirmado: ningún `.dark`/toggle de tema
existe en el código — grep sin resultados de `next-themes`/
`ThemeProvider`/clase `dark`). El bloque `.dark` quedaba muerto; se
elimina y la paleta negro/esmeralda pasa directamente a `:root`, con la
misma estructura de dos capas que usa el propio documento de diseño:
tokens crudos (`--bg-0`, `--panel`, `--emerald`, …) + mapeo a variables
semánticas shadcn (`--background`, `--card`, `--primary`, …) según la
tabla de la spec §1. Tokens sin variable shadcn directa
(`--panel-hover`, `--warning`, `--success`) se exponen también como
utilidades Tailwind (`bg-panel-hover`, `text-warning`, …) vía
`@theme inline`.

Verificado en el navegador embebido: `background` computado
`rgb(5, 8, 8)` (`#050808`), `card` `rgb(8, 36, 28)` (`#08241c`) — la
paleta se aplica correctamente sin tocar ninguna página individual,
porque ya usaban las variables semánticas de shadcn.

### `DataProvenanceBadge` (nuevo)

`components/data-provenance-badge.tsx` — chip + icono + tooltip para los
4 estados de procedencia de dato (§3 del doc de diseño): verificado
(`ShieldCheck`, emerald), proveedor/tercero (`Building2`, cyan-accent),
estimación AMAZONA (`Sparkles`, warning), pendiente (`Clock`, muted).
Necesitó un componente `Tooltip` nuevo (`components/ui/tooltip.tsx`,
mismo patrón `@base-ui/react` que ya usa `tabs.tsx` — no existía ninguna
primitiva de tooltip en el proyecto). Primer uso real: el bloque
"Competition analysis" de la pestaña Amazon en `/ecommerce`, que antes
mostraba `data_origin` como texto plano.

### `StatusChip` (consolidado, no duplicado)

`components/status-badge.tsx` ya cubría la mayoría del rol que pide la
spec para `StatusChip` — se **renombró** (`components/status-chip.tsx`,
export `StatusChip`) y se actualizaron los 7 sitios que lo consumían
(`approval-card.tsx`, `pipeline-review-card.tsx`, y las páginas
`status`, `dashboard`, `projects`, `projects/[id]`, `agents`) en vez de
crear un componente paralelo. De paso se resolvió la duplicación dejada
pendiente en Milestone 16: `LAUNCH_STATUS_STYLES`/`LISTING_STATUS_STYLES`
(idénticos, definidos dos veces en `ecommerce/page.tsx`) se eliminaron a
favor de `<StatusChip status={...} />`, que ya cubre esos mismos 3
estados (`READY`/`NEEDS_REVIEW`/`BLOCKED` añadidos al vocabulario común).

### Shell (`components/shell.tsx`)

Ajuste puramente visual, sin tocar la navegación: glow contenido en el
enlace activo (`shadow-[0_0_14px_-3px_var(--emerald)]`, verificado
computado como `rgb(0, 214, 154) 0px 0px 14px -3px`), hover usa
`bg-panel-hover` (el token dedicado a ese estado, en vez de `bg-muted`
genérico) y el logo lleva un glow sutil a juego. La estructura de
sidebar fija + drawer móvil no cambia.

### Dependencias nuevas

`three`, `@react-three/fiber`, `@react-three/drei`, `reactflow`
instaladas en `apps/control-center/package.json` — se usan recién en
Milestone 20 (`AgentGraph3D`), instaladas aquí para no mezclar "añadir
dependencia" con "primer uso" en el mismo commit.

## Verificación

```bash
cd apps/control-center && npm run lint && npx next typegen && npx tsc --noEmit && npm test && npm run build
```

No se tocó nada de `backend/` en este milestone.

Verificado en el navegador embebido contra el dev server real
(`preview_start`): paleta aplicada (background/card computados
confirmados por JS), glow del ítem de menú activo confirmado por
`getComputedStyle`, sin errores de consola propios de la aplicación
(solo `ERR_CONNECTION_REFUSED` esperado — el backend no se levantó
contra la base Supabase real).

## Qué sigue

Milestone 19 — Panel general (`/dashboard`), reutilizando
`DataProvenanceBadge`/`StatusChip` y construyendo `KpiCard` por primera
vez.
