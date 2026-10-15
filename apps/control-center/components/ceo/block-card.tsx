import Link from "next/link";
import type { ReactNode } from "react";
import { ArrowRight, Ban, CircleDashed, Inbox, TriangleAlert, type LucideIcon } from "lucide-react";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { blockNotice, type BlockKind, type BlockState } from "@/lib/ceo-blocks";
import { cn } from "@/lib/utils";

/** Icono y tono de lo que un bloque dice cuando NO tiene dato. Cuatro situaciones distintas, cuatro aspectos distintos:
 * sin leer (borde discontinuo), no disponible (tachado), error (rojo) y vacío (bandeja). Nunca un cero. */
const NOTICE_STYLE: Record<Exclude<BlockKind, "loaded">, { icon: LucideIcon; box: string; text: string }> = {
  unread: { icon: CircleDashed, box: "border-dashed border-border", text: "text-muted-foreground" },
  unavailable: { icon: Ban, box: "border-border bg-muted/30", text: "text-muted-foreground" },
  error: { icon: TriangleAlert, box: "border-destructive/40 bg-destructive/5", text: "text-destructive" },
  empty: { icon: Inbox, box: "border-border", text: "text-muted-foreground" },
};

/** El aviso de un bloque sin dato. `data-block-state` lo hace comprobable (pruebas y revisión visual). `empty` deja que el bloque diga SU
 * vacío («Ninguna decisión pendiente») en lugar del genérico; no cambia el aspecto ni el estado. */
export function BlockNotice({
  state,
  empty,
  className,
}: {
  state: BlockState<unknown>;
  empty?: { label: string; detail: string };
  className?: string;
}) {
  const base = blockNotice(state);
  if (base === null) return null;
  const notice = base.kind === "empty" && empty ? { ...base, ...empty } : base;
  const style = NOTICE_STYLE[notice.kind];
  const Icon = style.icon;
  return (
    <div
      data-block-state={notice.kind}
      className={cn("flex items-start gap-2.5 rounded-lg border p-3", style.box, className)}
    >
      <Icon aria-hidden className={cn("mt-0.5 size-4 shrink-0", style.text)} />
      <div className="min-w-0">
        <p className={cn("text-sm font-medium", notice.kind === "error" ? style.text : "text-foreground")}>{notice.label}</p>
        <p className="text-xs leading-snug text-muted-foreground">{notice.detail}</p>
      </div>
    </div>
  );
}

/** Tarjeta de un bloque del Director ejecutivo. Con lectura válida enseña `children`; en cualquier otro estado, su aviso. Es
 * la pieza que reutilizan los Commits 3–6 para conectar cada bloque a su fuente. */
export function BlockCard({
  title,
  state,
  seeAll,
  hideTitle = false,
  count,
  emptyNotice,
  footer,
  children,
  className,
}: {
  title: string;
  state: BlockState<unknown>;
  /** «Ver todas»: a la pantalla donde vive el detalle de este bloque. */
  seeAll?: { href: string; label: string };
  /** El título ya lo da la pestaña que contiene la tarjeta: se queda solo para lectores de pantalla. */
  hideTitle?: boolean;
  /** El contador de la cabecera, ya calculado por la vista del bloque: aquí solo se pinta. */
  count?: { text: string; label: string };
  /** Lo que dice el bloque cuando su lectura es válida y no hay nada. */
  emptyNotice?: { label: string; detail: string };
  /** Lo que va debajo del contenido o del aviso (la insignia de procedencia y las líneas fijas). */
  footer?: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <Card className={cn("min-w-0", className)} data-block={title}>
      <CardHeader>
        <div className="flex min-w-0 items-center gap-2">
          <CardTitle className={cn("text-sm font-semibold", hideTitle && "sr-only")}>{title}</CardTitle>
          {count ? (
            <span
              data-slot="block-count"
              aria-label={count.label}
              className="inline-flex h-5 shrink-0 items-center rounded-full bg-muted px-2 text-xs font-medium text-foreground tabular-nums"
            >
              {count.text}
            </span>
          ) : null}
        </div>
        {seeAll ? (
          <CardAction>
            <Link
              href={seeAll.href}
              aria-label={`${seeAll.label}: ${title}`}
              className="inline-flex items-center gap-1 rounded-sm text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            >
              {seeAll.label} <ArrowRight aria-hidden className="size-3" />
            </Link>
          </CardAction>
        ) : null}
      </CardHeader>
      <CardContent>
        {state.kind === "loaded" ? children : <BlockNotice state={state} empty={emptyNotice} />}
        {footer}
      </CardContent>
    </Card>
  );
}
