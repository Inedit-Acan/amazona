import { BlockCard } from "@/components/ceo/block-card";
import { BlockFooter } from "@/components/ceo/block-rows";
import { Badge } from "@/components/ui/badge";
import { ACTIVITY_BLOCK, activityStateOf, type ActivityRow, type ActivityView } from "@/lib/ceo-activity";
import { moreText } from "@/lib/ceo-block-view";

/** «Actividad registrada» (M47, Commit 5): las últimas cinco entradas del registro de auditoría, con su fecha y hora absolutas. Este
 * componente NO interpreta nada: no ordena, no filtra, no cuenta ni decide qué es un fallo; recibe la vista ya calculada por
 * `lib/ceo-activity`. No lleva «Ver todas»: ninguna pantalla existente es el detalle de este bloque (`/agents` no es el registro de
 * actividad y `/audit` mezcla filas de demostración con las del backend). */

type Loaded = Extract<ActivityView, { kind: "loaded" }>;

function Row({ row }: { row: ActivityRow }) {
  return (
    <li
      data-row={row.key}
      data-source={row.provenance.source}
      data-id={row.provenance.id}
      data-category={row.category}
      data-failed={row.failed ? "true" : undefined}
      className="min-w-0 space-y-0.5 rounded-md px-1.5 py-1"
    >
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5">
        <time dateTime={row.at} className="text-xs text-muted-foreground tabular-nums">
          {row.atText}
        </time>
        <span title="Categoría derivada del prefijo de la acción" className="text-[10px] font-medium tracking-wide text-muted-foreground uppercase">
          {row.category}
        </span>
        {row.failed ? (
          <Badge variant="outline" title="Derivado: la acción dice fail o error" className="border-destructive/50 bg-destructive/10 text-destructive">
            Fallo
          </Badge>
        ) : null}
      </div>
      <p className="font-mono text-xs font-medium [overflow-wrap:anywhere]">{row.action}</p>
      <p className="text-xs text-muted-foreground [overflow-wrap:anywhere]">
        {row.actor.text}
        {row.area ? <span title="Área derivada del rol del agente"> · {row.area}</span> : <span title="Sin área derivable"> · —</span>}
      </p>
    </li>
  );
}

function Rows({ view }: { view: Loaded }) {
  return (
    <div className="space-y-2" data-count={view.total}>
      <p className="text-xs text-muted-foreground">{view.subtitle}</p>
      <ul className="space-y-0.5">
        {view.visible.map((row) => (
          <Row key={row.key} row={row} />
        ))}
      </ul>
      {view.more > 0 ? (
        <p data-more={view.more} className="px-1.5 text-xs text-muted-foreground">
          {moreText(view.more)}
        </p>
      ) : null}
    </div>
  );
}

export function ActivityCard({ view, className }: { view: ActivityView; className?: string }) {
  return (
    <BlockCard
      title={ACTIVITY_BLOCK.title}
      state={activityStateOf(view)}
      className={className}
      count={view.kind === "loaded" ? { text: String(view.total), label: `${view.total} entradas leídas del registro de auditoría` } : undefined}
      emptyNotice={view.kind === "empty" ? { label: view.text, detail: "El backend respondió y el registro de auditoría está vacío." } : undefined}
      footer={
        view.kind === "loaded" ? (
          <>
            {view.agentsNote ? <p className="mt-3 text-[11px] leading-snug text-muted-foreground">{view.agentsNote}</p> : null}
            <BlockFooter footnote={view.footnote} />
          </>
        ) : undefined
      }
    >
      {view.kind === "loaded" ? <Rows view={view} /> : null}
    </BlockCard>
  );
}
