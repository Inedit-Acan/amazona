"use client";

import { CircleCheck, CircleX, LoaderCircle, TriangleAlert, type LucideIcon } from "lucide-react";
import { useBackendHealth } from "@/components/use-backend-health";
import { HEALTH_SCOPE_NOTE, healthLabel, type HealthVerdict } from "@/lib/backend-health";
import { cn } from "@/lib/utils";

/** Icono, color y punto de cada veredicto. El color nunca va solo: lleva icono y texto (visible desde `lg`, o siempre con
 * `showLabel`, y para lectores de pantalla siempre). */
const VERDICT_STYLE: Record<HealthVerdict, { icon: LucideIcon; text: string; dot: string }> = {
  ready: { icon: CircleCheck, text: "text-success", dot: "bg-success shadow-[0_0_6px_var(--success)]" },
  degraded: { icon: TriangleAlert, text: "text-warning", dot: "bg-warning" },
  unavailable: { icon: CircleX, text: "text-destructive", dot: "bg-destructive" },
};

/** El estado del backend a partir de `GET /health/ready` (M47, Commit 1): «Comprobando backend…», «Backend operativo»,
 * «Backend degradado» o «Backend no disponible». Solo dice si el backend responde y alcanza su base de datos. Lo usan la
 * cabecera del shell (desde `md`) y la del Director ejecutivo (bajo `md`), que comparten un único monitor. */
export function BackendStatus({ showLabel = false, className }: { showLabel?: boolean; className?: string }) {
  const state = useBackendHealth();
  const label = healthLabel(state);
  const refreshing = state.kind === "known" && state.refreshing;
  const style = state.kind === "known" ? VERDICT_STYLE[state.verdict] : null;
  const Icon = state.kind === "checking" ? LoaderCircle : refreshing ? LoaderCircle : style!.icon;
  const checkedAt =
    state.kind === "known"
      ? `Última comprobación: ${new Intl.DateTimeFormat("es-ES", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(state.checkedAt)}${refreshing ? " (actualizando…)" : ""}. `
      : "Todavía sin comprobar. ";
  return (
    <div
      role="status"
      aria-live="polite"
      aria-busy={state.kind === "checking" || refreshing}
      title={`${checkedAt}${HEALTH_SCOPE_NOTE}`}
      className={cn("flex items-center gap-1.5 text-xs", className)}
    >
      <Icon
        aria-hidden
        className={cn("size-3.5 shrink-0", style ? style.text : "text-muted-foreground", (state.kind === "checking" || refreshing) && "animate-spin")}
      />
      <span className={cn("size-2 rounded-full", style ? style.dot : "bg-muted-foreground/50")} aria-hidden />
      <span
        className={cn("font-medium", showLabel ? "" : "sr-only lg:not-sr-only", style ? "text-foreground" : "text-muted-foreground")}
      >
        {label}
      </span>
    </div>
  );
}
