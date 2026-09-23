import assert from "node:assert/strict";
import { test } from "node:test";
import type { Agent, Approval, EconomicAnalysis, LegalAnalysis, Product, Storefront, SupplierQuote } from "./api.ts";
import { REQUEST_TEMPLATES, RESOLVED_STATS, SLA_HOURS } from "./demo/approvals.ts";
import {
  countFor,
  demoRequests,
  filterRequests,
  hoursLeft,
  inboxKpis,
  requestFromApproval,
  requestsByKind,
  sortRequests,
  statusShares,
  type ProductContext,
} from "./approvals-view.ts";

const NOW = Date.parse("2026-09-22T12:00:00Z");
const HOUR = 3_600_000;

const PRODUCT: Product = { id: "p-917", name: "Silicone kitchen organizer", category: "home", status: "CANDIDATE", created_by: "agent", source: "research" };

const QUOTE: SupplierQuote = {
  id: "q1",
  product_id: PRODUCT.id,
  supplier_id: "sup-eu",
  unit_price: 3.4,
  moq: 10,
  lead_time_days: 10,
  verified: true,
  reliability_score: 0.9,
  logistics_cost_per_unit: 1.2,
  total_landed_cost_per_unit: 4.6,
  data: { name: "Bratislava Homeware Supply", region: "eu" },
};

const ANALYSIS: EconomicAnalysis = {
  correlation_id: "c-eco",
  product_id: PRODUCT.id,
  supplier_quote_id: "q1",
  sale_price: 50,
  monthly_fixed_costs: 500,
  margin_percent: 0.93,
  recommendation: "GO",
  confidence: 0.85,
  data: { scenarios: { conservative: { monthly_unit_sales: 186, margin_percent: 0.93, monthly_revenue: 9318, monthly_profit: 8197 }, base: { monthly_unit_sales: 266, margin_percent: 0.93, monthly_revenue: 13312, monthly_profit: 11924 }, optimistic: { monthly_unit_sales: 346, margin_percent: 0.93, monthly_revenue: 17306, monthly_profit: 15651 } }, risks: ["muestra limitada"] },
};

const LEGAL: LegalAnalysis = {
  correlation_id: "c-legal",
  product_id: PRODUCT.id,
  supplier_quote_id: "q1",
  market: "eu",
  restricted: false,
  recommendation: "GO",
  confidence: 0.8,
  data: { required_certifications: ["CE"], known_risks: ["documentación pendiente"], recent_changes: [] },
};

const STOREFRONT: Storefront = {
  correlation_id: "c-store",
  product_id: PRODUCT.id,
  market: "eu",
  store_slug: "silicone",
  launch_status: "READY",
  recommendation: "GO",
  confidence: 0.8,
  data: null,
};

const AGENTS: Agent[] = [
  { id: "a-marketing", name: "Acquisition Agent", role: "marketing", capabilities: [], status: "AVAILABLE", reliability_score: 1, version: "1.8.5", cost_profile: {} },
  { id: "a-legal", name: "Product Compliance", role: "legal", capabilities: [], status: "AVAILABLE", reliability_score: 1, version: "1.7.2", cost_profile: {} },
  { id: "a-cfo", name: "CFO Controller", role: "cfo", capabilities: [], status: "AVAILABLE", reliability_score: 1, version: "1.9.0", cost_profile: {} },
];

const CONTEXT: ProductContext = {
  product: PRODUCT,
  quotes: [QUOTE],
  economics: [ANALYSIS],
  legal: [LEGAL],
  storefronts: [STOREFRONT],
  campaigns: [],
  projectCode: "AMZ-0024",
  market: "eu",
};

const REQUESTS = demoRequests(CONTEXT, AGENTS, NOW);

test("demoRequests: una solicitud por plantilla, con datos del producto real", () => {
  assert.equal(REQUESTS.length, REQUEST_TEMPLATES.length);
  assert.deepEqual(demoRequests(CONTEXT, AGENTS, NOW), REQUESTS, "determinista");
  assert.equal(demoRequests(undefined, AGENTS, NOW).length, 0);

  const campaign = REQUESTS[0];
  assert.equal(campaign.title, "Campaña de lanzamiento");
  assert.equal(campaign.projectCode, "AMZ-0024");
  assert.equal(campaign.productName, PRODUCT.name);
  assert.equal(campaign.requestedBy, "Acquisition Agent", "usa el agente real del registro");
  assert.ok(campaign.amount! > 0);
  assert.ok(campaign.budget && campaign.budget.request === campaign.amount);
  assert.ok(campaign.fields.some((field) => field.label === "CAC máximo"));
  assert.ok(campaign.findings.some((text) => text.includes("ROAS")));
  assert.ok(campaign.risks.length > 0 && campaign.risks.length <= 3);
  assert.equal(campaign.isDemo, true);
  assert.equal(campaign.status, "PENDING");
  // El vencimiento sale del SLA de su severidad.
  assert.equal(campaign.expiresAt - campaign.requestedAt, SLA_HOURS[campaign.severity] * HOUR);
  assert.equal(new Set(REQUESTS.map((r) => r.code)).size, REQUESTS.length);
});

test("demoRequests: las validaciones llevan el estado real de cada análisis", () => {
  const campaign = REQUESTS[0];
  assert.deepEqual(campaign.validations.map((v) => v.label), ["Economía", "Legal", "Tienda", "Finanzas", "Riesgo"]);
  assert.equal(campaign.validations.find((v) => v.label === "Economía")!.state, "ok", "el análisis recomienda GO");
  // El Legal Gate se calcula igual que en la pantalla de Legal: con el catálogo
  // de requisitos sin evidencias, un análisis GO sigue saliendo bloqueado.
  assert.equal(campaign.validations.find((v) => v.label === "Legal")!.state, "bad");
  assert.ok(campaign.opinions.length === 7 && campaign.opinions.every((o) => o.agent.length > 2));
  assert.equal(campaign.opinions.find((o) => o.agent === "CFO Controller")?.ok, true);

  const noAnalysis = demoRequests({ ...CONTEXT, economics: [], legal: [], storefronts: [] }, AGENTS, NOW)[0];
  assert.equal(noAnalysis.validations.find((v) => v.label === "Economía")!.detail, "Sin análisis");
  assert.equal(noAnalysis.validations.find((v) => v.label === "Tienda")!.detail, "Sin escaparate");
});

test("requestFromApproval: la aprobación real se presenta sin inventar análisis", () => {
  const approval: Approval = {
    id: "apr-1234567",
    decision_id: "dec-1",
    action: "launch_marketing_campaign",
    amount: 1500,
    status: "PENDING",
    expires_at: new Date(NOW + 6 * HOUR).toISOString(),
    resolved_at: null,
    resolved_by: null,
  };
  const request = requestFromApproval(approval, NOW);
  assert.equal(request.isDemo, false);
  assert.equal(request.title, "Lanzamiento de campaña de marketing");
  assert.equal(request.amount, 1500);
  assert.equal(request.severity, "Crítica");
  assert.deepEqual(request.validations, []);
  assert.deepEqual(request.opinions, []);
  assert.ok(request.approveImpact.length >= 2 && request.rejectImpact.length >= 2);

  const expired = requestFromApproval({ ...approval, expires_at: new Date(NOW - HOUR).toISOString() }, NOW);
  assert.equal(expired.status, "EXPIRED");
});

test("inboxKpis: pendientes, críticas, las que vencen pronto y el tiempo medio", () => {
  const kpis = inboxKpis(REQUESTS, NOW);
  assert.equal(kpis.pending, REQUESTS.length);
  assert.equal(kpis.critical, REQUESTS.filter((r) => r.severity === "Crítica").length);
  assert.ok(kpis.expiringSoon >= 1 && kpis.expiringSoon <= kpis.pending);
  assert.equal(kpis.approvedToday, RESOLVED_STATS.approved);
  assert.equal(kpis.averageMinutes, RESOLVED_STATS.averageMinutes);
});

test("filterRequests, countFor y sortRequests: pestañas, búsqueda y orden", () => {
  assert.equal(filterRequests(REQUESTS, { filter: "all" }).length, REQUESTS.length);
  assert.ok(filterRequests(REQUESTS, { filter: "critical" }).every((r) => r.severity === "Crítica"));
  assert.ok(filterRequests(REQUESTS, { filter: "marketing" }).every((r) => r.kind === "marketing"));
  assert.equal(countFor(REQUESTS, "agents"), REQUESTS.filter((r) => r.kind === "agents").length);
  assert.equal(filterRequests(REQUESTS, { filter: "all", query: "proveedor" }).length, 1);

  const bySeverity = sortRequests(REQUESTS, "severity");
  assert.equal(bySeverity[0].severity, "Crítica");
  const byAmount = sortRequests(REQUESTS, "amount");
  assert.ok((byAmount[0].amount ?? 0) >= (byAmount[1].amount ?? 0));
  const recent = sortRequests(REQUESTS, "recent");
  assert.ok(recent[0].requestedAt >= recent[1].requestedAt);
  assert.ok(sortRequests(REQUESTS, "oldest")[0].requestedAt <= recent[0].requestedAt);
});

test("requestsByKind y statusShares: reparto por tipo y por estado", () => {
  const kinds = requestsByKind(REQUESTS);
  assert.equal(kinds.reduce((sum, row) => sum + row.value, 0), REQUESTS.length);
  for (let k = 1; k < kinds.length; k++) assert.ok(kinds[k - 1].value >= kinds[k].value);

  const shares = statusShares(REQUESTS);
  assert.equal(shares.length, 6);
  assert.ok(Math.abs(shares.reduce((sum, row) => sum + row.share, 0) - 1) < 1e-9);
  assert.equal(shares.find((row) => row.label === "Pendientes")!.value, REQUESTS.length);
});

test("hoursLeft: horas hasta el vencimiento, negativas si ya venció", () => {
  const campaign = REQUESTS[0];
  assert.ok(Math.abs(hoursLeft(campaign, NOW) - (SLA_HOURS[campaign.severity] - 0.4)) < 0.01);
  assert.ok(hoursLeft(campaign, campaign.expiresAt + HOUR) < 0);
});
