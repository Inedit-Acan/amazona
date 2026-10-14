// La precarga de la misión del Director ejecutivo (M47, Commit 2). Antes vivía dentro de `app/ceo/page.tsx` como
// `buildInitialState`, sin ninguna prueba: la leen seis pantallas que navegan a `/ceo?title=…&…` con lo que ya saben de un
// producto (Investigación, Proveedores, Economía, Legal, Tienda y Marketing).
//
// Dos cambios de comportamiento, deliberados:
//   · un número ilegible (`unit_cost=abc`) ya no llega al backend como `NaN` (que se serializa como `null`): vale el valor de
//     ejemplo, igual que un parámetro ausente;
//   · sin precarga la misión NO empieza con un título inventado («Validate wireless earbuds opportunity»): empieza vacío.
// El contexto de ejemplo (`DEFAULT_CONTEXT`) sigue siendo el de los agentes simulados y el drawer lo rotula así.

/** Lo único que se necesita de `URLSearchParams`/`ReadonlyURLSearchParams`: se puede probar con un objeto cualquiera. */
export interface ParamSource {
  get(name: string): string | null;
}

/** El contexto de ejemplo que reciben los agentes simulados. NO son datos de la empresa. */
export const DEFAULT_CONTEXT = {
  product_validation: { estimated_monthly_searches: 12000, competition_level: "low" },
  supplier_sourcing: { unit_cost: 5.0, lead_time_days: 20, supplier_verified: true },
  finance_validation: { unit_cost: 5.0, sale_price: 20.0, monthly_unit_sales: 300, monthly_fixed_costs: 500.0 },
  legal_validation: { restricted_category: false, requires_certification: false, certification_available: true },
  requests_simulated_spend: true,
  spend_action: "launch_marketing_campaign",
  spend_amount: 150.0,
};

export type MissionContext = typeof DEFAULT_CONTEXT;

export interface MissionInitialState {
  title: string;
  context: MissionContext;
}

/** Un número finito del parámetro, o el valor por defecto si falta o no se lee (`""`, `abc`, `Infinity`). */
function numberParam(params: ParamSource, name: string, fallback: number): number {
  const raw = params.get(name);
  if (raw === null || raw.trim() === "") return fallback;
  const value = Number(raw);
  return Number.isFinite(value) ? value : fallback;
}

/** `"true"` / `"false"`; cualquier otra cosa (o la ausencia) es el valor por defecto. */
function booleanParam(params: ParamSource, name: string, fallback: boolean): boolean {
  const raw = params.get(name);
  if (raw === "true") return true;
  if (raw === "false") return false;
  return fallback;
}

/** ¿Llega una misión precargada desde otra pantalla? Solo cuenta si trae título. */
export function hasHandoff(params: ParamSource): boolean {
  const title = params.get("title");
  return title !== null && title.trim() !== "";
}

/** El estado inicial del formulario: la precarga de otra pantalla (`?title=&product_name=&category=&demand_signal=…`) o,
 * sin ella, un título vacío y el contexto de ejemplo. */
export function buildInitialState(params: ParamSource): MissionInitialState {
  if (!hasHandoff(params)) return { title: "", context: DEFAULT_CONTEXT };

  const d = DEFAULT_CONTEXT;
  const demandSignal = params.get("demand_signal");
  const demand = demandSignal === null || demandSignal.trim() === "" ? Number.NaN : Number(demandSignal);
  const estimatedMonthlySearches = Number.isFinite(demand)
    ? Math.round(demand * 15000)
    : d.product_validation.estimated_monthly_searches;

  return {
    title: params.get("title")!.trim(),
    context: {
      ...d,
      product_validation: {
        estimated_monthly_searches: estimatedMonthlySearches,
        competition_level: params.get("competition_level") || d.product_validation.competition_level,
      },
      supplier_sourcing: {
        unit_cost: numberParam(params, "unit_cost", d.supplier_sourcing.unit_cost),
        lead_time_days: numberParam(params, "lead_time_days", d.supplier_sourcing.lead_time_days),
        supplier_verified: booleanParam(params, "supplier_verified", d.supplier_sourcing.supplier_verified),
      },
      finance_validation: {
        unit_cost: numberParam(params, "unit_cost", d.finance_validation.unit_cost),
        sale_price: numberParam(params, "sale_price", d.finance_validation.sale_price),
        monthly_unit_sales: numberParam(params, "monthly_unit_sales", d.finance_validation.monthly_unit_sales),
        monthly_fixed_costs: numberParam(params, "monthly_fixed_costs", d.finance_validation.monthly_fixed_costs),
      },
      legal_validation: {
        restricted_category: booleanParam(params, "restricted_category", d.legal_validation.restricted_category),
        requires_certification: booleanParam(params, "requires_certification", d.legal_validation.requires_certification),
        certification_available: booleanParam(params, "certification_available", d.legal_validation.certification_available),
      },
      spend_amount: numberParam(params, "spend_amount", d.spend_amount),
    },
  };
}
