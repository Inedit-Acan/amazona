import { AlertTriangle, Check } from "lucide-react";
import { cn } from "@/lib/utils";

export type VerdictTone = "ok" | "warn" | "bad";

/** Veredicto de un análisis (viabilidad económica, Legal Gate…): título corto y
 * una línea de detalle. El color acompaña al texto, nunca lo sustituye. El
 * llamador traduce la recomendación del agente; aquí no se decide nada. */
export function VerdictBanner({ tone, title, detail }: { tone: VerdictTone; title: string; detail: string }) {
  return (
    <div
      className={cn(
        "flex items-start gap-3 rounded-lg border p-3",
        tone === "ok" && "border-primary/40 bg-primary/10",
        tone === "warn" && "border-amber-500/40 bg-amber-500/10",
        tone === "bad" && "border-red-500/40 bg-red-500/10",
      )}
    >
      {tone === "ok" ? (
        <Check className="mt-0.5 size-4 shrink-0 text-primary" />
      ) : (
        <AlertTriangle className={cn("mt-0.5 size-4 shrink-0", tone === "warn" ? "text-amber-500" : "text-red-500")} />
      )}
      <div>
        <p className="text-sm font-semibold">{title}</p>
        <p className="mt-0.5 text-xs text-muted-foreground">{detail}</p>
      </div>
    </div>
  );
}
