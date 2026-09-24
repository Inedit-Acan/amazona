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
 * lleva además icono, punto y etiqueta. */
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

/** Intensidad base del anillo de cada estado. Por encima de 1 a propósito: es lo
 * que hace que el bloom lo encienda. */
export const STATUS_GLOW: Record<NodeStatus, number> = {
  running: 1.35,
  available: 0.9,
  waiting: 1.1,
  blocked: 1.2,
  error: 1.3,
  inactive: 0.32,
};

/** Radio de cada nivel de la jerarquía: el núcleo domina, el CEO le sigue. */
export const NODE_RADIUS: Record<NodeType, number> = {
  core: 1.55,
  ceo: 0.6,
  domain: 0.52,
  agent: 0.33,
};

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
