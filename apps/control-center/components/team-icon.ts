import { Bot, Gauge, Landmark, Megaphone, Scale, Search, ShoppingCart, Truck, type LucideIcon } from "lucide-react";
import type { Team } from "@/lib/agents";

/** Icono de cada equipo de agentes: el mismo en Agentes y en el Panel, para que
 * un agente se reconozca igual en las dos pantallas. */
export const TEAM_ICON: Record<Team, LucideIcon> = {
  Investigación: Search,
  Abastecimiento: Truck,
  Economía: Gauge,
  Legal: Scale,
  Comercio: ShoppingCart,
  Marketing: Megaphone,
  Operaciones: Truck,
  Finanzas: Landmark,
  Otros: Bot,
};
