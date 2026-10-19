import type { ReactNode } from "react";
import { CircleDashed, Inbox, TriangleAlert } from "lucide-react";
import { LevelChip, type LevelTone } from "@/components/level-chip";
import { READ_UNAVAILABLE_VALUE, READ_UNREAD_TEXT } from "@/lib/read-state";
import type { BudgetLoadedView, BudgetStatus, BudgetView } from "@/lib/budget-view";
import { cn } from "@/lib/utils";

// Las piezas que comparten `/ceo` (tarjeta compacta) y `/cfo` (detalle) para enseñar el presupuesto operativo (M47). Aquí no se decide nada:
// todo lo que se pinta sale de la vista de `lib/budget-view.ts`, y el texto de cada estado es el que esa vista fija.

const STATUS_TONE: Record<BudgetStatus, LevelTone> = {
  available: "ok",
  partial: "neutral",
  exhausted: "warn",
  inconsistent: "bad",
};

/** El estado del presupuesto como chip. «Agotado» es un estado de un presupuesto leído (ámbar), no un error: un error no lleva chip. */
export function BudgetStatusChip({ view }: { view: BudgetLoadedView }) {
  return (
    <LevelChip tone={STATUS_TONE[view.status]} className="shrink-0">
      <span data-budget-status={view.status}>{view.statusLabel}</span>
    </LevelChip>
  );
}

/** Qué se enseña cuando NO hay un presupuesto leído: vacío (un hecho), error o sin leer. Cuatro situaciones, cuatro textos, ningún cero. */
export function BudgetNotice({ view }: { view: Exclude<BudgetView, BudgetLoadedView> }) {
  if (view.kind === "error") {
    return (
      <div data-budget-state="error" className="space-y-1">
        <p className="flex items-center gap-2 text-xl leading-tight font-semibold">
          <TriangleAlert aria-hidden className="size-4 shrink-0 text-destructive" />
          {READ_UNAVAILABLE_VALUE}
        </p>
        <p className="text-xs text-destructive">{view.message}</p>
      </div>
    );
  }
  if (view.kind === "unread") {
    return (
      <div data-budget-state="unread" className="space-y-1">
        <p className="flex items-center gap-2 text-xl leading-tight font-semibold">
          <CircleDashed aria-hidden className="size-4 shrink-0 text-muted-foreground" />
          {READ_UNREAD_TEXT}
        </p>
        <p className="text-xs text-muted-foreground">{view.reason}</p>
      </div>
    );
  }
  return (
    <div data-budget-state="empty" className="space-y-1">
      <p className="flex items-center gap-2 text-xl leading-tight font-semibold">
        <Inbox aria-hidden className="size-4 shrink-0 text-muted-foreground" />
        {view.label}
      </p>
      <p className="text-xs text-muted-foreground">{view.detail}</p>
    </div>
  );
}

/** Una cifra del presupuesto con su etiqueta. `tone` solo colorea el valor (lo disponible agotado o negativo se distingue a simple vista). */
export function BudgetStat({
  label,
  value,
  hint,
  tone = "default",
  figure,
}: {
  label: string;
  value: string;
  hint?: ReactNode;
  tone?: "default" | "accent" | "warn" | "bad";
  figure: string;
}) {
  return (
    <div data-budget-figure={figure} className="min-w-0 space-y-0.5">
      <p className="text-[11px] text-muted-foreground">{label}</p>
      <p
        className={cn(
          "text-lg leading-tight font-semibold tabular-nums break-words",
          tone === "accent" && "text-primary",
          tone === "warn" && "text-warning",
          tone === "bad" && "text-destructive",
        )}
      >
        {value}
      </p>
      {hint ? <p className="text-[11px] leading-snug text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

/** La barra de uso: lo comprometido y lo reservado, sobre el techo. Solo existe si el saldo cuadra (la vista da `bar = null` si no): un
 * porcentaje sobre una contabilidad rota sería una cifra falsa. */
export function BudgetBar({ view }: { view: BudgetLoadedView }) {
  if (view.bar === null || view.usedPercent === null) return null;
  const { reservedPercent, committedPercent } = view.bar;
  return (
    <div
      role="img"
      data-budget-bar=""
      aria-label={`Usado ${view.usedPercent} % del techo: ${committedPercent} % comprometido y ${reservedPercent} % reservado`}
      className="flex h-2 w-full overflow-hidden rounded-full bg-muted"
    >
      <div className="h-full bg-primary" style={{ width: `${committedPercent}%` }} />
      <div className="h-full bg-warning" style={{ width: `${reservedPercent}%` }} />
    </div>
  );
}

/** La inconsistencia, a la vista y sin adornos: el saldo no cuadra. */
export function BudgetInconsistency({ view }: { view: BudgetLoadedView }) {
  if (view.inconsistency === null) return null;
  return (
    <p data-budget-inconsistency="" className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/5 p-2 text-xs text-destructive">
      <TriangleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0" />
      {view.inconsistency}
    </p>
  );
}

/** Lo que dice el porcentaje, en una línea. */
export function usedText(view: BudgetLoadedView): string {
  return view.usedPercent === null ? "Uso no calculable" : `Usado ${String(view.usedPercent).replace(".", ",")} %`;
}
