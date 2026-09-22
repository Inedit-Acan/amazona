import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export type LevelTone = "ok" | "warn" | "bad" | "neutral";

const TONE: Record<LevelTone, string> = {
  ok: "border-primary/30 bg-primary/15 text-primary",
  warn: "border-warning/30 bg-warning/15 text-warning",
  bad: "border-destructive/30 bg-destructive/15 text-destructive",
  neutral: "border-border bg-muted text-muted-foreground",
};

/** Chip de nivel coloreado (Alta / Media / Baja, Bajo / Medio / Alto…). Quien
 * lo usa decide el tono, porque «alta» es buena en demanda y mala en competencia. */
export function LevelChip({ tone, children, className }: { tone: LevelTone; children: ReactNode; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex min-w-12 items-center justify-center rounded-md border px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        TONE[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
