import type { Decision } from "@/lib/api";

export type NodeStatus = "idle" | "waiting" | "active" | "blocked" | "error";
export type NodeKind = "ceo" | "agent" | "decision" | "output";

export interface AgentGraphNode {
  id: string;
  label: string;
  /** One-line role description shown in the node detail panel. */
  role: string;
  status: NodeStatus;
  kind: NodeKind;
  /** [x, y, z] — used directly by the 3D scene; the 2D fallback maps x/z onto a plane. */
  position: [number, number, number];
}

export interface AgentGraphEdge {
  id: string;
  source: string;
  target: string;
  active: boolean;
}

function findEvidence(decision: Decision | null, source: string) {
  return decision?.evidence.find((e) => e.source === source);
}

/** The CEOOrchestrator flow this page drives (Milestone 1) only produces
 * evidence for 4 specialists — market_analyst/marketing/ecommerce belong
 * to the separate Fase-3 PipelineOrchestrator (ADR 0001/0005) and never
 * light up here. They stay in the graph as the full conceptual agent
 * roster the design spec asks for (v0.5 §4.2), just permanently idle on
 * this page — never faked as active. */
export function deriveGraphState(decision: Decision | null): {
  nodes: AgentGraphNode[];
  edges: AgentGraphEdge[];
} {
  const hasRun = decision !== null;

  const productEvidence = findEvidence(decision, "product_validation");
  const supplierEvidence = findEvidence(decision, "supplier_sourcing");
  const financeEvidence = findEvidence(decision, "finance_validation");
  const legalEvidence = findEvidence(decision, "legal_validation");

  const financeBlocked = Boolean(financeEvidence?.data?.finance_veto);
  const legalStatus = legalEvidence?.data?.legal_status as string | undefined;
  const legalBlocked = legalStatus === "NO_GO";

  const status = decision?.status;
  const approveActive = status === "GO";
  const rejectActive = status === "NO_GO";
  const decisionEngineStatus: NodeStatus = !hasRun
    ? "idle"
    : status === "GO"
      ? "active"
      : status === "NO_GO"
        ? "error"
        : "waiting"; // REVIEW / HUMAN_APPROVAL

  const specialist = (evidence: unknown, blocked: boolean): NodeStatus => {
    if (!hasRun) return "idle";
    if (blocked) return "blocked";
    return evidence ? "active" : "waiting";
  };

  const nodes: AgentGraphNode[] = [
    { id: "ceo", label: "CEO", role: "Orquestador — inicia el objetivo", status: hasRun ? "active" : "idle", kind: "ceo", position: [0, 5.5, 0] },

    { id: "product_hunter", label: "Product Hunter", role: "Validación de producto", status: specialist(productEvidence, false), kind: "agent", position: [-4.5, 2, 2] },
    { id: "market_analyst", label: "Market Analyst", role: "Investigación de mercado (Fase 3)", status: "idle", kind: "agent", position: [-2, 2, 4.2] },
    { id: "supplier_finder", label: "Supplier Finder", role: "Sourcing de proveedores", status: specialist(supplierEvidence, false), kind: "agent", position: [2, 2, 4.2] },
    { id: "cfo_finance", label: "CFO / Finanzas", role: "Validación financiera", status: specialist(financeEvidence, financeBlocked), kind: "agent", position: [4.5, 2, 2] },
    { id: "legal", label: "Legal", role: "Cumplimiento legal", status: specialist(legalEvidence, legalBlocked), kind: "agent", position: [4.5, 2, -2] },
    { id: "marketing", label: "Marketing", role: "Adquisición (Fase 3)", status: "idle", kind: "agent", position: [2, 2, -4.2] },
    { id: "ecommerce", label: "E-commerce", role: "Tienda y canales (Fase 3)", status: "idle", kind: "agent", position: [-2, 2, -4.2] },

    { id: "decision_engine", label: "Decision Engine", role: "Síntesis de la decisión", status: decisionEngineStatus, kind: "decision", position: [0, -1.5, 0] },

    { id: "approve", label: "Aprobar", role: "Salida: GO", status: approveActive ? "active" : "idle", kind: "output", position: [-2.5, -4, 0] },
    { id: "reject", label: "Rechazar", role: "Salida: NO_GO", status: rejectActive ? "error" : "idle", kind: "output", position: [2.5, -4, 0] },
  ];

  const specialistIds = ["product_hunter", "market_analyst", "supplier_finder", "cfo_finance", "legal", "marketing", "ecommerce"];

  const edges: AgentGraphEdge[] = [
    ...specialistIds.map((id) => ({ id: `ceo-${id}`, source: "ceo", target: id, active: hasRun })),
    ...specialistIds.map((id) => ({
      id: `${id}-decision_engine`,
      source: id,
      target: "decision_engine",
      active: nodes.find((n) => n.id === id)?.status === "active",
    })),
    { id: "decision_engine-approve", source: "decision_engine", target: "approve", active: approveActive },
    { id: "decision_engine-reject", source: "decision_engine", target: "reject", active: rejectActive },
  ];

  return { nodes, edges };
}
