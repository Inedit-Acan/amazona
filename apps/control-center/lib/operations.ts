import type { SupportTicketExample } from "./api.ts";

// El agente de operaciones (operations.py) genera un ticket de soporte de
// ejemplo y su triaje (IA o persona). Es lo único de su informe que el Control
// Tower enseña tal cual: el resto de la pantalla son pedidos de demostración.

export const TICKET_TYPE_LABELS: Record<string, string> = {
  compliance_question: "Consulta de cumplimiento",
  order_status_inquiry: "Consulta de estado del pedido",
};

export function ticketTypeLabel(type: string): string {
  return TICKET_TYPE_LABELS[type] ?? type.replace(/_/g, " ");
}

/** Cómo se resolvería el ticket de ejemplo del agente. */
export function ticketTriage(ticket: SupportTicketExample): { label: string; detail: string } {
  return ticket.ai_resolvable
    ? { label: "Resoluble por IA", detail: ticketTypeLabel(ticket.ticket_type) }
    : { label: "Escala a una persona", detail: ticket.escalation_reason ?? ticketTypeLabel(ticket.ticket_type) };
}
