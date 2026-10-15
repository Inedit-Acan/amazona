"use client";

import { STATUS_LABEL } from "@/lib/neural-nexus";
import type { EngineHud, HudField, Provenance } from "@/lib/nexus-engine-state";
import { cn } from "@/lib/utils";
import { STATUS_COLOR } from "./nexus-theme";

/** Cómo se llama cada procedencia. Cada fila del HUD es una de las tres: lo que el backend guarda (`recorded`), lo que se calcula de datos
 * guardados (`derived`) o lo que no hay (`unavailable`). */
const PROVENANCE_LABEL: Record<Provenance, string> = {
  recorded: "Registrado",
  derived: "Derivado",
  unavailable: "No disponible",
};

const NOTICE_STYLE = {
  info: "border-white/10 text-muted-foreground",
  warning: "border-amber-500/40 text-amber-600 dark:text-amber-400",
  error: "border-destructive/40 text-destructive",
} as const;

function Row({ field }: { field: HudField }) {
  const muted = field.provenance === "unavailable";
  return (
    <div
      data-provenance={field.provenance}
      data-field={field.label}
      title={`${PROVENANCE_LABEL[field.provenance]}${field.note ? `: ${field.note}` : ""}`}
      className="flex items-baseline justify-between gap-3 text-xs"
    >
      <span className="min-w-0 shrink-0 text-muted-foreground">{field.label}</span>
      <span className={cn("min-w-0 text-right break-words", muted ? "text-muted-foreground" : "tabular-nums")}>
        {field.text}
        <span className="sr-only"> ({PROVENANCE_LABEL[field.provenance]})</span>
      </span>
    </div>
  );
}

/** Panel de métricas del Decision Engine (especificación §22). Solo PINTA lo que `engineHud` ya decidió: cada fila lleva su procedencia
 * (`data-provenance`), y lo que falta dice «Sin dato» o «No disponible» (M47 · Commit 4). Nada es de demostración. */
export function NexusHud({ hud }: { hud: EngineHud }) {
  const color = STATUS_COLOR[hud.coreStatus];
  return (
    <div className="pointer-events-none w-60 rounded-xl border border-white/10 bg-[#071713]/85 p-3 backdrop-blur-sm">
      <p className="text-[11px] font-semibold tracking-wide text-foreground">DECISION ENGINE</p>
      <p className="mb-2.5 flex items-center gap-1.5 text-xs font-medium" style={{ color }}>
        <span className="size-1.5 rounded-full" style={{ background: color }} aria-hidden />
        {STATUS_LABEL[hud.coreStatus]}
      </p>
      {hud.notice ? (
        <p data-hud-notice={hud.notice.tone} className={cn("mb-2 rounded-md border px-2 py-1 text-[11px] leading-snug", NOTICE_STYLE[hud.notice.tone])}>
          {hud.notice.text}
        </p>
      ) : null}
      <div className="space-y-1.5">
        {hud.fields.map((field) => (
          <Row key={field.label} field={field} />
        ))}
      </div>
      {hud.progress === null ? null : (
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/10" aria-hidden>
          <div className="h-full rounded-full bg-primary" style={{ width: `${Math.round(hud.progress * 100)}%` }} />
        </div>
      )}
    </div>
  );
}
