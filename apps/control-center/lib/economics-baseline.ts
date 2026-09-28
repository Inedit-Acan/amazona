import type { EconomicAnalysis, SupplierQuoteDetail } from "./api.ts";
import { DEMO_SALE, DEMO_TRANSPORT_SHARE, DEMO_UNIT_COSTS } from "./demo/economics.ts";
import { demoQuotes } from "./demo/sourcing.ts";
import { rankSuppliers } from "./sourcing-view.ts";
import type { CostKey, EconomicsInputs } from "./economics-model.ts";

/** De dónde sale cada coste del desglose (badge de la fila). */
export type CostSource = "verified" | "third_party" | "estimated";

export interface EconomicsBaseline {
  inputs: EconomicsInputs;
  supplier: { name: string; region: string | null; verified: boolean; isDemo: boolean };
  costSources: Record<CostKey, CostSource>;
  /** Supuestos de demostración presentes (para avisarlo en pantalla). */
  demoFields: string[];
}

const round2 = (value: number) => Math.round(value * 100) / 100;

/** Supuestos de partida del panel: cotización y último análisis reales cuando
 * existen; lo que falte, de lib/demo/economics.ts. */
export function buildBaseline(quote: SupplierQuoteDetail | undefined, analysis: EconomicAnalysis | undefined): EconomicsBaseline {
  const demoFields: string[] = [];

  // Sin cotización real, el mismo proveedor de ejemplo que Proveedores recomienda.
  const source = quote ?? rankSuppliers(demoQuotes(analysis?.product_id ?? "demo"))[0].quote;
  // Milestone 39: una cotización real puede no traer precio ni logística. El
  // desglose necesita las dos, así que cuando faltan se usa la cotización de
  // ejemplo entera —y la pantalla lo dice— en vez de rellenar el hueco con un
  // cero que parecería un transporte gratis.
  const complete = source.unit_price !== null && source.logistics_cost_per_unit !== null;
  const fallback = rankSuppliers(demoQuotes(analysis?.product_id ?? "demo"))[0].quote;
  const priced = complete ? source : fallback;
  const unitPrice = priced.unit_price ?? 0;
  const logistics = priced.logistics_cost_per_unit ?? 0;
  if (!quote) demoFields.push("proveedor y su cotización");
  else if (!complete) demoFields.push("precio o coste logístico (la cotización real no los declara)");

  const baseOrders = analysis?.data?.scenarios?.base?.monthly_unit_sales;
  if (!analysis) demoFields.push("precio de venta y costes fijos");
  if (baseOrders === undefined) demoFields.push("pedidos mensuales");
  demoFields.push("arancel, fulfillment, pasarela, devoluciones, CAC, otros costes y conversión");

  const transport = round2(logistics * DEMO_TRANSPORT_SHARE);
  return {
    inputs: {
      salePrice: analysis ? analysis.sale_price : DEMO_SALE.salePrice,
      supplierCost: unitPrice,
      transport,
      tariff: round2(logistics - transport),
      ...DEMO_UNIT_COSTS,
      monthlyOrders: baseOrders !== undefined ? Math.round(baseOrders) : DEMO_SALE.monthlyOrders,
      monthlyFixedCosts: analysis ? analysis.monthly_fixed_costs : DEMO_SALE.monthlyFixedCosts,
      // Capital del primer pedido de stock (o el MOQ, si es mayor).
      initialInvestment: round2(Math.max(priced.moq ?? DEMO_SALE.firstOrderUnits, DEMO_SALE.firstOrderUnits) * (unitPrice + logistics)),
    },
    supplier: {
      name: source.supplier?.name ?? source.data?.name ?? source.supplier_id,
      region: source.supplier?.region ?? source.data?.region ?? null,
      // Verificado significa verificado por un tercero independiente
      // (Milestone 39). Que lo diga el propio proveedor ya no cuenta.
      verified: source.supplier?.verification === "third_party_verified",
      isDemo: !quote || !complete,
    },
    costSources: {
      supplier: source.supplier?.verification === "third_party_verified" ? "verified" : "third_party",
      transport: "third_party",
      tariff: "estimated",
      fulfillment: "estimated",
      payment: "estimated",
      returns: "estimated",
      cac: "estimated",
      other: "estimated",
    },
    demoFields,
  };
}
