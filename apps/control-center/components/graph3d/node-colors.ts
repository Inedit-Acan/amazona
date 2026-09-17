import type { NodeStatus } from "./graph-state";

/** Same 4-color vocabulary as StatusChip/DataProvenanceBadge — dimmed
 * emerald when idle/waiting, bright emerald when active, amber for a
 * blocked node, red reserved for a critical error/NO_GO output only
 * (docs/design/AMAZONA_sistema_de_diseno_visual.md §8). */
export const NODE_STATUS_COLOR: Record<NodeStatus, string> = {
  idle: "#22c997", // emerald-soft, dim
  waiting: "#9ca9a5", // text-secondary
  active: "#15f0b2", // emerald-bright
  blocked: "#f3b63f", // warning
  error: "#ef5a5a", // danger
};

export const NODE_STATUS_OPACITY: Record<NodeStatus, number> = {
  idle: 0.35,
  waiting: 0.55,
  active: 1,
  blocked: 0.9,
  error: 0.95,
};
