import { BlockCard } from "@/components/ceo/block-card";
import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { AREA_BLOCK, areaStateOf, type AreaRow, type AreaView } from "@/lib/ceo-area-executions";
import { plural } from "@/lib/ceo-block-view";
import { cn } from "@/lib/utils";

/** «Ejecuciones por área» (M47, Commit 5): por cada uno de los ocho dominios, cuántas de las últimas ejecuciones registradas fueron
 * correctas, la latencia media y la última ejecución. Este componente NO calcula nada: recibe la vista ya hecha por
 * `lib/ceo-area-executions`. No hay porcentajes ni puntuaciones: «X de Y correctas». */

type Loaded = Extract<AreaView, { kind: "loaded" }>;

const DERIVED_LABEL = "Derivado";
const DERIVED_MEANING =
  "Calculado a partir de las ejecuciones que el backend registró: conteos, «X de Y correctas», latencia media y área. La fecha de la última ejecución es la registrada.";

function Row({ row }: { row: AreaRow }) {
  const idle = row.total === 0;
  return (
    <li data-area={row.area} data-total={row.total} data-idle={idle ? "true" : undefined} className="min-w-0 rounded-md px-1.5 py-1">
      <div className="flex min-w-0 items-baseline justify-between gap-2">
        <span className={cn("min-w-0 text-sm font-medium [overflow-wrap:anywhere]", idle && "text-muted-foreground")}>{row.area}</span>
        <span className={cn("shrink-0 text-xs tabular-nums", idle ? "text-muted-foreground" : "text-foreground")}>{row.okText}</span>
      </div>
      {idle ? null : (
        <p className="text-xs text-muted-foreground [overflow-wrap:anywhere]">
          {row.failedText} · Latencia media {row.latencyText} · Última {row.lastText} · {row.agents} {plural(row.agents, "agente", "agentes")}
        </p>
      )}
    </li>
  );
}

function Rows({ view }: { view: Loaded }) {
  return (
    <div className="space-y-2" data-total={view.total} data-truncated={view.truncated ? "true" : undefined}>
      <p className="text-xs text-muted-foreground">{view.windowText}</p>
      <ul className="space-y-0.5">
        {view.rows.map((row) => (
          <Row key={row.area} row={row} />
        ))}
      </ul>
    </div>
  );
}

function Footer({ footnote }: { footnote: string }) {
  return (
    <div className="mt-3 space-y-1.5">
      <p className="text-[11px] leading-snug text-muted-foreground">{footnote}</p>
      <Tooltip>
        <TooltipTrigger className="inline-flex rounded-md focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
          <Badge variant="outline" className="rounded-md bg-muted text-foreground">
            {DERIVED_LABEL}
          </Badge>
        </TooltipTrigger>
        <TooltipContent className="max-w-xs whitespace-normal">{DERIVED_MEANING}</TooltipContent>
      </Tooltip>
    </div>
  );
}

export function AreaExecutionsCard({ view, className }: { view: AreaView; className?: string }) {
  return (
    <BlockCard
      title={AREA_BLOCK.title}
      state={areaStateOf(view)}
      className={className}
      emptyNotice={view.kind === "empty" ? { label: view.text, detail: "El backend respondió y el log de ejecuciones está vacío." } : undefined}
      footer={view.kind === "loaded" ? <Footer footnote={view.footnote} /> : undefined}
    >
      {view.kind === "loaded" ? <Rows view={view} /> : null}
    </BlockCard>
  );
}
