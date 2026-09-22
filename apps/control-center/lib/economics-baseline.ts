import type { EconomicAnalysis, SupplierQuote } from "./api.ts";
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
export function buildBaseline(quote: SupplierQuote | undefined, analysis: EconomicAnalysis | undefined): EconomicsBaseline {
  const demoFields: string[] = [];

  // Sin cotización real, el mismo proveedor de ejemplo que Proveedores recomienda.
  const source = quote ?? rankSuppliers(demoQuotes(analysis?.product_id ?? "demo"))[0].quote;
  const unitPrice = source.unit_price;
  const logistics = source.logistics_cost_per_unit;
  if (!quote) demoFields.push("proveedor y su cotización");

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
      initialInvestment: round2(Math.max(source.moq, DEMO_SALE.firstOrderUnits) * (unitPrice + logistics)),
    },
    supplier: {
      name: source.data?.name ?? source.supplier_id,
      region: source.data?.region ?? null,
      verified: quote ? quote.verified : false,
      isDemo: !quote,
    },
    costSources: {
      supplier: quote?.verified ? "verified" : "third_party",
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
