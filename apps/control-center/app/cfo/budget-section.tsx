import { Wallet } from "lucide-react";
import { BudgetBar, BudgetInconsistency, BudgetNotice, BudgetStat, BudgetStatusChip, usedText } from "@/components/budget-parts";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { BUDGET_TITLE, type BudgetLoadedView, type BudgetView } from "@/lib/budget-view";

/** Presupuesto operativo (M47): el control del gasto interno, aparte de las tres zonas de dinero de esta pantalla.
 *
 * No es ninguna de ellas y no se suma ni se compara con ellas: no es ingreso (registro verificado), ni coste declarado, ni proyección, ni
 * «cash». Es el techo que el propietario autorizó y lo que el libro del backend ha reservado y comprometido contra él. Lee la MISMA vista
 * que `/ceo` (`readBudget`, una lectura de `GET /api/budget`): esta pantalla solo la enseña con más detalle. */

const BUDGET_TOOLTIP =
  "El presupuesto que el propietario autorizó y lo que el libro del backend ha reservado y comprometido contra él. Lo guarda el backend; no es un pago comprobado ni caja.";

const FORMULA = "Usado = reservado + comprometido · Disponible = techo − usado. Lo gastado se enseña aparte y no se resta: ya está dentro de lo comprometido.";

function Detail({ view }: { view: BudgetLoadedView }) {
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <Figure figure="techo" label="Techo (hard limit)" value={view.hardLimit} hint={view.softLimit ? `Umbral de aviso ${view.softLimit}` : undefined} />
        <Figure figure="reservado" label="Reservado" value={view.reserved} hint="Pendiente de una aprobación" />
        <Figure figure="comprometido" label="Comprometido" value={view.committed} hint="Reserva ya aprobada" />
        <Figure figure="gastado" label="Gastado" value={view.spent} hint="Aparte: ya está en lo comprometido" />
        <Figure
          figure="disponible"
          label="Disponible"
          value={view.remaining}
          hint={view.status === "exhausted" ? "Sin saldo para reservar" : undefined}
          tone={view.status === "inconsistent" ? "bad" : view.status === "exhausted" ? "warn" : "accent"}
        />
      </div>
      <Card className="min-w-0">
        <CardContent className="space-y-2.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-medium">{usedText(view)}</p>
            <BudgetStatusChip view={view} />
          </div>
          <BudgetBar view={view} />
          <BudgetInconsistency view={view} />
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
            <span className="flex items-center gap-1.5">
              <span aria-hidden className="inline-block size-2 rounded-full bg-primary" /> Comprometido
            </span>
            <span className="flex items-center gap-1.5">
              <span aria-hidden className="inline-block size-2 rounded-full bg-warning" /> Reservado
            </span>
            <span className="flex items-center gap-1.5">
              <span aria-hidden className="inline-block size-2 rounded-full bg-muted-foreground/40" /> Disponible
            </span>
          </div>
        </CardContent>
      </Card>
      <dl data-budget-meta="" className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-[11px] sm:grid-cols-4">
        <Meta label="Periodo declarado" value={view.period} />
        <Meta label="Moneda" value={view.currency ?? view.currencyNote ?? ""} />
        <Meta label="Fuente" value="Libro del backend" />
        <Meta label="Última lectura" value={view.readAt ?? "Sin hora de lectura"} />
      </dl>
      <p className="text-[11px] text-muted-foreground">{FORMULA}</p>
      <p className="text-[11px] text-muted-foreground">{view.scopeNote}</p>
    </div>
  );
}

function Figure({
  figure,
  label,
  value,
  hint,
  tone,
}: {
  figure: string;
  label: string;
  value: string;
  hint?: string;
  tone?: "default" | "accent" | "warn" | "bad";
}) {
  return (
    <Card className="min-w-0">
      <CardContent>
        <BudgetStat figure={figure} label={label} value={value} hint={hint} tone={tone} />
      </CardContent>
    </Card>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-medium break-words">{value}</dd>
    </div>
  );
}

export function BudgetSection({ view }: { view: BudgetView }) {
  return (
    <section id="presupuesto" data-block="presupuesto" data-block-state={view.kind} aria-label={BUDGET_TITLE} className="space-y-3 scroll-mt-4">
      <div className="flex flex-wrap items-start justify-between gap-2 border-t pt-4">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 text-sm font-semibold tracking-tight">
            <Wallet aria-hidden className="size-4 shrink-0 text-primary" />
            {BUDGET_TITLE}
          </h2>
          <p className="mt-1 max-w-3xl text-[11px] text-muted-foreground">
            El techo de gasto interno que autorizó el propietario y lo que se ha reservado y comprometido contra él. No es cash, ni ingresos, ni beneficio,
            ni una de las tres zonas de arriba: no se suma con ellas.
          </p>
        </div>
        <DataProvenanceBadge status="recorded" tooltip={BUDGET_TOOLTIP} />
      </div>
      {view.kind === "loaded" ? (
        <Detail view={view} />
      ) : (
        <Card className="min-w-0">
          <CardHeader className="pb-0">
            <CardTitle className="sr-only">{BUDGET_TITLE}</CardTitle>
          </CardHeader>
          <CardContent>
            <BudgetNotice view={view} />
          </CardContent>
        </Card>
      )}
    </section>
  );
}
