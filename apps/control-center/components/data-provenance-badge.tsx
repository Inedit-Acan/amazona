import type { ComponentType } from "react";
import { Building2, Clock, Database, FileSignature, FlaskConical, LineChart, Server, ShieldCheck, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

/** The 4 data-provenance states every panel must distinguish — never
 * present an estimate as a confirmed fact (docs/design/
 * AMAZONA_sistema_de_diseno_visual.md §3). */
export type DataProvenance =
  | "ledger"
  | "declared"
  | "planned"
  | "recorded"
  | "verified"
  | "third_party"
  | "estimated"
  | "pending"
  | "demo";

const PROVENANCE_CONFIG: Record<
  DataProvenance,
  { label: string; short: string; description: string; icon: ComponentType<{ className?: string }>; className: string }
> = {
  // M45: lo que el backend registró como hecho de pago verificado (ADR 0030). Dice QUÉ demuestra el backend. Desde M46
  // (ADR 0031) cada hecho lleva su origen (`provider_kind`), pero esta etiqueta sigue sin poder leerse como «dinero que
  // se movió fuera del simulador»: el origen se enseña aparte, con su valor, y el texto final es del Commit 4.
  ledger: {
    label: "Registro verificado",
    short: "Registro",
    description:
      "El backend tiene este hecho de pago o reembolso verificado y registrado: no es un modelo ni una estimación. Cada cifra lleva el origen (provider_kind) que el backend guardó en el hecho; un hecho verificado no es dinero liquidado.",
    icon: Database,
    className: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30",
  },
  // M45, Commit 10: el coste de una línea de pedido. El backend lo guarda con su fuente (`cost_provenance`,
  // `cost_source`), pero nadie ha comprobado que se pagara: es un dato declarado, no un hecho.
  declared: {
    label: "Declarado",
    short: "Declarado",
    description:
      "Dato que alguien declaró y que el backend guarda con su fuente (una cotización de proveedor o una declaración manual). No es un pago comprobado.",
    icon: FileSignature,
    className: "bg-cyan-accent/15 text-cyan-accent border-cyan-accent/30",
  },
  // M45, Commit 10: lo que el modelo espera si los supuestos se cumplen. No ha ocurrido.
  planned: {
    label: "Proyección (PLAN)",
    short: "PLAN",
    description:
      "Proyección calculada sobre los supuestos de un análisis económico. No ha ocurrido: es lo que el modelo espera si esos supuestos se cumplen.",
    icon: LineChart,
    className: "bg-warning/15 text-warning border-warning/30",
  },
  // M46, Commit 8: lo que el backend GUARDA (un registro, un estado, un recuento de lo que hay en su base). Dice dónde está
  // el dato, no que alguien lo haya contrastado: un registro que existe no es un registro verificado. Neutral a propósito:
  // ningún color dice «bien».
  recorded: {
    label: "Registro del backend",
    short: "Backend",
    description:
      "Dato que el backend guarda tal cual: lo que el sistema registró, no una comprobación contra la fuente original. Que exista no lo hace verificado.",
    icon: Server,
    className: "bg-muted text-foreground border-border",
  },
  // `verified` queda para una verificación que consta en la fuente (p. ej. el proveedor de una cotización verificado por un
  // tercero). Lo que el backend solo guarda se llama `recorded`.
  verified: {
    label: "Verificado por un tercero",
    short: "Verificado (3.º)",
    description:
      "Lo verificó un tercero que consta en la fuente (por ejemplo, el proveedor de la cotización). AMAZONA no lo ha contrastado.",
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
    description: "Dato de demostración: se sustituirá por el dato del backend cuando lo proporcione.",
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
