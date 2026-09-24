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
  core: 1.45,
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
