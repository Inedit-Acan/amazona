import Link from "next/link";
import { OctagonPause } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { moreText, RECORDED_LABEL, RECORDED_MEANING, type BlockRow, type BlockView } from "@/lib/ceo-block-view";
import { cn } from "@/lib/utils";

/** Cómo se pinta lo que cada bloque del tríptico ya decidió (M47, Commit 3B). Este componente NO interpreta nada: no filtra, no ordena,
 * no mira estados ni fechas; recibe filas, una franja y líneas ya calculadas por `lib/ceo-decisions`, `ceo-opportunities` y `ceo-risks`.
 * Las filas son enlaces reales (teclado y foco visibles) a la pantalla donde vive el detalle; el tooltip, que también se abre con el
 * foco, trae el texto completo y los detalles que la fila recorta. */

type Loaded = Extract<BlockView, { kind: "loaded" }>;

/** El tono de la etiqueta cuando el backend da una severidad real; sin severidad, neutra. */
const LEVEL_STYLE = {
  low: "border-border text-muted-foreground",
  medium: "border-amber-500/40 text-amber-700 dark:text-amber-400",
  high: "border-orange-500/50 text-orange-700 dark:text-orange-400",
  critical: "border-destructive/50 bg-destructive/10 text-destructive",
} as const;

function Row({ row, href }: { row: BlockRow; href: string }) {
  const { source, entity, id, areaLabel } = row.provenance;
  return (
    <li data-row={row.key} data-source={source} data-entity={entity} data-id={id ?? undefined} className="min-w-0">
      <Tooltip>
        <TooltipTrigger
          render={
            <Link
              href={href}
              className="flex min-w-0 items-center justify-between gap-2 rounded-md px-1.5 py-1 transition-colors hover:bg-muted/50 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            />
          }
        >
          <span className="min-w-0 flex-1">
            {row.tag.level ? null : (
              <span className="block truncate text-[10px] font-medium tracking-wide text-muted-foreground uppercase">{row.tag.text}</span>
            )}
            <span className="line-clamp-2 text-sm font-medium break-words">{row.title}</span>
            <span className="block truncate text-xs text-muted-foreground">{row.subtitle}</span>
          </span>
          {row.tag.level ? (
            <Badge variant="outline" className={cn("shrink-0", LEVEL_STYLE[row.tag.level])}>
              {row.tag.text}
            </Badge>
          ) : null}
        </TooltipTrigger>
        <TooltipContent className="max-w-xs space-y-1 whitespace-normal">
          <p className="font-medium break-words">{row.title}</p>
          <p className="break-words text-muted-foreground">{row.subtitle}</p>
          {row.detail.map((line) => (
            <p key={line} className="break-words">
              {line}
            </p>
          ))}
          <p className="text-muted-foreground">Origen: {areaLabel}</p>
        </TooltipContent>
      </Tooltip>
    </li>
  );
}

/** El contenido de un bloque con lectura válida: franja de estado, tres filas, «y N más» y lo que queda fuera del contador. */
export function BlockRows({ view, href }: { view: Loaded; href: string }) {
  return (
    <div className="space-y-2" data-count={view.count}>
      {view.strip ? (
        <div data-strip={view.strip.provenance.source} className="flex items-start gap-2 rounded-md border border-border bg-muted/30 p-2">
          <OctagonPause aria-hidden className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
          <div className="min-w-0">
            <p className="text-xs font-medium break-words">{view.strip.text}</p>
            {view.strip.detail ? <p className="text-xs break-words text-muted-foreground">{view.strip.detail}</p> : null}
          </div>
        </div>
      ) : null}
      {view.noRowsText ? <p className="text-sm text-muted-foreground">{view.noRowsText}</p> : null}
      {view.visible.length > 0 ? (
        <ul className="space-y-0.5">
          {view.visible.map((row) => (
            <Row key={row.key} row={row} href={href} />
          ))}
        </ul>
      ) : null}
      {view.more > 0 ? (
        <p data-more={view.more} className="px-1.5 text-xs text-muted-foreground">
          {moreText(view.more)}
        </p>
      ) : null}
      {view.secondary.map((line) => (
        <p key={line} data-section="fuera-del-contador" className="text-[11px] leading-snug text-muted-foreground">
          {line}
        </p>
      ))}
    </div>
  );
}

/** El pie de un bloque con lectura válida: la línea fija (si la hay) y la insignia «Registrado». */
export function BlockFooter({ footnote }: { footnote: string | null }) {
  return (
    <div className="mt-3 space-y-1.5">
      {footnote ? <p className="text-[11px] leading-snug text-muted-foreground">{footnote}</p> : null}
      <Tooltip>
        <TooltipTrigger className="inline-flex rounded-md focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
          <Badge variant="outline" className="rounded-md bg-muted text-foreground">
            {RECORDED_LABEL}
          </Badge>
        </TooltipTrigger>
        <TooltipContent className="max-w-xs whitespace-normal">{RECORDED_MEANING}</TooltipContent>
      </Tooltip>
    </div>
  );
}
