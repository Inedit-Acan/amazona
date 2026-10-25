/** La conversación escrita con el CEO (M52): tipos del contrato con el backend y la lógica pura de la pantalla.
 *
 * Sin React ni navegador: se prueba con `node --test` (`ceo-chat.test.ts`). El backend es la fuente de verdad —el modelo propone, el propietario confirma
 * y el backend ejecuta—; aquí solo se decide QUÉ se enseña y CÓMO se clasifica un error. Nada de lo que muestra es inventado: si el backend no dice
 * un coste, se enseña «No estimado», no cero. */

export const CHAT_MAX_CHARS = 2000;

export type ChatRole = "user" | "assistant" | "tool";

export interface CeoMessage {
  id: string;
  seq: number;
  role: ChatRole;
  content: string;
  /** La salida estructurada de una herramienta, o el resultado de una acción. */
  structured: Record<string, unknown> | null;
  provider: string | null;
  model: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  estimated_cost_usd: number | null;
  external_cost_category: string | null;
  created_at: string | null;
}

export type ProposalStatus = "PROPOSED" | "EXECUTING" | "EXECUTED" | "FAILED" | "REJECTED";
export type RiskLevel = "low" | "medium" | "high";
export type ActionType =
  | "create_mission"
  | "retry_task"
  | "reassign_task"
  | "resume_mission"
  | "approve_approval"
  | "reject_approval";

export interface CeoProposal {
  id: string;
  conversation_id: string;
  message_id: string | null;
  action_type: ActionType;
  target: Record<string, unknown>;
  parameters: Record<string, unknown>;
  reason: string;
  estimated_effects: { summary?: string; external_cost_eur?: number; budget_effect?: string } & Record<string, unknown>;
  risk_level: RiskLevel;
  requires_confirmation: boolean;
  idempotency_scope: string | null;
  status: ProposalStatus;
  resolved_at: string | null;
  execution_result: Record<string, unknown> | null;
  error: string | null;
  result_message_id: string | null;
  created_at: string | null;
}

export interface CeoUsage {
  rounds: number;
  tool_rounds: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number | null;
  provider: string | null;
  model: string | null;
  external_cost_category: string | null;
  stopped: string | null;
}

export interface CeoChatReply {
  conversation_id: string;
  user_message: CeoMessage;
  tool_messages: CeoMessage[];
  assistant_message: CeoMessage;
  proposals: CeoProposal[];
  sources: string[];
  usage: CeoUsage;
}

export interface CeoConversationSummary {
  id: string;
  title: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface CeoConversation extends CeoConversationSummary {
  messages: CeoMessage[];
  proposals: CeoProposal[];
}

export interface CeoActionReply {
  proposal: CeoProposal;
  result_message: CeoMessage | null;
}

// --- Qué se puede enviar --------------------------------------------------------------------------------------------

export function canSend(text: string, busy: boolean): boolean {
  const trimmed = text.trim();
  return !busy && trimmed.length > 0 && trimmed.length <= CHAT_MAX_CHARS;
}

// --- Errores --------------------------------------------------------------------------------------------------------

export type ChatFailure =
  | { kind: "unavailable"; message: string; conversationId: string | null }
  | { kind: "unauthenticated"; message: string }
  | { kind: "forbidden"; message: string }
  | { kind: "error"; message: string };

/** Clasifica el fallo de una llamada del chat. Un 503 es «el CEO no está disponible» (el mensaje YA está guardado en la conversación que dice el cuerpo);
 * 401 y 403 son de identidad. Nunca se enseña el cuerpo crudo del servidor. */
export function classifyChatError(status: number, body: string): ChatFailure {
  if (status === 401) return { kind: "unauthenticated", message: "Inicia sesión como propietario para hablar con el CEO." };
  if (status === 403) return { kind: "forbidden", message: "Solo el propietario puede hablar con el CEO." };
  if (status === 503) {
    let conversationId: string | null = null;
    let message = "El CEO no está disponible ahora. Tu mensaje se ha guardado; el resto del panel sigue funcionando.";
    try {
      const parsed: unknown = JSON.parse(body);
      const detail = parsed && typeof parsed === "object" && "detail" in parsed ? (parsed as { detail: unknown }).detail : null;
      if (detail && typeof detail === "object") {
        const d = detail as { conversation_id?: unknown; message?: unknown };
        if (typeof d.conversation_id === "string") conversationId = d.conversation_id;
        if (typeof d.message === "string") message = d.message;
      }
    } catch {
      // cuerpo no JSON: el texto fijo de arriba
    }
    return { kind: "unavailable", message, conversationId };
  }
  if (status === 409) return { kind: "error", message: "Esta propuesta ya se resolvió o ya no es posible." };
  if (status === 428) return { kind: "error", message: "Falta la clave de idempotencia de la operación." };
  if (status === 404) return { kind: "error", message: "No se encontró la conversación o la propuesta." };
  if (status === 422) return { kind: "error", message: "El mensaje no es válido." };
  return { kind: "error", message: "No se pudo completar la operación." };
}

// --- Etiquetas ------------------------------------------------------------------------------------------------------

export const ACTION_LABELS: Record<ActionType, string> = {
  create_mission: "Crear misión",
  retry_task: "Reintentar tarea",
  reassign_task: "Reasignar tarea",
  resume_mission: "Reanudar misión",
  approve_approval: "Aprobar aprobación",
  reject_approval: "Rechazar aprobación",
};

export const RISK_LABELS: Record<RiskLevel, { label: string; tone: "ok" | "warn" | "bad" }> = {
  low: { label: "Riesgo bajo", tone: "ok" },
  medium: { label: "Riesgo medio", tone: "warn" },
  high: { label: "Riesgo alto", tone: "bad" },
};

export const STATUS_LABELS: Record<ProposalStatus, string> = {
  PROPOSED: "Pendiente de tu confirmación",
  EXECUTING: "Ejecutándose",
  EXECUTED: "Ejecutada",
  FAILED: "No se pudo ejecutar",
  REJECTED: "Rechazada",
};

/** Solo una propuesta `PROPOSED` se puede confirmar o rechazar. */
export function isOpen(proposal: Pick<CeoProposal, "status">): boolean {
  return proposal.status === "PROPOSED";
}

/** El coste de una consulta. `null` = no hay tarifa configurada: se dice, no se inventa un cero. */
export function costLabel(usage: Pick<CeoUsage, "estimated_cost_usd" | "input_tokens" | "output_tokens">): string {
  const tokens = `${usage.input_tokens} entrada · ${usage.output_tokens} salida`;
  const cost = usage.estimated_cost_usd === null ? "Coste no estimado" : `≈ ${usage.estimated_cost_usd.toFixed(4)} USD`;
  return `${cost} · ${tokens} tokens`;
}

/** Lo que se enseña del contexto: las fuentes, ya con nombre. */
export function sourcesLabel(sources: readonly string[]): string | null {
  return sources.length === 0 ? null : `Fuentes: ${sources.join(" · ")}`;
}

/** Lo visible de una conversación: lo que dijo el propietario y lo que contestó el CEO. Las herramientas se enseñan como fuentes, no como mensajes. */
export function conversationLines(messages: readonly CeoMessage[]): CeoMessage[] {
  return messages.filter((message) => message.role === "user" || message.role === "assistant");
}

/** De qué herramientas leyó una respuesta, sin repetir, en el orden en que las usó. */
export function toolsRead(messages: readonly CeoMessage[]): string[] {
  const names: string[] = [];
  for (const message of messages) {
    const tool = message.role === "tool" && message.structured ? message.structured["tool"] : null;
    if (typeof tool === "string" && tool.startsWith("get_") && !names.includes(tool)) names.push(tool);
  }
  return names;
}

// --- Fuentes de una respuesta ---------------------------------------------------------------------------------------

/** El nombre con el que se enseña cada lectura del CEO: las fuentes de lo que contesta. */
export const TOOL_LABELS: Record<string, string> = {
  get_system_status: "Estado general",
  get_latest_mission: "Última misión",
  get_budget_status: "Presupuesto",
  get_pending_approvals: "Aprobaciones",
  get_task_details: "Tarea",
  get_decision_history: "Decisiones",
  get_audit_summary: "Auditoría",
};

/** Las fuentes de CADA respuesta de una conversación guardada: las lecturas hechas desde el mensaje anterior del propietario hasta esa respuesta. */
export function sourcesByAnswer(messages: readonly CeoMessage[]): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  let pending: CeoMessage[] = [];
  for (const message of [...messages].sort((a, b) => a.seq - b.seq)) {
    if (message.role === "user") pending = [];
    else if (message.role === "tool") pending.push(message);
    else if (message.role === "assistant") {
      out[message.id] = toolsRead(pending).map((name) => TOOL_LABELS[name] ?? name);
      pending = [];
    }
  }
  return out;
}

export const BUDGET_EFFECT_LABELS: Record<string, string> = {
  none: "Presupuesto: sin cambios",
  commit: "Presupuesto: compromete lo reservado",
  release: "Presupuesto: libera lo reservado",
};
