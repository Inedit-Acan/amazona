import Link from "next/link";
import { ArrowRight, Wallet } from "lucide-react";
import { BudgetBar, BudgetInconsistency, BudgetNotice, BudgetStat, BudgetStatusChip, usedText } from "@/components/budget-parts";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api-server";
import { BUDGET_TITLE, readBudget, type BudgetView } from "@/lib/budget-view";

/** El presupuesto operativo en el Director ejecutivo (M47): una tarjeta COMPACTA bajo la fila de KPI, no una pantalla contable. Techo,
 * reservado, comprometido y disponible, el estado y la barra de uso; el detalle (gastado, periodo, fórmula, hora de lectura) está en
 * Finanzas. Lee `GET /api/budget` UNA vez, en el servidor, con la misma función que `/cfo` (`readBudget`): una sola fuente.
 *
 *  · `empty` ⇒ «No hay presupuesto autorizado»; `error` ⇒ «No disponible» + el motivo; `unread` ⇒ «Sin leer». Nunca un cero ni «Agotado».
 *  · No es «Cash disponible»: es un techo de gasto interno, y la tarjeta lo rotula como «Presupuesto operativo». */

const BUDGET_TOOLTIP =
  "El presupuesto que el propietario autorizó y lo que el libro del backend ha reservado y comprometido contra él. Un techo de gasto interno: no es caja ni ingresos.";

export function BudgetCard({ view }: { view: BudgetView }) {
  return (
    <Card data-block="presupuesto" data-block-state={view.kind} className="min-w-0">
      <CardHeader className="flex flex-row items-center justify-between gap-2 pb-0">
        <CardTitle className="flex min-w-0 items-center gap-2 text-sm font-semibold">
          <Wallet aria-hidden className="size-4 shrink-0 text-primary" />
          {BUDGET_TITLE}
        </CardTitle>
        {view.kind === "loaded" ? <BudgetStatusChip view={view} /> : null}
      </CardHeader>
      <CardContent className="space-y-3">
        {view.kind !== "loaded" ? (
          <BudgetNotice view={view} />
        ) : (
          <>
            <div className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
              <BudgetStat figure="techo" label="Techo" value={view.hardLimit} />
              <BudgetStat figure="reservado" label="Reservado" value={view.reserved} />
              <BudgetStat figure="comprometido" label="Comprometido" value={view.committed} />
              <BudgetStat
                figure="disponible"
                label="Disponible"
                value={view.remaining}
                tone={view.status === "inconsistent" ? "bad" : view.status === "exhausted" ? "warn" : "accent"}
              />
            </div>
            <BudgetBar view={view} />
            <BudgetInconsistency view={view} />
            <p className="text-[11px] leading-snug text-muted-foreground">
              {usedText(view)} · Periodo declarado: {view.period.toLowerCase()}
              {view.currencyNote ? ` · ${view.currencyNote}` : ""}
              {view.readAt ? ` · Leído ${view.readAt}` : ""}
            </p>
          </>
        )}
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1.5">
          <div className="flex flex-wrap items-center gap-1.5">
            <DataProvenanceBadge status="recorded" compact tooltip={BUDGET_TOOLTIP} />
            {view.kind === "loaded" ? <span className="text-[11px] text-muted-foreground">{view.scopeNote}</span> : null}
          </div>
          <Link
            href="/cfo#presupuesto"
            className="inline-flex items-center gap-1 rounded-sm text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          >
            Ver detalle en Finanzas <ArrowRight aria-hidden className="size-3" />
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}

/** Mientras el servidor lee: ninguna cifra, ningún cero. */
export function BudgetSkeleton() {
  return (
    <Card data-block="presupuesto" data-block-state="reading" aria-busy="true" className="min-w-0">
      <CardHeader className="pb-0">
        <CardTitle className="text-sm font-semibold">{BUDGET_TITLE}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <p className="text-sm text-muted-foreground">Leyendo presupuesto…</p>
        <div aria-hidden className="h-6 w-2/3 animate-pulse rounded bg-muted" />
      </CardContent>
    </Card>
  );
}

export async function BudgetBlock() {
  const view = await readBudget(api);
  return <BudgetCard view={view} />;
}
