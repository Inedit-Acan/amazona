import { Boxes, Gauge, Landmark, Megaphone, Scale, Search, ShoppingCart, Truck, type LucideIcon } from "lucide-react";
import type { DomainKey } from "@/lib/demo/neural-nexus";
import type { NodeStatus, NodeType } from "@/lib/neural-nexus";

/** Paleta del grafo (especificación §3). El color nunca va solo: cada estado
 * lleva además icono y etiqueta. */
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

/** Brillo base de cada estado: «disponible» apenas brilla, «ejecutando» sí. */
export const STATUS_GLOW: Record<NodeStatus, number> = {
  running: 1.15,
  available: 0.4,
  waiting: 0.75,
  blocked: 0.95,
  error: 1,
  inactive: 0.18,
};

/** Radio de cada nivel de la jerarquía: el núcleo domina, el CEO le sigue. */
export const NODE_RADIUS: Record<NodeType, number> = {
  core: 1.35,
  ceo: 0.5,
  domain: 0.36,
  agent: 0.24,
};

/** Icono de cada dominio. Se consulta como propiedad, no a través de una
 * función: una función que devuelve un componente en pleno render hace saltar a
 * react-hooks («componente creado durante el render»). */
export const DOMAIN_ICON: Record<DomainKey, LucideIcon> = {
  "Investigación": Search,
  Abastecimiento: Truck,
  "Economía": Gauge,
  Legal: Scale,
  Finanzas: Landmark,
  Operaciones: Boxes,
  Marketing: Megaphone,
  Comercio: ShoppingCart,
};

export const EDGE_COLOR = {
  hierarchy: "#22c997",
  flow: "#15f0b2",
  dependency: "#28e5d0",
  incident: "#ef5a5a",
} as const;
