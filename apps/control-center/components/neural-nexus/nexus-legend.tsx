"use client";

import { AlertTriangle, CheckCircle2, Circle, Clock, MinusCircle, type LucideIcon } from "lucide-react";
import { STATUS_LABEL, type NodeStatus } from "@/lib/neural-nexus";
import { STATUS_COLOR } from "./nexus-theme";

/** Cada estado lleva icono además de color: la leyenda no depende de la vista
 * cromática (especificación §3 y §34). */
const LEGEND: { status: NodeStatus; icon: LucideIcon; label?: string }[] = [
  { status: "running", icon: CheckCircle2 },
  { status: "available", icon: Circle },
  { status: "waiting", icon: Clock },
  { status: "blocked", icon: AlertTriangle, label: "Bloqueado / Error" },
  { status: "inactive", icon: MinusCircle },
];

export function NexusLegend({ counts }: { counts: Record<NodeStatus, number> }) {
  return (
    <div className="pointer-events-none w-44 rounded-xl border border-white/10 bg-[#071713]/85 p-3 backdrop-blur-sm">
      <p className="mb-2 text-[11px] font-semibold tracking-wide text-foreground">Estados de agentes</p>
      <ul className="space-y-1.5">
        {LEGEND.map(({ status, icon: Icon, label }) => {
          const total = status === "blocked" ? counts.blocked + counts.error : counts[status];
          return (
            <li key={status} className="flex items-center gap-2 text-xs">
              <Icon className="size-3.5 shrink-0" style={{ color: STATUS_COLOR[status] }} />
              <span className="min-w-0 flex-1 truncate text-muted-foreground">{label ?? STATUS_LABEL[status]}</span>
              <span className="shrink-0 tabular-nums text-foreground">{total}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
