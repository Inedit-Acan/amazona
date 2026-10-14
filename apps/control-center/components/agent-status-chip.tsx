import { Activity, Ban, CircleAlert, CircleCheck, CircleHelp, CircleX, Clock, PowerOff, type LucideIcon } from "lucide-react";
import { LevelChip } from "@/components/level-chip";
import { presentActivity, type AgentActivity } from "@/lib/agent-status";
import { cn } from "@/lib/utils";

/** Icono de cada categoría: el color nunca va solo (etiqueta + icono). Es solo el dibujo; la etiqueta y el tono salen de
 * `lib/agent-status.ts`, que es la única tabla de estados de agente. */
const ACTIVITY_ICON: Record<AgentActivity, LucideIcon> = {
  available: CircleCheck,
  running: Activity,
  waiting: Clock,
  blocked: Ban,
  degraded: CircleAlert,
  disabled: PowerOff,
  failed: CircleX,
  unknown: CircleHelp,
};

/** El estado de un agente como lo dice el registro. BUSY (verde activo) se distingue de AVAILABLE (verde) por el icono y el
 * borde. `raw` (el texto del registro) solo hace falta si puede ser desconocido: se enseña en el `title`. */
export function AgentStatusChip({ activity, raw, className }: { activity: AgentActivity; raw?: string; className?: string }) {
  const presentation = presentActivity(activity);
  const Icon = ACTIVITY_ICON[activity];
  return (
    <LevelChip
      tone={presentation.tone}
      className={cn("gap-1", activity === "running" && "ring-1 ring-primary/60", className)}
    >
      <span title={raw !== undefined && activity === "unknown" ? `Estado del registro: «${raw}»` : undefined} className="inline-flex items-center gap-1">
        <Icon aria-hidden className="size-3 shrink-0" />
        {presentation.label}
      </span>
    </LevelChip>
  );
}
