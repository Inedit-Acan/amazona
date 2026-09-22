import type { ComponentType } from "react";
import { Building2, Clock, FlaskConical, ShieldCheck, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

/** The 4 data-provenance states every panel must distinguish — never
 * present an estimate as a confirmed fact (docs/design/
 * AMAZONA_sistema_de_diseno_visual.md §3). */
export type DataProvenance = "verified" | "third_party" | "estimated" | "pending" | "demo";

const PROVENANCE_CONFIG: Record<
  DataProvenance,
  { label: string; short: string; description: string; icon: ComponentType<{ className?: string }>; className: string }
> = {
  verified: {
    label: "Verificado",
    short: "Verificado",
    description: "Dato verificado contra su fuente original.",
    icon: ShieldCheck,
    className: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30",
  },
  third_party: {
    label: "Proveedor/tercero",
    short: "Proveedor",
    description: "Dato proporcionado por un proveedor o servicio externo, no verificado por AMAZONA.",
    icon: Building2,
    className: "bg-cyan-accent/15 text-cyan-accent border-cyan-accent/30",
  },
  estimated: {
    label: "Estimación AMAZONA",
    short: "Estimación",
    description: "Estimación calculada por AMAZONA a partir de datos disponibles — no es un hecho confirmado.",
    icon: Sparkles,
    className: "bg-warning/15 text-warning border-warning/30",
  },
  pending: {
    label: "Pendiente",
    short: "Pendiente",
    description: "Dato pendiente de validación.",
    icon: Clock,
    className: "bg-muted text-muted-foreground border-border",
  },
  demo: {
    label: "Datos de demostración",
    short: "Demo",
    description: "Dato de demostración: se sustituirá por el real cuando el backend lo proporcione.",
    icon: FlaskConical,
    className: "bg-sky-500/10 text-sky-300 border-sky-400/30",
  },
};

export function DataProvenanceBadge({
  status,
  tooltip,
  compact = false,
  className,
}: {
  status: DataProvenance;
  /** Etiqueta corta («Proveedor», «Estimación»…) y sin icono, para filas densas. */
  compact?: boolean;
  /** Overrides the default description in the tooltip (e.g. to name the specific source). */
  tooltip?: string;
  className?: string;
}) {
  const config = PROVENANCE_CONFIG[status];
  const Icon = config.icon;

  return (
    <Tooltip>
      <TooltipTrigger>
        <Badge variant="outline" className={cn("gap-1 font-medium", compact && "rounded-md", config.className, className)}>
          {compact ? null : <Icon className="size-3.5" />}
          {compact ? config.short : config.label}
        </Badge>
      </TooltipTrigger>
      <TooltipContent>{tooltip ?? config.description}</TooltipContent>
    </Tooltip>
  );
}
