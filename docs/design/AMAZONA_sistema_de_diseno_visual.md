# Sistema de diseño visual — AMAZONA Control Center

## Contexto y alcance

Con el menú ya reordenado (`nav-items.ts`) y la fusión de Marketplace/
Pipeline en manos de Claude Code (ver
`AMAZONA_handoff_fusion_marketplace_y_pipeline.md`), esta nota define la
capa visual que falta sobre `apps/control-center`: hoy es un shadcn/ui
por defecto (tema claro/oscuro genérico, sin tokens propios, sin 3D) y
tiene que convertirse en lo que
`AMAZONA_especificacion_paneles_aprobados_v0.5.md` (§1) y su continuación
`..._parte2.md` (§1) describen como identidad visual aprobada. Este
documento traduce esas dos secciones (ya redactadas por separado, aquí
unificadas en una sola referencia) a decisiones de implementación
concretas: tokens, librerías, catálogo de componentes y orden de trabajo.

No repite la especificación de cada panel — para eso están los dos
documentos de especificación. Esto es la base compartida que todos los
paneles consumen.

---

## 1. Identidad visual y paleta

Fondo general teal muy oscuro, tarjetas casi del color del fondo separadas
por un borde fino (sin relleno verde saturado), acentos esmeralda/turquesa brillante, estética **2.5D premium**
(sombras suaves, capas, bordes finos, glow contenido) — empresarial y
sobrio, nunca "gaming". Alta densidad de información con jerarquía clara.
Desktop-first (1440–1920 primero), responsive después.

### Tokens (valores orientativos de la especificación — ajustables para
### calzar mejor con los mockups, pero dentro de esta dirección):

```css
--bg-0: #001214;
--bg-1: #011618;
--panel: #011a1c;
--panel-2: #04211f;
--panel-hover: #012a27;

--emerald: #00d69a;
--emerald-bright: #15f0b2;
--emerald-soft: #22c997;
--cyan-accent: #28e5d0;

--text-primary: #e8f0f3;
--text-secondary: #8fa3ad;
--border: rgba(64, 200, 190, 0.14);

--warning: #f9c45f;
--danger: #f84d60;
--success: #24d69a;
```

Valores medidos (mediana por zonas) sobre los mockups de paneles de
`docs/design/*.png` el 22-09-2026; sustituyen a los orientativos iniciales
(`--bg-0: #050808`, `--panel: #08241c`…), que daban un verde saturado que
no aparece en los mockups. La opción activa del menú lateral es
`--panel-hover` con barra izquierda y texto `--emerald-bright`, no un
relleno esmeralda.

### Mapeo sobre las variables shadcn ya presentes en `app/globals.css`

El proyecto ya usa el patrón `@theme inline` con variables shadcn
(`--background`, `--foreground`, `--card`, `--primary`, `--secondary`,
`--muted`, `--accent`, `--destructive`, `--border`, `--input`, `--ring`,
`--chart-1..5`, `--sidebar*`). No hace falta inventar un sistema de
tokens paralelo: sustituir los valores de `:root` (AMAZONA no tiene modo
claro — es un solo tema oscuro permanente, no un toggle) por esta
paleta:

| Token de la spec | Variable shadcn destino |
|---|---|
| `--bg-0` / `--bg-1` | `--background` |
| `--panel` / `--panel-2` | `--card`, `--popover` |
| `--panel-hover` | estado hover de card (no hay variable shadcn directa — añadir como token propio) |
| `--emerald` / `--emerald-bright` | `--primary`, `--ring`, `--sidebar-primary` |
| `--cyan-accent` | `--accent`, `--chart-1` |
| `--text-primary` | `--foreground`, `--card-foreground` |
| `--text-secondary` | `--muted-foreground` |
| `--border` | `--border`, `--sidebar-border` |
| `--warning` | token nuevo (shadcn no trae "warning" por defecto) |
| `--danger` | `--destructive` |
| `--success` | token nuevo, o reutilizar `--chart-2` |

Esto permite seguir usando los componentes shadcn ya instalados
(`components/ui/*`) sin reescribirlos — el cambio de identidad visual
completo se logra en gran parte solo tocando `globals.css`, y luego
ajustando spacing/radios/sombras donde el 2.5D lo pida.

---

## 2. Regla 2.5D vs. 3D

**Toda la aplicación es 2.5D.** El único componente 3D real de todo
AMAZONA es el grafo de agentes del panel **Director ejecutivo**
(`/ceo`) — ver §8. Ningún otro panel debe llevar 3D.

Librerías a añadir en `apps/control-center/package.json` (hoy no hay
ninguna de estas — el `package.json` actual solo trae shadcn/Tailwind/
lucide):

- `three` + `@react-three/fiber` + `@react-three/drei` → el grafo 3D real.
- `reactflow` → grafo 2D de respaldo/fallback (dispositivos sin buen
  soporte 3D, o modo simplificado en móvil — ver §6).

No se prescribe ninguna librería de animación 2.5D concreta (framer-
motion, etc.); es una decisión de implementación libre de Claude Code
mientras se respete "sobrio, no gaming".

---

## 3. Separación de datos (provenance)

En todo el sistema, sin excepción, debe distinguirse visualmente entre:

1. **Dato verificado**
2. **Dato proporcionado por proveedor/tercero**
3. **Estimación AMAZONA**
4. **Pendiente / no validado**

Nunca presentar una estimación como si fuera un hecho confirmado. Esto
se resuelve con un componente único y reutilizado en todas partes:

**`DataProvenanceBadge`** — un chip/badge con icono + color + tooltip que
indica cuál de los 4 estados aplica a un dato concreto (una cifra de
KPI, una fila de tabla, un campo de formulario). Un solo componente,
usado por todos los paneles — no una implementación distinta por panel.

---

## 4. Lenguaje de componentes compartido

### Shell común (todos los paneles)

- sidebar izquierda fija (ya existe como `components/shell.tsx` +
  `nav-items.ts` — adaptar visualmente, no reescribir la navegación);
- barra superior con búsqueda global;
- indicador de estado del sistema/agente;
- avatar/usuario (`session-badge.tsx` ya existe);
- breadcrumbs/contexto de producto o proyecto cuando aplique;
- acciones primarias en esmeralda, peligrosas/bloqueos en rojo.

### Catálogo de componentes comunes (unificado de v0.5 §15.2 + parte2 §13.2)

```text
AppSidebar          KpiCard             StatusChip
DataProvenanceBadge RiskBadge           AgentCard / AgentStatus
ReadinessScore      Timeline            DataTable
FilterBar           ApprovalCTA         EmptyState
SourceBadge / EvidenceBadge            ScenarioCard
RadarChart          FunnelChart         MetricSparkline
ProductContextCard  GlobalSearch        CorrelationTrace
ApprovalDetail      BudgetImpact        ServiceMap
IncidentCard        QueueStatus         VersionCard
ProjectHealth · FinancialHealth · SystemHealth · AuditHealth · OperationalHealth
AgentGraph3D (único, solo Director ejecutivo)
```

Construir cada uno una sola vez en `components/` (no por panel) y
reutilizarlo. Varios de los "*Health" son variaciones de un mismo
patrón de tarjeta de salud por dominio — vale la pena un componente
base parametrizable en vez de cinco copias.

---

## 5. Estados comunes

Todo panel debe contemplar (lista unificada de las dos especificaciones):

```text
loading · empty/sin datos · error · simulado · real · verificado ·
parcialmente verificado · pendiente · bloqueado · esperando aprobación ·
degradado · offline
```

Estos son los mismos estados que alimenta `DataProvenanceBadge` (§3) y
`StatusChip` — no crear un segundo vocabulario de estados por panel.

---

## 6. Accesibilidad y responsive

- Contraste AA mínimo; nunca depender solo del color para transmitir
  estado (icono + texto siempre acompañan al color).
- Tooltips en iconos, labels en inputs, navegación por teclado.
- Soporte de "reducir movimiento" (`prefers-reduced-motion`) — el grafo
  3D debe tener fallback 2D/2.5D (React Flow) cuando el dispositivo no
  soporta bien WebGL o el usuario pide menos movimiento.
- Responsive: desktop (1440–1920) → laptop → tablet → móvil, en ese
  orden de prioridad. En móvil: sidebar colapsable, tablas → cards,
  gráficos simplificados, grafo 3D en modo simplificado.

## 7. Seguridad UX (acciones sensibles)

Cualquier acción con impacto real (gastar dinero, lanzar campaña,
publicar producto, aprobar proveedor, cambiar precios, activar canal,
asumir stock, modificar datos legales, ejecutar pagos, cambiar permisos,
borrar/deshabilitar recursos) requiere: confirmación, verificación de
permisos, trazabilidad (event id, timestamp, actor, correlation id,
resultado) y, cuando proceda, aprobación humana explícita. Esto es un
requisito transversal, no solo de las pantallas de Aprobaciones.

---

## 8. El grafo 3D del Director ejecutivo (`/ceo`)

Único componente 3D real de la aplicación (`AgentGraph3D`, React Three
Fiber + Three.js). Debe mostrar como nodos: CEO (nodo iniciador),
Product Hunter, Market Analyst, Supplier Finder, CFO/Finanzas, Legal,
Marketing, E-commerce, y el **Decision Engine** como núcleo central, con
salidas Aprobar/Rechazar.

Comportamiento: zoom, orbit/drag moderado, click en nodo para detalle,
estado en tiempo real, conexiones luminosas, pulso cuando un agente
transmite resultado, nodo atenuado si espera, ámbar si hay bloqueo, rojo
solo para error/bloqueo crítico. Regla de oro: el usuario no debe
trabajar con JSON en el flujo normal (eso queda en "Contexto avanzado",
oculto por defecto).

La página actual `app/ceo/page.tsx` (formulario de validación de
producto) puede convivir con este grafo — es la vista de "crear
objetivo"/"resumen de misión" descrita en la spec (§4.2 de `v0.5.md`);
no se descarta su lógica, se envuelve en la nueva estructura visual y se
le añade el grafo como pieza central nueva.

---

## 9. Orden de implementación recomendado

Esto es una recomendación, no una imposición — ajustar si Claude Code ve
mejor orden dado el estado real del código:

1. **Base compartida primero**: tokens de color en `globals.css` (§1),
   `DataProvenanceBadge` y `StatusChip` (§3, §5), ajuste del shell
   (`shell.tsx`, `nav-items.ts` visual). Esto se nota en todas las
   páginas a la vez con un solo cambio.
2. **Panel general (`/dashboard`)** — es la vista ejecutiva de entrada,
   y ya tiene spec detallada (v0.5 §3) como referencia de cómo debe
   quedar un panel "terminado".
3. **Director ejecutivo (`/ceo`)** — el grafo 3D es la pieza de mayor
   riesgo técnico (librería nueva, WebGL, fallback); conviene abordarlo
   con margen en vez de dejarlo para el final.
4. Resto de paneles (Investigación → ... → Estado), reutilizando los
   componentes de §4 en cada uno.

## 10. Qué no cambia

Los mockups (`docs/design/*.png`) son referencia visual y de estructura,
**no especificación pixel-perfect** si contradicen el texto de
`v0.5.md`/`parte2.md` (así lo dice el propio documento, §16). Ante
conflicto entre imagen y texto, gana el texto.

## Referencias

- `docs/design/AMAZONA_especificacion_paneles_aprobados_v0.5.md` (§1, §15)
- `docs/design/AMAZONA_especificacion_paneles_aprobados_parte2.md` (§1, §13)
- `docs/design/AMAZONA_handoff_fusion_marketplace_y_pipeline.md`
- `apps/control-center/app/globals.css` (tema actual a sustituir)
- `apps/control-center/package.json` (librerías a añadir: three,
  @react-three/fiber, @react-three/drei, reactflow)
