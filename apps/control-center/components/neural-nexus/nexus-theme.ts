import {
  AlertTriangle,
  BarChart3,
  Box,
  Brain,
  Calculator,
  Database,
  FileText,
  Headset,
  LineChart,
  Megaphone,
  Monitor,
  Scale,
  Search,
  Settings,
  Shield,
  ShoppingBag,
  ShoppingCart,
  TrendingUp,
  Truck,
  User,
  Users,
  type LucideIcon,
} from "lucide-react";
import type { NodeStatus, NodeType } from "@/lib/neural-nexus";

/** Paleta del grafo (especificación §3). El color nunca va solo: cada estado
 * lleva además icono, punto indicador y etiqueta. */
export const STATUS_COLOR: Record<NodeStatus, string> = {
  running: "#15f0b2",
  available: "#22c997",
  waiting: "#f3b63f",
  blocked: "#ef5a5a",
  error: "#ef5a5a",
  inactive: "#52615d",
};

/** Clase de texto equivalente, para el HUD y la vista 2D. */
export const STATUS_TEXT: Record<NodeStatus, string> = {
  running: "text-[#15f0b2]",
  available: "text-[#22c997]",
  waiting: "text-[#f3b63f]",
  blocked: "text-[#ef5a5a]",
  error: "text-[#ef5a5a]",
  inactive: "text-[#52615d]",
};

/** Emisividad del anillo de cada estado. Es la jerarquía de intensidad de la
 * corrección visual (§3.2): un nodo en reposo apenas emite y se queda por debajo
 * del umbral del bloom; solo lo cruzan los que están pasando algo. */
export const STATUS_EMISSIVE: Record<NodeStatus, number> = {
  running: 1.6,
  available: 0.22,
  waiting: 1,
  blocked: 1.25,
  error: 1.4,
  inactive: 0.06,
};

/** Opacidad del anillo principal: define el borde sin recurrir al brillo. */
export const STATUS_RING_OPACITY: Record<NodeStatus, number> = {
  running: 1,
  available: 0.72,
  waiting: 0.9,
  blocked: 0.95,
  error: 1,
  inactive: 0.34,
};

/** Los estados que merecen bloom (§7). El resto se queda mate. */
export const STATUS_BLOOMS: Record<NodeStatus, boolean> = {
  running: true,
  available: false,
  waiting: true,
  blocked: true,
  error: true,
  inactive: false,
};

/** Radio de cada nivel. Los dominios son ~25 % mayores que los agentes y el CEO
 * mayor que un dominio (§5.4): la jerarquía se lee por tamaño, no por brillo. */
export const NODE_RADIUS: Record<NodeType, number> = {
  // El núcleo ya no es un disco: su tamaño lo manda BRAIN.halfWidth
  // (lib/decision-engine.ts). Se deja aquí por completitud del registro.
  core: 1.12,
  ceo: 0.5,
  domain: 0.4,
  agent: 0.32,
};

/** Superficie oscura común a todos los nodos: es lo que los recorta contra el
 * fondo y evita la «nube verde» de discos translúcidos. */
export const NODE_SURFACE = "#05120f";

/** Iconos por la clave que trae cada nodo (`GraphNode.icon`). Se consultan como
 * propiedad, no a través de una función: una función que devuelve un componente
 * en pleno render hace saltar a react-hooks. */
export const NODE_ICON: Record<string, LucideIcon> = {
  ceo: User,
  core: Brain,
  search: Search,
  trending: TrendingUp,
  box: Box,
  truck: Truck,
  calculator: Calculator,
  alert: AlertTriangle,
  file: FileText,
  shield: Shield,
  "chart-line": LineChart,
  headset: Headset,
  users: Users,
  monitor: Monitor,
  store: ShoppingBag,
  "bar-chart": BarChart3,
  scale: Scale,
  database: Database,
  settings: Settings,
  megaphone: Megaphone,
  cart: ShoppingCart,
};

/** Paleta del Decision Engine (§18 de su especificación). El cerebro NUNCA se
 * tiñe con el estado: el color de estado se queda para el núcleo y para la zona
 * o la ruta afectada (§26). */
export const ENGINE_COLOR = {
  /** Casco de los hemisferios: casi negro con un punto de verde petróleo. */
  shell: "#04100d",
  /** Malla neural. */
  wireframe: "#00d69a",
  synapse: "#22c997",
  synapseActive: "#15f0b2",
  /** Núcleo: centro blanco frío, borde esmeralda. */
  coreCenter: "#e6fff7",
  coreEdge: "#15f0b2",
  ring: "#22c997",
};

/** Acabado del Decision Engine. Casi todo lo visual se ajusta desde aquí, sin
 * tocar los componentes. */
export const ENGINE_OPACITY = {
  /** Casco: bajo, pero nunca cero — el cerebro no puede ser transparente (§19).
   * Se dibuja ANTES que la red, así que no la apaga: le pone cuerpo debajo. */
  shell: 0.55,
  /** La línea nunca domina sobre los nodos (§6.4): a más de ~0,3 los 500
   * segmentos se funden en una masa luminosa y el cerebro deja de leerse. */
  link: 0.26,
  /** Los nodos van contenidos: si suben, los 420 se funden en una nube verde.
   * La luz del cerebro la pone la red, no la masa de puntos (§41). */
  synapse: 0.5,
  /** Halo del núcleo, mínimo y de caída corta (§10). */
  halo: 0.04,
  ring: 0.2,
  ringTick: 0.36,
  route: 0.8,
};

export const EDGE_COLOR = {
  hierarchy: "#22c997",
  flow: "#15f0b2",
  dependency: "#28e5d0",
  incident: "#ef5a5a",
} as const;

/** Opacidades de referencia de la corrección visual (§3.5). Las órbitas y las
 * conexiones son guía espacial, no protagonistas. */
export const EDGE_OPACITY = {
  ceoToCore: 0.34,
  coreToDomain: 0.24,
  domainToAgent: 0.13,
  contextual: 0.5,
  active: 0.72,
  dimmed: 0.05,
  orbit: 0.09,
  orbitAccent: 0.15,
};
