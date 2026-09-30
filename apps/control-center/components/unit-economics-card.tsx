import type { CostConcept, EconomicAnalysis, MoneyAmount, SupplierProvenance } from "@/lib/api";
import { fxNotices, fxSourceLabel, ingestedOn } from "@/lib/fx-source";
import { PROVENANCE_LABEL } from "@/lib/sourcing-view";
import { Badge } from "@/components/ui/badge";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const CONCEPT_LABEL: Record<CostConcept, string> = {
  product: "Producto",
  logistics: "Logística / transporte",
  import: "Aranceles / importación",
  channel: "Comisión del canal",
  payment: "Pago / transacción",
  other_variable: "Otros costes variables",
};

const MISSING_LABEL: Record<string, string> = {
  ...CONCEPT_LABEL,
  exchange_rate: "Tipo de cambio",
  units_per_order: "Unidades por pedido",
  expected_monthly_orders: "Pedidos mensuales esperados",
  monthly_fixed_costs: "Costes fijos mensuales",
};

/** Cómo se enseña cada una de las cinco situaciones de un coste. «No declarado»
 * y «no aplica» se ven distinto a propósito: confundirlos es el error que el
 * Milestone 40 quita del backend, y sería una lástima recometerlo aquí. */
function statusText(component: EconomicAnalysis["data"] extends null ? never : { status: string; included_in: CostConcept | null; reason: string | null }): string {
  switch (component.status) {
    case "included_in_another":
      return `Incluido en ${component.included_in ? CONCEPT_LABEL[component.included_in].toLowerCase() : "otro coste"}`;
    case "not_applicable":
      return component.reason ?? "No aplica";
    case "unknown_required":
      return "No declarado · hace falta";
    case "unknown_optional":
      return "No declarado";
    default:
      return "";
  }
}

function amount(value: MoneyAmount | null): string {
  if (value === null) return "—";
  const number = Number(value.amount);
  return `${number.toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${value.currency}`;
}

function fromString(value: string | null, currency: string | null): string {
  if (value === null) return "—";
  return amount({ amount: value, currency: currency ?? "" });
}

function provenanceLabel(provenance: SupplierProvenance): string {
  return PROVENANCE_LABEL[provenance];
}

/** La economía unitaria tal y como la calculó el backend (Milestone 40).
 *
 * El backend es la implementación canónica: esta tarjeta **presenta**, no
 * calcula. Y enseña tres cosas que hasta aquí no existían: en qué canal y
 * moneda se calculó, de qué componentes está hecho el margen con la procedencia
 * de cada uno, y qué falta cuando algo no se puede evaluar. */
export function UnitEconomicsCard({ analysis }: { analysis: EconomicAnalysis }) {
  const unit = analysis.data?.unit_economics;
  const currency = analysis.currency;
  const notEvaluable = analysis.margin_evaluability === "not_evaluable";
  const missing = analysis.missing_inputs ?? [];

  return (
    <Card id="economia-unitaria" className="scroll-mt-4">
      <CardHeader>
        <CardTitle>Economía unitaria</CardTitle>
        <CardDescription>
          Calculada por el backend para un canal y una moneda concretos. Esta pantalla la presenta;
          no la calcula.
        </CardDescription>
        <CardAction>
          <div className="flex flex-wrap items-center gap-1.5">
            {analysis.channel && <Badge variant="outline">{analysis.channel}</Badge>}
            {currency && <Badge variant="outline">{currency}</Badge>}
            {unit && (
              <Badge variant="outline" title="Un margen no vale más que el más flojo de sus sumandos">
                {provenanceLabel(unit.weakest_provenance)}
              </Badge>
            )}
          </div>
        </CardAction>
      </CardHeader>

      <CardContent className="space-y-4 text-[13px]">
        {notEvaluable && (
          <div className="rounded-lg border border-warning/30 bg-warning/10 px-3 py-2">
            <p className="font-medium text-warning">No evaluable</p>
            <p className="text-muted-foreground">
              No es un resultado negativo: es la ausencia de resultado. Falta{" "}
              {missing.map((key) => MISSING_LABEL[key] ?? key).join(", ")}. Nada se ha completado
              con ceros ni con un cambio de 1:1.
            </p>
          </div>
        )}

        {unit && (
          <dl className="rounded-lg border bg-background/40 px-3 py-1">
            <p className="py-1.5 text-[11px] text-muted-foreground">
              Precio de venta menos cada coste variable conocido. Lo que está dentro de otro coste
              no se suma —se contaría dos veces— y lo que no aplica no es un coste de cero.
            </p>
            {unit.components.map((component) => (
              <div key={component.concept} className="flex justify-between gap-3 border-b py-1.5 last:border-b-0">
                <dt className="min-w-0">
                  <span className={component.status === "known" ? "" : "text-muted-foreground"}>
                    {CONCEPT_LABEL[component.concept]}
                  </span>
                  <span className="block text-[11px] text-muted-foreground">
                    {component.status === "known"
                      ? provenanceLabel(component.provenance)
                      : statusText(component)}
                    {component.source ? ` · ${component.source}` : ""}
                  </span>
                </dt>
                <dd className="font-medium whitespace-nowrap tabular-nums">{amount(component.amount)}</dd>
              </div>
            ))}
          </dl>
        )}

        <dl className="grid gap-x-4 rounded-lg border bg-background/40 px-3 py-1 sm:grid-cols-2">
          {[
            ["Margen de contribución por unidad", fromString(analysis.contribution_margin_per_unit, currency)],
            [
              `Margen por pedido${analysis.units_per_order ? ` (${analysis.units_per_order} u.)` : ""}`,
              fromString(analysis.contribution_margin_per_order, currency),
            ],
            ["Coste fijo asignado por pedido", fromString(analysis.allocated_fixed_cost_per_order, currency)],
            ["CAC máximo de equilibrio", fromString(analysis.max_breakeven_cac, currency)],
          ].map(([label, value]) => (
            <div key={label} className="flex justify-between gap-3 border-b py-1.5 last:border-b-0">
              <dt className="text-muted-foreground">{label}</dt>
              <dd className="font-medium whitespace-nowrap tabular-nums">{value}</dd>
            </div>
          ))}
        </dl>

        <p className="text-[11px] text-muted-foreground">
          El CAC máximo dice <strong>cuánto podríamos permitirnos pagar</strong> por una adquisición,
          no cuánto costará: eso se mide con campañas reales y queda fuera. Una adquisición es un
          pedido —la compra repetida es LTV y no está modelada—.
          {analysis.units_per_order === null &&
            " Y sin unidades por pedido declaradas no hay margen por pedido: un 1 que nadie ha declarado no vale."}
        </p>

        {analysis.fx_conversions && analysis.fx_conversions.length > 0 && (
          <div className="rounded-lg border bg-background/40 px-3 py-2">
            <p className="font-medium">Conversiones aplicadas</p>
            {analysis.fx_conversions.map((fx, index) => (
              <p key={`${fx.pair}-${fx.source_amount}-${index}`} className="text-muted-foreground">
                {fx.source_amount} {fx.source_currency} → {fx.converted_amount} {fx.target_currency}{" "}
                · par {fx.pair} a {fx.rate}
                {fx.direction === "inverted" ? " (invertida)" : ""} · vigente el {fx.effective_date}{" "}
                · {provenanceLabel(fx.provenance)} · {fxSourceLabel(fx.source)}
                {ingestedOn(fx.ingested_at) ? ` · ingerida el ${ingestedOn(fx.ingested_at)}` : ""}
              </p>
            ))}
            {fxNotices(analysis.fx_conversions.map((fx) => fx.source)).map((notice) => (
              <p key={notice.label} className="text-[11px] text-muted-foreground">
                {notice.warning} {notice.attribution}
              </p>
            ))}
          </div>
        )}

        {analysis.data?.supplier_identity && (
          <div className="rounded-lg border bg-background/40 px-3 py-2">
            <p className="font-medium">Proveedor: tres hechos distintos</p>
            <p className="text-muted-foreground">
              Identidad{" "}
              {analysis.data.supplier_identity.identity_verified === null
                ? "sin declarar"
                : analysis.data.supplier_identity.identity_verified
                  ? "verificada por un tercero"
                  : "no verificada por nadie independiente"}{" "}
              · fiabilidad{" "}
              {analysis.data.supplier_identity.commercial_reliability === null
                ? "sin valorar"
                : analysis.data.supplier_identity.commercial_reliability.toLocaleString("es-ES")}{" "}
              · procedencia del precio:{" "}
              {provenanceLabel(analysis.data.supplier_identity.quote_provenance)}.
            </p>
            <p className="text-[11px] text-muted-foreground">
              Ninguno de los tres es un término del margen: un proveedor sin verificar tiene un
              margen igual de calculable.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
