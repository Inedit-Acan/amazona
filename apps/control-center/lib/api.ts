import { withIdempotencyKey } from "@/lib/idempotency";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** Mensaje legible del backend: FastAPI responde `{"detail": "..."}`; si el
   * cuerpo no es ese JSON se devuelve tal cual. */
  get detail(): string {
    try {
      const body: unknown = JSON.parse(this.message);
      if (body && typeof body === "object" && "detail" in body && typeof body.detail === "string") {
        return body.detail;
      }
    } catch {
      // cuerpo no JSON: se usa el texto original
    }
    return this.message;
  }
}

type TokenResolver = () => Promise<string | null>;

/** De dónde sale el token de acceso. Por defecto, de la sesión del navegador.
 *
 * `lib/api-server.ts` lo sustituye por la lectura de las cookies de la
 * petición. Es una inyección y no un `import()` condicional a propósito: este
 * módulo lo importan también componentes de cliente, y cualquier referencia a
 * `next/headers` desde aquí —aunque estuviera tras un `typeof window`— entraría
 * en el bundle del navegador y rompería el build (Milestone 29.1). */
let resolveAccessToken: TokenResolver = async () => {
  if (typeof window === "undefined") return null;
  const { getAccessToken } = await import("@/lib/auth");
  return getAccessToken();
};

export function setAccessTokenResolver(resolver: TokenResolver): void {
  resolveAccessToken = resolver;
}

async function authHeader(): Promise<Record<string, string>> {
  const token = await resolveAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(await authHeader()),
      ...withIdempotencyKey(init),
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });

  if (!response.ok) {
    const body = await response.text();
    throw new ApiError(body || response.statusText, response.status);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export type ProjectStatus =
  | "DRAFT"
  | "VALIDATING"
  | "APPROVED"
  | "EXECUTING"
  | "MONITORING"
  | "PAUSED"
  | "COMPLETED"
  | "REJECTED"
  | "FAILED";

export type TaskStatus =
  | "PENDING"
  | "QUEUED"
  | "RUNNING"
  | "WAITING"
  | "WAITING_APPROVAL"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED"
  | "BLOCKED";

export type DecisionStatus = "GO" | "REVIEW" | "NO_GO" | "HUMAN_APPROVAL";
export type ApprovalStatus = "PENDING" | "APPROVED" | "REJECTED" | "EXPIRED" | "CANCELLED";

export interface Objective {
  id: string;
  title: string;
  description: string | null;
  created_by: string;
  status: string;
  context: Record<string, unknown> | null;
}

/** Otro nombre con el que llegó un producto (Milestone 36). */
export interface ProductAlias {
  alias: string;
  /** `normalised` si bastó la normalización, `alias:<versión>` si hizo falta el
   * catálogo escrito a mano. Nunca por parecido: eso no existe. */
  method: string;
}

export interface Product {
  id: string;
  name: string;
  category: string;
  status: string;
  created_by: string;
  source: string;
  /** Quién es este producto, independientemente de cómo se escribiera su nombre.
   * Nulo en las filas anteriores al Milestone 36 que nadie ha reinvestigado. */
  identity_key?: string | null;
  /** Los nombres distintos que se resolvieron a este producto. Vacío cuando
   * siempre llegó igual: no hubo nada que resolver. */
  also_known_as?: ProductAlias[];
}

export interface Project {
  id: string;
  objective_id: string;
  name: string;
  status: ProjectStatus;
}

export interface Task {
  id: string;
  project_id: string;
  name: string;
  capability: string;
  status: TaskStatus;
  input: Record<string, unknown> | null;
  output: Record<string, unknown> | null;
  error: string | null;
}

export interface Agent {
  id: string;
  name: string;
  role: string;
  capabilities: string[];
  status: string;
  reliability_score: number;
  version: string;
  cost_profile: Record<string, unknown>;
}

export interface DecisionEvidence {
  source: string;
  summary: string;
  data: Record<string, unknown> | null;
}

export interface Decision {
  id: string;
  project_id: string;
  status: DecisionStatus;
  opportunity_score: number | null;
  confidence: number | null;
  rationale: string | null;
  correlation_id: string;
  evidence: DecisionEvidence[];
}

export interface RunResult {
  id: string;
  project_id: string;
  status: DecisionStatus;
  opportunity_score: number | null;
  confidence: number | null;
  rationale: string | null;
  correlation_id: string;
}

export interface Approval {
  id: string;
  decision_id: string;
  action: string;
  amount: number | null;
  status: ApprovalStatus;
  expires_at: string | null;
  resolved_at: string | null;
  resolved_by: string | null;
}

export interface AuditEntry {
  id: string;
  actor: string;
  action: string;
  resource: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  correlation_id: string;
  created_at: string;
}

export interface AgentExecution {
  id: string;
  agent_id: string;
  capability: string;
  duration_ms: number;
  success: boolean;
  correlation_id: string;
  created_at: string;
}

/** De dónde salen los datos de un dominio externo (Milestone 30). `mock` son
 * fixtures deterministas: nunca base de una decisión operativa. */
export type ProviderKind = "mock" | "sandbox" | "real";

export interface ProviderBinding {
  domain: string;
  kind: ProviderKind;
  name: string;
  simulated: boolean;
  /** Las fuentes reales activas, en orden, cuando hay más de una (Milestone 37).
   * Vacío o ausente cuando el nombre ya lo dice todo. */
  sources?: string[];
}

/** Observado, modelado o inventado (Milestone 37, ADR 0015). */
export type SignalBasis = "measured" | "estimated" | "simulated";

/** Los cuatro tipos estructurales de canal (Milestone 38, ADR 0016). Cerrados
 * porque son conceptos; las plataformas concretas son valores dentro de
 * `marketplace`, `search` y `social`. */
export type ChannelKind = "own_web" | "marketplace" | "search" | "social";

/** Lo consumido hoy con un proveedor externo, y contra qué se compara
 * (Milestone 37, plan maestro §25). */
export interface ApiProviderUsage {
  provider: string;
  /** `free` o `paid`. No es lo mismo «no cuesta» que «no tiene límite». */
  pricing: "free" | "paid";
  /** Qué se cuenta: peticiones, tokens, créditos. */
  unit: string;
  units_today: number;
  denied_today: number;
  last_denied_reason: string | null;
  estimated_cost_today: number;
  /** Lo que el proveedor ha cobrado de verdad. **Nulo no es cero**: es que
   * todavía no lo ha dicho. */
  actual_cost_today: number | null;
  currency: string;
  quota_units_per_day: number | null;
  max_units_per_run: number | null;
  /** Nulo = sin autorización. Y sin autorización un proveedor de pago no se
   * llama. */
  authorised_cost_per_day: number | null;
  authorised_cost_per_run: number | null;
  source: string;
}

export interface DetailedHealth {
  database: "ok" | "error";
  migration: string | null;
  supabase_configured: boolean;
  /** Ausentes cuando la base de datos no responde, y en backends anteriores al
   * Milestone 30. */
  environment?: string;
  providers?: ProviderBinding[];
}

/** Runtime de trabajos (Milestone 31). */
export type JobStatus =
  | "PENDING"
  | "QUEUED"
  | "RUNNING"
  | "RETRYING"
  | "WAITING_APPROVAL"
  | "BLOCKED"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED";

export interface Job {
  id: string;
  type: string;
  status: JobStatus;
  payload: Record<string, unknown>;
  correlation_id: string;
  attempt: number;
  max_attempts: number;
  available_at: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  failed_at: string | null;
  cancelled_at: string | null;
  error: string | null;
  result_reference: string | null;
  created_by: string | null;
}

export type IncidentSeverity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type IncidentStatus = "OPEN" | "RESOLVED";

export interface Incident {
  id: string;
  title: string;
  description: string | null;
  severity: IncidentSeverity;
  status: IncidentStatus;
  resolved_at: string | null;
  created_at: string;
}

export interface ResearchCandidate {
  product_id: string;
  name: string;
  category: string;
  opportunity_score: number | null;
  confidence: number | null;
  data: {
    demand_signal?: number;
    competition_level?: string;
    /** Radar axes added Milestone 26 — absent on analyses persisted before it. */
    future_outlook_signal?: number;
    regulatory_risk_signal?: number;
    scalability_signal?: number;
    niche_rationale?: string;
    /** Proveedores cuya señal existe y cuya licencia no permite puntuar con
     * ella (Milestone 37, ADR 0015). Un score ausente sin explicación es
     * indistinguible de una avería. */
    scoring_withheld_from?: string[];
    /** Para qué canal se puntuó. `null` = agnóstico (Milestone 38, ADR 0016). */
    channel?: string | null;
    /** Canales cuya señal existe y no sirve para **este** canal. Se arregla
     * consiguiendo una fuente del canal que falta, no leyendo un contrato. */
    scoring_wrong_channel?: string[];
    /** Nombres que una fuente declara equivalentes a este candidato. */
    declared_aliases?: { name: string; method: string }[];
    /** De qué está hecho el score (Milestone 34): `real` si todo lo que cuenta
     * está medido, `estimated` si alguna pieza está modelada en vez de
     * observada, `simulated` si nada viene del mundo, `mixed` si se mezcla con
     * fixtures.
     * Ausente en análisis guardados antes del Milestone 34, que eran fixtures. */
    provenance?: "real" | "estimated" | "mixed" | "simulated" | "unknown";
    market?: string;
    /** Las señales con su procedencia, y la evidencia mensual de cada una
     * cuando la fuente la da (Milestone 35). */
    signals?: ResearchSignal[];
    [key: string]: unknown;
  };
}

export interface ResearchSignal {
  kind: string;
  value: number;
  confidence: number;
  provider: string;
  source: string;
  query: string;
  market: string;
  observed_at: string;
  method: string;
  raw_reference: string | null;
  /** De qué está hecho el número (Milestone 37): `measured` si la fuente lo
   * observó, `estimated` si lo modeló, `simulated` si es un fixture. Sustituye al
   * booleano `simulated`, que juntaba los dos primeros. */
  basis: SignalBasis;
  /** Dónde se midió (Milestone 38). Una clave declarada: `own_web`,
   * `marketplace:amazon`, `search:google`…
   *
   * **Nulo significa agnóstica del canal, no «válida para todos»**: el interés por
   * un tipo de producto no depende de dónde se venda; la competencia sí. */
  channel?: string | null;
  /** Las medidas que componen el valor. Vacío no es cero: es que esta señal no
   * viene de una serie. */
  observations?: { period: string; value: number }[];
}

export interface ResearchRun {
  correlation_id: string;
  candidates: ResearchCandidate[];
}

/** Qué dice cada proveedor sobre la misma pregunta (Milestone 35). */
export interface ResearchComparison {
  id: string;
  category: string;
  market: string;
  baseline_provider: string;
  candidate_provider: string;
  summary: {
    category: string;
    market: string;
    baseline: ComparisonProviderSummary;
    candidate: ComparisonProviderSummary;
    shared: string[];
    only_baseline: string[];
    only_candidate: string[];
    deltas: { candidate: string; kind: string; baseline_value: number; candidate_value: number; difference: number }[];
    verdict: string;
  };
  correlation_id: string;
  created_at: string;
}

export interface ComparisonProviderSummary {
  provider: string;
  candidates: number;
  coverage: Record<string, number>;
  scorable: number;
  mean_confidence: number | null;
  measured_signals: number;
  /** Milestone 37: antes una estimación caía del lado de «medida», que es justo
   * lo que no es. */
  estimated_signals?: number;
  simulated_signals: number;
  /** En qué canales midió algo (Milestone 38). Vacío = todo agnóstico del canal,
   * lo cual es correcto para una medida de interés y sospechoso para una de
   * competencia. */
  channels?: string[];
}

/** Quién sostiene un hecho sobre un proveedor (Milestone 39, ADR 0017).
 *
 * `unknown` NO es un valor que el backend guarde: es lo que contesta cuando
 * nadie ha declarado nada. Un hecho ausente se queda ausente. */
export type SupplierProvenance =
  | "third_party_verified"
  | "supplier_claim"
  /** Lo afirma el operador: el precio de venta, los costes fijos, el cambio que
   * aplicó el banco. No lo dice el proveedor ni lo calcula un modelo
   * (Milestone 40). */
  | "declared"
  | "amazona_estimate"
  | "simulated"
  | "unknown";

/** Las ocho capacidades del plan maestro §16. Conjunto cerrado. */
export type SupplyCapability =
  | "direct_shipping"
  | "dropshipping"
  | "blind_shipping"
  | "custom_packaging"
  | "tracking"
  | "returns"
  | "eu_return_address"
  | "sla";

export interface SupplierCapabilityAnswer {
  capability: SupplyCapability;
  /** `null` significa **no declarado**, nunca «no lo soporta». */
  supported: boolean | null;
  provenance: SupplierProvenance;
  source: string | null;
  note: string | null;
  observed_at: string | null;
  /** Si la respuesta es una declaración específica de este producto. */
  product_specific: boolean;
}

/** Una de las ocho dimensiones de riesgo del plan maestro §11. */
export type RiskDimension =
  | "identity"
  | "financial"
  | "quality"
  | "delivery"
  | "legal"
  | "fraud"
  | "dependency"
  | "geopolitical_logistics";

export type RiskLevel = "low" | "medium" | "high" | "unknown";

export interface SupplierRiskAssessment {
  dimension: RiskDimension;
  level: RiskLevel;
  rationale: string;
  provenance: SupplierProvenance;
  basis: string[];
}

export interface Supplier {
  id: string;
  name: string;
  identity_key: string | null;
  identity_method: string | null;
  region: string | null;
  country: string | null;
  city: string | null;
  website: string | null;
  /** `null` = nadie ha dicho de dónde sale esta ficha. No es «no verificado». */
  verification: SupplierProvenance | null;
  verified_by: string | null;
  /** `null` = nadie la ha valorado. **No es cero.** */
  reliability_score: number | null;
  reliability_provenance: SupplierProvenance | null;
  last_checked_at: string | null;
}

/** Una cotización. Desde el Milestone 39 casi todo puede faltar: lo que el
 * proveedor no ha dicho se queda sin decir, y `null` no es cero. */
export interface SupplierQuote {
  id: string;
  product_id: string;
  supplier_id: string;
  unit_price: number | null;
  /** ISO 4217. Sin moneda el precio no se compara con ningún otro. */
  currency: string | null;
  quoted_unit: string | null;
  quoted_quantity: number | null;
  moq: number | null;
  /** Días de preparación, sin el transporte. */
  lead_time_days: number | null;
  transit_days: number | null;
  transport_mode: string | null;
  /** Incoterms 2020: hasta dónde llega el precio. */
  incoterm: string | null;
  payment_terms: string | null;
  destination_market: string | null;
  valid_from: string | null;
  valid_until: string | null;
  provenance: SupplierProvenance | null;
  source: string | null;
  logistics_cost_per_unit: number | null;
  logistics_provenance: SupplierProvenance | null;
  total_landed_cost_per_unit: number | null;
  data: {
    name?: string;
    region?: string;
    notes?: string;
    [key: string]: unknown;
  } | null;
}

/** La cotización con lo que hace falta para decidir. Un precio sin saber si el
 * proveedor acepta devoluciones en la UE es la mitad de la información. */
export interface SupplierQuoteDetail extends SupplierQuote {
  supplier: Supplier | null;
  /** Siempre las ocho, declaradas o no. */
  capabilities: SupplierCapabilityAnswer[];
  /** Las críticas para el modelo sin stock (§16) que siguen sin respuesta.
   * Vacío no significa «compatible»: significa que ya no faltan respuestas. */
  unanswered_capabilities: SupplyCapability[];
  /** Las ocho dimensiones de §11. No hay puntuación total y no es un olvido. */
  risk: SupplierRiskAssessment[];
}

export interface SourcingRun {
  correlation_id: string;
  quotes: SupplierQuote[];
}

export interface EconomicScenario {
  monthly_unit_sales: number;
  margin_percent: number;
  monthly_revenue: number;
  monthly_profit: number;
}

/** Si una cifra se pudo calcular (Milestone 40).
 *
 * **No es un resultado económico.** Un margen negativo se sabe y es malo;
 * `not_evaluable` es que no se sabe. Confundirlos descartaría productos buenos
 * por falta de un dato administrativo. */
export type Evaluability = "evaluable" | "not_evaluable";

/** Los seis componentes de la economía unitaria. */
export type CostConcept =
  | "product"
  | "logistics"
  | "import"
  | "channel"
  | "payment"
  | "other_variable";

/** Las cinco situaciones en que puede estar un coste. Las cuatro últimas suman
 * cero euros y significan cuatro cosas distintas. */
export type CostStatus =
  | "known"
  | "included_in_another"
  | "not_applicable"
  | "unknown_required"
  | "unknown_optional";

/** Un importe exacto. Viaja como **cadena** a propósito: en JavaScript un
 * número es un `float64`, y mandar `6.4` devolvería el error de redondeo que el
 * backend acaba de quitar. */
export interface MoneyAmount {
  amount: string;
  currency: string;
}

export interface CostComponentView {
  concept: CostConcept;
  status: CostStatus;
  /** Solo cuando `known`. */
  amount: MoneyAmount | null;
  provenance: SupplierProvenance;
  source: string | null;
  /** Solo cuando `included_in_another`: dentro de cuál está. */
  included_in: CostConcept | null;
  /** Solo cuando `not_applicable`: por qué no aplica. */
  reason: string | null;
}

/** La cadena unidad → pedido → adquisición, y de qué está hecha. */
export interface UnitEconomicsView {
  currency: string;
  contribution_margin_per_unit: MoneyAmount | null;
  contribution_margin_percent: string | null;
  contribution_margin_per_order: MoneyAmount | null;
  breakeven_cac_before_fixed_costs: MoneyAmount | null;
  allocated_fixed_cost_per_order: MoneyAmount | null;
  max_breakeven_cac: MoneyAmount | null;
  margin_evaluability: Evaluability;
  cac_evaluability: Evaluability;
  missing_inputs: string[];
  omitted_costs: string[];
  /** La procedencia más floja de lo que se sumó. Un suelo, no una nota: un
   * margen no vale más que el más flojo de sus sumandos. */
  weakest_provenance: SupplierProvenance;
  orders_per_acquisition: string;
  components: CostComponentView[];
}

/** La conversión aplicada, con los diez campos que la hacen auditable. */
export interface FxConversionView {
  source_currency: string;
  source_amount: string;
  target_currency: string;
  converted_amount: string;
  rate: string;
  /** El par tal y como se declaró la tasa: `USD/EUR` es cuántos EUR vale 1 USD. */
  pair: string;
  direction: "direct" | "inverted";
  effective_date: string;
  source: string;
  provenance: SupplierProvenance;
  /** Cuándo entró la tasa en nuestra base (Milestone 42). Ausente en conversiones anteriores. */
  ingested_at?: string | null;
}

/** Identidad, fiabilidad comercial y procedencia de la cotización: tres hechos
 * distintos, y **ninguno es un término del margen**. */
export interface SupplierIdentityView {
  /** `null` = nadie lo ha dicho. No es `false`. */
  identity_verified: boolean | null;
  identity_provenance: SupplierProvenance;
  commercial_reliability: number | null;
  commercial_reliability_provenance: SupplierProvenance;
  quote_provenance: SupplierProvenance;
  note: string;
}

export interface EconomicAnalysis {
  correlation_id: string;
  product_id: string;
  supplier_quote_id: string;
  sale_price: number;
  monthly_fixed_costs: number;
  /** `null` cuando el análisis no se pudo evaluar. **No es cero.** */
  margin_percent: number | null;
  recommendation: "GO" | "REVIEW" | "NO_GO";
  confidence: number;
  /** Dónde se vende. Del catálogo de canales del Milestone 38. */
  channel: string | null;
  currency: string | null;
  /** Cuántas unidades lleva un pedido. `null` = **no declarado**, y entonces no
   * hay margen por pedido ni techo de CAC. */
  units_per_order: number | null;
  units_per_order_provenance: SupplierProvenance | null;
  margin_evaluability: Evaluability;
  cac_evaluability: Evaluability;
  /** Qué faltó, por su nombre. */
  missing_inputs: string[] | null;
  contribution_margin_per_unit: string | null;
  contribution_margin_per_order: string | null;
  allocated_fixed_cost_per_order: string | null;
  /** Lo que **podríamos permitirnos** pagar por una adquisición. No dice lo que
   * costará: eso es CAC medido y queda fuera del Milestone 40. */
  max_breakeven_cac: string | null;
  /** **Una lista**: el precio y el coste logístico se convierten por separado,
   * y guardar solo la última dejaría la otra sin rastro. */
  fx_conversions: FxConversionView[] | null;
  data: {
    scenarios?: Record<"conservative" | "base" | "optimistic", EconomicScenario>;
    risks?: string[];
    evidence?: string[];
    unit_economics?: UnitEconomicsView;
    supplier_identity?: SupplierIdentityView;
    [key: string]: unknown;
  } | null;
}

/** Un tipo de cambio declarado: `1 base_currency = rate quote_currency`. */
export interface ExchangeRate {
  id: string;
  base_currency: string;
  quote_currency: string;
  rate: string;
  effective_date: string;
  source: string;
  provenance: SupplierProvenance;
  declared_by: string | null;
  note: string | null;
  /** Cuándo entró la tasa en nuestra base (Milestone 42). No es la fecha efectiva. */
  ingested_at?: string;
  /** Solo en referencias del BCE: la atribución que su licencia exige. */
  attribution?: string | null;
  /** Solo en referencias del BCE: lo que la tasa no es. */
  notice?: string | null;
}

export interface EconomicsTimeseriesPoint {
  day: string;
  analyses_count: number;
  avg_margin_percent: number;
  avg_sale_price: number;
}

export interface RegulatoryChange {
  date: string;
  description: string;
}

export interface LegalAnalysis {
  correlation_id: string;
  product_id: string;
  supplier_quote_id: string | null;
  market: string;
  restricted: boolean | null;
  recommendation: "GO" | "REVIEW" | "NO_GO";
  confidence: number;
  data: {
    required_certifications?: string[];
    known_risks?: string[];
    recent_changes?: RegulatoryChange[];
    terms_and_conditions?: string;
    risks?: string[];
    evidence?: string[];
    /** Solo en el análisis real (Milestone 41). Ausente en el simulado. */
    legal_status?: LegalStatus;
    reasons?: string[];
    requirements?: LegalRequirementResult[];
    disclaimer?: string;
    confidence_rule?: string;
    source_errors?: Record<string, string>;
    certification_flag_ignored?: boolean;
    [key: string]: unknown;
  } | null;
}

/** Los cuatro estados cerrados de Legal (Milestone 41, ADR 0019). `PASS` significa
 * únicamente: dentro del alcance y de los requisitos declarados y comprobados,
 * Legal no ha encontrado un bloqueo. Nunca «producto legal». */
export type LegalStatus = "PASS" | "REVIEW_REQUIRED" | "BLOCKED" | "UNKNOWN";

/** Lo que la fuente dijo de una norma. Independiente de si se aplica. */
export type ExistenceState =
  | "verified_in_force"
  | "verified_not_in_force"
  | "not_found"
  | "source_inconsistent"
  | "unverified"
  | "stale"
  | "never_checked";

export type ComplianceState = "none" | "declared" | "third_party_verified" | "expired";

export interface RegulatoryAnchor {
  celex: string;
  provider: string;
  provenance: string;
  verified_at: string;
  recheck_after: string;
  found: boolean;
  in_force: boolean | null;
  act_type: string;
  act_type_code: string | null;
  eli: string | null;
  document_date: string | null;
  source_effective_from: string[] | null;
  source_effective_to: string | null;
  source_url: string;
}

/** Lo que el BOE dijo de una norma nacional, tal como lo entregó (Milestone 43, ADR 0021).
 * **Informativo**: la consolidación y el análisis no tienen valor oficial. */
export interface NationalAnchor {
  national_id: string;
  provider: string;
  provenance: string;
  verified_at: string;
  recheck_after: string;
  consolidated: boolean;
  informational: boolean;
  notice: string;
  attribution: string;
  /** Metadatos verbatim: fechas como cadena `AAAAMMDD`, banderas `S`/`N`. */
  source_metadata: Record<string, unknown> | null;
  source_updated_at: string | null;
  relations: { previous?: NationalRelation[]; next?: NationalRelation[] } | null;
  publication_state: PublicationState;
  publication_detail: string | null;
  publication_url: string | null;
  source_urls: string[] | null;
}

export interface NationalRelation {
  id_norma: string;
  relation_code: number | null;
  relation: string;
  text: string;
}

/** `absent_from_summary` es la única respuesta negativa; `check_failed` no es una conclusión. */
export type PublicationState = "confirmed" | "absent_from_summary" | "check_failed" | "not_checked";

export type NationalState =
  | "verified_in_force"
  | "not_in_force"
  | "not_consolidated"
  | "outdated_consolidation"
  | "unverified"
  | "relation_flagged"
  | "publication_inconsistent"
  | "stale"
  | "never_checked";

export type Corroboration = "corroborated" | "partial" | "uncorroborated" | "not_assessable";

export interface NationalAssessment {
  state: NationalState;
  corroboration: Corroboration;
  corroboration_reason: string;
  ok: boolean;
  reasons: string[];
  matching_relations: NationalRelation[];
  flagged_relations: NationalRelation[];
}

/** Una norma nacional que una persona declara como transposición. El sistema no la propone. */
export interface NationalTransposition {
  id: string;
  requirement_id: string;
  national_id: string;
  provenance: SupplierProvenance;
  declared_by: string;
  note: string | null;
  created_at: string;
  official_url: string;
  notice: string;
  attribution: string;
  anchor: NationalAnchor | null;
  assessment: NationalAssessment | null;
}

export interface RegulatoryRequirement {
  id: string;
  product_scope: string;
  jurisdiction: string;
  celex: string;
  regulation: string;
  reference: string | null;
  requirement: string;
  kind: "obligation" | "restriction";
  applicability_provenance: SupplierProvenance;
  applicability_source: string | null;
  declared_by: string;
  transposition_reference: string | null;
  transposition_provenance: SupplierProvenance | null;
  transposition_source: string | null;
  note: string | null;
  created_at: string;
  anchor: RegulatoryAnchor | null;
  existence: ExistenceState;
  national_transpositions: NationalTransposition[];
}

export interface ComplianceEvidence {
  id: string;
  product_id: string;
  requirement_id: string;
  provenance: SupplierProvenance;
  source: string | null;
  reference: string | null;
  valid_until: string | null;
  declared_by: string;
  note: string | null;
  created_at: string;
}

/** Un requisito evaluado por Legal, con las tres cuestiones **separadas**. */
export interface LegalRequirementResult {
  requirement_id: string;
  celex: string;
  regulation: string;
  reference: string | null;
  requirement: string;
  kind: "obligation" | "restriction";
  status: LegalStatus;
  reasons: string[];
  confidence: number;
  weakest_link: SupplierProvenance;
  applicability: { provenance: SupplierProvenance; source: string | null; declared_by: string };
  existence: {
    state: ExistenceState;
    provider: string | null;
    verified_at: string | null;
    recheck_after: string | null;
    in_force: boolean | null;
    act_type: string | null;
    eli: string | null;
    source_effective_from: string[];
    source_effective_to: string | null;
  };
  compliance: { state: ComplianceState };
  transposition: { reference: string | null; provenance: SupplierProvenance | null };
}

export interface LandingPageCopy {
  headline: string;
  subheadline: string;
  price_display: string;
  bullets: string[];
  cta: string;
}

export interface PaymentGatewayPlan {
  gateway: string;
  mode: string;
  checklist: string[];
  requires_human_approval: boolean;
}

export interface CatalogEntry {
  sku: string;
  price: number | null;
  category: string;
  market: string;
  restricted: boolean | null;
  lead_time_days: number | null;
}

export interface Storefront {
  correlation_id: string;
  product_id: string;
  market: string;
  store_slug: string;
  launch_status: "READY" | "NEEDS_REVIEW" | "BLOCKED";
  recommendation: "GO" | "REVIEW" | "NO_GO";
  confidence: number;
  data: {
    landing_page_copy?: LandingPageCopy;
    payment_gateway_plan?: PaymentGatewayPlan;
    catalog_entry?: CatalogEntry;
    conversion_tips?: string[];
    risks?: string[];
    evidence?: string[];
    [key: string]: unknown;
  } | null;
}

export interface ListingContent {
  title: string;
  bullet_points: string[];
  backend_keywords: string[];
}

export interface CompetitionAnalysis {
  competitor_count: number;
  avg_price: number;
  avg_rating: number;
  buy_box_difficulty: string;
  data_origin: string;
}

export interface CommissionBreakdown {
  referral_fee_percent: number;
  fulfillment_fee_per_unit: number;
  net_margin_per_unit: number | null;
}

export interface InventoryPolicy {
  tracking_enabled: boolean;
  fulfillment_method: string;
}

export interface MarketplaceListing {
  correlation_id: string;
  product_id: string;
  storefront_id: string | null;
  market: string;
  platform: string;
  listing_status: "READY" | "NEEDS_REVIEW" | "BLOCKED";
  recommendation: "GO" | "REVIEW" | "NO_GO";
  confidence: number;
  data: {
    listing_content?: ListingContent;
    competition_analysis?: CompetitionAnalysis;
    commission_breakdown?: CommissionBreakdown;
    inventory_policy?: InventoryPolicy;
    risks?: string[];
    evidence?: string[];
    [key: string]: unknown;
  } | null;
}

export interface AudienceSegment {
  name: string;
  age_range: string;
  interests: string[];
  estimated_reach: number;
}

export interface AdCreative {
  headline: string;
  primary_text: string;
  cta: string;
  image_brief: string;
}

export interface PerformanceEstimate {
  avg_cpc: number;
  avg_ctr: number;
  conversion_rate: number;
  data_origin: string;
  projected_roas: number | null;
}

export interface MarketingCampaign {
  correlation_id: string;
  product_id: string;
  marketplace_listing_id: string | null;
  market: string;
  platform: string;
  daily_budget: number;
  campaign_status: "READY" | "NEEDS_REVIEW" | "BLOCKED";
  recommendation: "GO" | "REVIEW" | "NO_GO";
  confidence: number;
  data: {
    audience_segments?: AudienceSegment[];
    ad_creative?: AdCreative;
    performance_estimate?: PerformanceEstimate;
    budget_recommendation?: string;
    risks?: string[];
    evidence?: string[];
    [key: string]: unknown;
  } | null;
}

export interface TrackingStage {
  stage: string;
  day_offset: number;
}

export interface OrderTracking {
  stages: TrackingStage[];
  lead_time_days_used: number;
}

export interface SimulatedOrder {
  order_id: string;
  quantity: number;
  tracking: OrderTracking;
}

export interface SupplierCoordination {
  lead_time_days: number | null;
  supplier_verified: boolean | null;
}

export interface ReturnPolicy {
  eligibility_window_days: number;
  restocking_fee_percent: number;
  refund_estimate: number | null;
}

export interface SupportTicketExample {
  ticket_type: string;
  ai_resolvable: boolean;
  escalation_reason: string | null;
}

export interface OperationsRecord {
  correlation_id: string;
  product_id: string;
  marketing_campaign_id: string | null;
  market: string;
  operations_status: "READY" | "NEEDS_REVIEW" | "BLOCKED";
  recommendation: "GO" | "REVIEW" | "NO_GO";
  confidence: number;
  data: {
    order?: SimulatedOrder;
    supplier_coordination?: SupplierCoordination;
    return_policy?: ReturnPolicy;
    support_ticket_example?: SupportTicketExample;
    risks?: string[];
    evidence?: string[];
    [key: string]: unknown;
  } | null;
}

export interface CFOReport {
  correlation_id: string;
  financial_health_status: "HEALTHY" | "AT_RISK" | "CRITICAL" | "NEEDS_REVIEW";
  recommendation: "GO" | "REVIEW" | "NO_GO";
  confidence: number;
  data: {
    no_go_ratio: number | null;
    budget_utilization: number | null;
    total_products_analyzed: number;
    go_count: number;
    review_count: number;
    no_go_count: number;
    total_campaigns: number;
    active_campaigns: number;
    total_daily_budget: number;
    total_budget_hard_limit: number;
    total_reserved: number;
    total_committed: number;
    total_spent: number;
    risks?: string[];
    evidence?: string[];
    [key: string]: unknown;
  } | null;
}

export interface PipelineStep {
  correlation_id: string | null;
  entity_id?: string;
  /** Estado de NEGOCIO del paso (el listing quedó BLOCKED, el CFO CRITICAL). */
  status?: string;
  recommendation?: string;
  candidate_count?: number;
  /** Estado de EJECUCIÓN del paso (Milestone 32). Distinto de `status`: un paso
   * puede estar COMPLETED y su resultado de negocio ser BLOCKED. */
  step_status: PipelineStepStatus;
  attempt: number;
  error?: string;
}

export type PipelineStepStatus =
  | "PENDING"
  | "RUNNING"
  | "COMPLETED"
  | "FAILED"
  | "SKIPPED"
  | "CANCELLED"
  /** El ActionGate no dejó ejecutarlo (Milestone 33). No es un fallo. */
  | "DENIED"
  /** El ActionGate pide una decisión humana antes de ejecutarlo. */
  | "WAITING_APPROVAL";

/** Estados de una ejecución (Milestone 32). QUEUED/RUNNING son del proceso;
 * PARTIAL es un resultado de negocio y FAILED un fallo técnico reintentable. */
export type PipelineRunStatus =
  | "QUEUED"
  | "RUNNING"
  | "COMPLETED"
  | "PARTIAL"
  | "FAILED"
  | "BLOCKED"
  | "CANCELLED"
  /** Parada delante de una acción con efecto que nadie ha autorizado
   * todavía (Milestone 33). */
  | "WAITING_APPROVAL";

export interface PipelineRun {
  correlation_id: string;
  product_id: string | null;
  category: string;
  market: string;
  status: PipelineRunStatus;
  failed_step: string | null;
  needs_review: boolean;
  steps: Record<string, PipelineStep>;
  /** El trabajo del runtime que la ejecuta (Milestone 32). */
  job_id: string | null;
}

/** Qué clase de decisión se pide (Milestone 33): mirar lo que ya pasó, o
 * autorizar lo que todavía no ha pasado. */
export type PipelineReviewKind = "POST_HOC" | "ACTION_GATE";

export interface PipelineReview {
  id: string;
  pipeline_run_id: string;
  kind: PipelineReviewKind;
  /** Paso y acción con efecto, solo en las de tipo ACTION_GATE. */
  step: string | null;
  action: string | null;
  reasons: string[];
  status: "PENDING" | "APPROVED" | "REJECTED";
  resolved_at: string | null;
  resolved_by: string | null;
  correlation_id: string;
}

export interface PipelineKillSwitchState {
  enabled: boolean;
  reason: string | null;
  updated_by: string | null;
}

export const api = {
  createObjective: (payload: { title: string; description?: string; created_by: string; context?: unknown }) =>
    request<Objective>("/api/objectives", { method: "POST", body: JSON.stringify(payload) }),
  runObjective: (objectiveId: string) =>
    request<RunResult>(`/api/objectives/${objectiveId}/run`, { method: "POST" }),
  listProducts: (status?: string) =>
    request<Product[]>(`/api/products${status ? `?status=${encodeURIComponent(status)}` : ""}`),
  listProjects: () => request<Project[]>("/api/projects"),
  getProject: (projectId: string) => request<Project>(`/api/projects/${projectId}`),
  listTasks: (projectId: string) => request<Task[]>(`/api/tasks?project_id=${projectId}`),
  listAgents: () => request<Agent[]>("/api/agents"),
  getDecision: (decisionId: string) => request<Decision>(`/api/decisions/${decisionId}`),
  listDecisionsForProject: (projectId: string) => request<Decision[]>(`/api/decisions?project_id=${projectId}`),
  listApprovals: () => request<Approval[]>("/api/approvals"),
  approveApproval: (approvalId: string, actor: string) =>
    request<Approval>(`/api/approvals/${approvalId}/approve`, {
      method: "POST",
      body: JSON.stringify({ actor }),
    }),
  rejectApproval: (approvalId: string, actor: string) =>
    request<Approval>(`/api/approvals/${approvalId}/reject`, {
      method: "POST",
      body: JSON.stringify({ actor }),
    }),
  listAudit: (correlationId?: string) =>
    request<AuditEntry[]>(`/api/audit${correlationId ? `?correlation_id=${correlationId}` : ""}`),
  listAgentExecutions: () => request<AgentExecution[]>("/api/agent-executions"),
  getHealth: () => request<DetailedHealth>("/health/detailed"),

  listJobs: (limit = 50) => request<Job[]>(`/api/jobs?limit=${limit}`),
  getJob: (id: string) => request<Job>(`/api/jobs/${id}`),
  listIncidents: () => request<Incident[]>("/api/incidents"),
  createIncident: (payload: { title: string; description?: string; severity: IncidentSeverity; actor: string }) =>
    request<Incident>("/api/incidents", { method: "POST", body: JSON.stringify(payload) }),
  resolveIncident: (incidentId: string, actor: string) =>
    request<Incident>(`/api/incidents/${incidentId}/resolve`, {
      method: "POST",
      body: JSON.stringify({ actor }),
    }),
  createResearchRun: (payload: { category: string; keywords?: string[]; max_results?: number }) =>
    request<ResearchRun>("/api/research/runs", { method: "POST", body: JSON.stringify(payload) }),
  getResearchRun: (correlationId: string) => request<ResearchRun>(`/api/research/runs/${correlationId}`),
  createSourcingRun: (payload: {
    product_id: string;
    category: string;
    destination_region: string;
    max_results?: number;
  }) => request<SourcingRun>("/api/sourcing/runs", { method: "POST", body: JSON.stringify(payload) }),
  listProductSuppliers: (productId: string) =>
    request<SupplierQuoteDetail[]>(`/api/products/${productId}/suppliers`),
  listSuppliers: () => request<Supplier[]>("/api/suppliers"),
  getSupplier: (supplierId: string) => request<Supplier>(`/api/suppliers/${supplierId}`),
  /** Alta manual de un proveedor real (Milestone 39). */
  createSupplier: (payload: {
    name: string;
    region?: string | null;
    country?: string | null;
    city?: string | null;
    website?: string | null;
    verification?: SupplierProvenance;
    verified_by?: string | null;
    reliability?: number | null;
  }) => request<Supplier>("/api/suppliers", { method: "POST", body: JSON.stringify(payload) }),
  /** Alta manual de una cotización real. Lo que no se pasa se queda sin decir. */
  createSupplierQuote: (
    supplierId: string,
    payload: {
      product_id: string;
      provenance?: SupplierProvenance;
      source?: string | null;
      unit_price?: number | null;
      currency?: string | null;
      quoted_unit?: string | null;
      quoted_quantity?: number | null;
      moq?: number | null;
      lead_time_days?: number | null;
      transit_days?: number | null;
      transport_mode?: string | null;
      incoterm?: string | null;
      payment_terms?: string | null;
      destination_market?: string | null;
      logistics_cost_per_unit?: number | null;
      valid_from?: string | null;
      valid_until?: string | null;
    },
  ) =>
    request<SupplierQuote>(`/api/suppliers/${supplierId}/quotes`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  /** Declara una de las ocho capacidades del §16. */
  declareSupplierCapability: (
    supplierId: string,
    payload: {
      capability: SupplyCapability;
      supported: boolean;
      provenance?: SupplierProvenance;
      product_id?: string | null;
      source?: string | null;
      note?: string | null;
    },
  ) =>
    request<SupplierCapabilityAnswer>(`/api/suppliers/${supplierId}/capabilities`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  createEconomicAnalysisRun: (payload: {
    product_id: string;
    supplier_quote_id: string;
    sale_price: number;
    monthly_fixed_costs?: number;
    monthly_unit_sales_base?: number;
    channel?: string;
    currency?: string;
    units_per_order?: number | null;
    payment_cost_per_unit?: number | null;
    other_variable_cost_per_unit?: number | null;
  }) => request<EconomicAnalysis>("/api/economics/runs", { method: "POST", body: JSON.stringify(payload) }),
  listExchangeRates: () => request<ExchangeRate[]>("/api/exchange-rates"),
  /** Alta manual de un tipo de cambio (Milestone 40). La dirección va en los
   * nombres: `1 base = rate quote`. */
  declareExchangeRate: (payload: {
    base_currency: string;
    quote_currency: string;
    rate: string;
    effective_date: string;
    source?: string | null;
    provenance?: SupplierProvenance;
    declared_by?: string | null;
    note?: string | null;
  }) => request<ExchangeRate>("/api/exchange-rates", { method: "POST", body: JSON.stringify(payload) }),
  listProductEconomics: (productId: string) =>
    request<EconomicAnalysis[]>(`/api/products/${productId}/economics`),
  getEconomicsTimeseries: (days = 30) =>
    request<EconomicsTimeseriesPoint[]>(`/api/economics/analyses/timeseries?days=${days}`),
  createLegalAnalysisRun: (payload: {
    product_id: string;
    market: string;
    certification_available?: boolean;
  }) => request<LegalAnalysis>("/api/legal/runs", { method: "POST", body: JSON.stringify(payload) }),
  listProductLegal: (productId: string) => request<LegalAnalysis[]>(`/api/products/${productId}/legal`),
  /** Requisitos regulatorios que una persona declaró (Milestone 41). */
  listRegulatoryRequirements: () => request<RegulatoryRequirement[]>("/api/regulatory-requirements"),
  declareRegulatoryRequirement: (payload: {
    product_scope: string;
    jurisdiction: string;
    celex: string;
    regulation: string;
    requirement: string;
    kind: "obligation" | "restriction";
    reference?: string | null;
    applicability_provenance?: SupplierProvenance;
    applicability_source?: string | null;
    transposition_reference?: string | null;
    transposition_provenance?: SupplierProvenance | null;
    transposition_source?: string | null;
    note?: string | null;
  }) =>
    request<RegulatoryRequirement>("/api/regulatory-requirements", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  withdrawRegulatoryRequirement: (id: string) =>
    request<RegulatoryRequirement>(`/api/regulatory-requirements/${id}/withdraw`, { method: "POST" }),
  /** Pregunta a la fuente por la norma de un requisito: es una llamada externa. */
  verifyRegulatoryRequirement: (id: string) =>
    request<RegulatoryAnchor>(`/api/regulatory-requirements/${id}/verify`, { method: "POST" }),
  /** Una persona declara qué norma española traspone la directiva del requisito (Milestone 43). */
  declareNationalTransposition: (requirementId: string, payload: { national_id: string; note?: string | null }) =>
    request<NationalTransposition>(`/api/regulatory-requirements/${requirementId}/national-transpositions`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  /** Pregunta al BOE por la norma declarada: es una llamada externa. */
  verifyNationalTransposition: (id: string) =>
    request<NationalTransposition>(`/api/national-transpositions/${id}/verify`, { method: "POST" }),
  withdrawNationalTransposition: (id: string) =>
    request<NationalTransposition>(`/api/national-transpositions/${id}/withdraw`, { method: "POST" }),
  listComplianceEvidence: (productId: string) =>
    request<ComplianceEvidence[]>(`/api/products/${productId}/compliance-evidence`),
  declareComplianceEvidence: (
    productId: string,
    payload: {
      requirement_id: string;
      provenance?: SupplierProvenance;
      source?: string | null;
      reference?: string | null;
      valid_until?: string | null;
      note?: string | null;
    },
  ) =>
    request<ComplianceEvidence>(`/api/products/${productId}/compliance-evidence`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  createStorefrontRun: (payload: { product_id: string; market: string }) =>
    request<Storefront>("/api/ecommerce/runs", { method: "POST", body: JSON.stringify(payload) }),
  listProductStorefronts: (productId: string) =>
    request<Storefront[]>(`/api/products/${productId}/storefronts`),
  createMarketplaceListingRun: (payload: { product_id: string; market: string; platform?: string }) =>
    request<MarketplaceListing>("/api/marketplace/runs", { method: "POST", body: JSON.stringify(payload) }),
  listProductMarketplaceListings: (productId: string) =>
    request<MarketplaceListing[]>(`/api/products/${productId}/marketplace-listings`),
  createMarketingCampaignRun: (payload: {
    product_id: string;
    market: string;
    platform?: string;
    daily_budget?: number;
  }) => request<MarketingCampaign>("/api/marketing/runs", { method: "POST", body: JSON.stringify(payload) }),
  listProductCampaigns: (productId: string) =>
    request<MarketingCampaign[]>(`/api/products/${productId}/campaigns`),
  createOperationsRun: (payload: { product_id: string; market: string }) =>
    request<OperationsRecord>("/api/operations/runs", { method: "POST", body: JSON.stringify(payload) }),
  listProductOperations: (productId: string) =>
    request<OperationsRecord[]>(`/api/products/${productId}/operations`),
  createCFORun: () => request<CFOReport>("/api/cfo/runs", { method: "POST" }),
  getCFORun: (correlationId: string) => request<CFOReport>(`/api/cfo/runs/${correlationId}`),
  listCFORuns: () => request<CFOReport[]>("/api/cfo/runs"),
  createPipelineRun: (payload: {
    category: string;
    sale_price: number;
    destination_region: string;
    market?: string;
    marketplace_platform?: string;
    marketing_platform?: string;
    daily_budget?: number;
    monthly_fixed_costs?: number;
    certification_available?: boolean;
    max_results?: number;
  }) => request<PipelineRun>("/api/pipeline/runs", { method: "POST", body: JSON.stringify(payload) }),
  listResearchComparisons: () => request<ResearchComparison[]>("/api/research/comparisons"),
  listApiUsage: () => request<ApiProviderUsage[]>("/api/costs/api-usage"),
  listPipelineRuns: () => request<PipelineRun[]>("/api/pipeline/runs"),
  listPipelineReviews: () => request<PipelineReview[]>("/api/pipeline/reviews"),
  approvePipelineReview: (reviewId: string, actor: string) =>
    request<PipelineReview>(`/api/pipeline/reviews/${reviewId}/approve`, {
      method: "POST",
      body: JSON.stringify({ actor }),
    }),
  rejectPipelineReview: (reviewId: string, actor: string) =>
    request<PipelineReview>(`/api/pipeline/reviews/${reviewId}/reject`, {
      method: "POST",
      body: JSON.stringify({ actor }),
    }),
  getPipelineKillSwitch: () => request<PipelineKillSwitchState>("/api/pipeline/kill-switch"),
  setPipelineKillSwitch: (payload: { enabled: boolean; reason?: string; actor: string }) =>
    request<PipelineKillSwitchState>("/api/pipeline/kill-switch", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};
