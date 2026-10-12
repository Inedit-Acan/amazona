import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { originLabel, originMeaning, type OriginSummary } from "@/lib/provenance";
import { cn } from "@/lib/utils";

// El ORIGEN del dinero (M46, ADR 0031): de qué adaptador salió el hecho. Es un eje distinto al de `DataProvenanceBadge`
// (registro / declarado / PLAN / demo) y se pinta aparte. Ni el texto ni su significado se escriben aquí: salen de
// `lib/provenance.ts`, la única fuente. Ningún color dice «bien» o «mal»: describe al proveedor, no afirma nada del dinero.

const TONE: Record<OriginSummary["kind"], string> = {
  single: "border-border bg-muted/60 text-foreground",
  multiple: "border-warning/30 bg-warning/10 text-warning",
  none: "border-border bg-transparent text-muted-foreground",
  unknown: "border-destructive/30 bg-destructive/10 text-destructive",
};

export function OriginBadge({ summary, className }: { summary: OriginSummary; className?: string }) {
  return (
    <Tooltip>
      <TooltipTrigger>
        <Badge variant="outline" className={cn("rounded-md font-medium whitespace-nowrap", TONE[summary.kind], className)}>
          {originLabel(summary)}
        </Badge>
      </TooltipTrigger>
      <TooltipContent>{originMeaning(summary)}</TooltipContent>
    </Tooltip>
  );
}
