"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Check, CircleSlash, Send, ShieldCheck, TriangleAlert, X } from "lucide-react";
import { LevelChip } from "@/components/level-chip";
import { Button } from "@/components/ui/button";
import { ApiError, api } from "@/lib/api";
import {
  ACTION_LABELS,
  BUDGET_EFFECT_LABELS,
  CHAT_MAX_CHARS,
  RISK_LABELS,
  STATUS_LABELS,
  canSend,
  classifyChatError,
  conversationLines,
  costLabel,
  isOpen,
  sourcesByAnswer,
  sourcesLabel,
  type CeoConversation,
  type CeoMessage,
  type CeoProposal,
  type ChatFailure,
} from "@/lib/ceo-chat";
import { OPERATIONS } from "@/lib/intent-operations";
import { useIntent } from "@/lib/use-intent";

/** El chat escrito con el CEO (M52). El CEO LEE el estado real con herramientas cerradas y PROPONE acciones; no ejecuta nada. Cada propuesta es una
 * tarjeta con Confirmar / Rechazar: confirmar es una llamada autenticada del propietario, no algo que el modelo pueda decir. Si el modelo no está
 * disponible lo dice y el resto del panel sigue funcionando. Sin voz. */

const SUGGESTIONS = ["¿Cuál es el estado actual de AMAZONA?", "Analiza el presupuesto actual.", "¿Qué decisión tomaste en la última misión?"];

function failureFrom(error: unknown): ChatFailure {
  if (error instanceof ApiError) return classifyChatError(error.status, error.message);
  return { kind: "error", message: "No se pudo contactar con el backend." };
}

function CostLine({ message }: { message: CeoMessage }) {
  if (message.role !== "assistant" || message.input_tokens === null) return null;
  return (
    <span data-chat-cost className="block text-[0.7rem] text-muted-foreground">
      {costLabel({
        estimated_cost_usd: message.estimated_cost_usd,
        input_tokens: message.input_tokens,
        output_tokens: message.output_tokens ?? 0,
      })}
      {message.external_cost_category ? ` · ${message.external_cost_category}` : ""}
    </span>
  );
}

function ProposalCard({
  proposal,
  busy,
  onConfirm,
  onReject,
}: {
  proposal: CeoProposal;
  busy: boolean;
  onConfirm: (proposal: CeoProposal) => void;
  onReject: (proposal: CeoProposal) => void;
}) {
  const risk = RISK_LABELS[proposal.risk_level];
  const effects = proposal.estimated_effects;
  const budget = BUDGET_EFFECT_LABELS[effects.budget_effect ?? "none"] ?? BUDGET_EFFECT_LABELS.none;
  return (
    <div
      data-proposal-id={proposal.id}
      data-proposal-status={proposal.status}
      className="space-y-2 rounded-lg border border-primary/25 bg-primary/5 p-3"
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-medium">{ACTION_LABELS[proposal.action_type]}</p>
        <LevelChip tone={risk.tone} className="shrink-0">
          {risk.label}
        </LevelChip>
      </div>
      {proposal.reason ? <p className="text-xs leading-snug text-muted-foreground">{proposal.reason}</p> : null}
      {effects.summary ? <p className="text-xs leading-snug">{effects.summary}</p> : null}
      <p className="text-[0.7rem] text-muted-foreground">
        Coste externo: {effects.external_cost_eur ?? 0} € · {budget}
      </p>
      {isOpen(proposal) ? (
        <div className="flex items-center gap-2">
          <Button type="button" size="sm" disabled={busy} onClick={() => onConfirm(proposal)}>
            <Check aria-hidden /> Confirmar
          </Button>
          <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => onReject(proposal)}>
            <X aria-hidden /> Rechazar
          </Button>
        </div>
      ) : (
        <p className="text-xs font-medium" data-proposal-outcome>
          {STATUS_LABELS[proposal.status]}
          {proposal.error ? <span className="block font-normal text-muted-foreground">{proposal.error}</span> : null}
        </p>
      )}
    </div>
  );
}

export function CeoChat() {
  const intent = useIntent("ceo-chat");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<CeoMessage[]>([]);
  const [proposals, setProposals] = useState<Record<string, CeoProposal>>({});
  const [sources, setSources] = useState<Record<string, string[]>>({});
  const [draft, setDraft] = useState("");
  const [thinking, setThinking] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);
  const [failure, setFailure] = useState<ChatFailure | null>(null);
  const [loaded, setLoaded] = useState(false);
  const logEnd = useRef<HTMLDivElement>(null);

  const hydrate = useCallback((conversation: CeoConversation) => {
    setConversationId(conversation.id);
    setMessages(conversation.messages);
    setProposals(Object.fromEntries(conversation.proposals.map((proposal) => [proposal.id, proposal])));
    setSources(sourcesByAnswer(conversation.messages));
  }, []);

  // Al abrir: la última conversación del propietario, si la hay. Un fallo se dice; no se traga.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [latest] = await api.listCeoConversations();
        if (latest && !cancelled) hydrate(await api.getCeoConversation(latest.id));
      } catch (error) {
        if (!cancelled) setFailure(failureFrom(error));
      } finally {
        if (!cancelled) setLoaded(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [hydrate]);

  useEffect(() => {
    logEnd.current?.scrollIntoView?.({ block: "end" });
  }, [messages, thinking, proposals]);

  const blocked = failure?.kind === "forbidden" || failure?.kind === "unauthenticated";

  async function send() {
    const text = draft.trim();
    if (!canSend(text, thinking) || blocked) return;
    setThinking(true);
    setFailure(null);
    try {
      const reply = await intent.run(
        { operation: OPERATIONS.ceoChat, target: conversationId ?? "new", params: { message: text } },
        (key) => api.sendCeoChat({ message: text, conversation_id: conversationId }, key),
      );
      setConversationId(reply.conversation_id);
      setMessages((current) => [...current, reply.user_message, reply.assistant_message]);
      setProposals((current) => ({ ...current, ...Object.fromEntries(reply.proposals.map((proposal) => [proposal.id, proposal])) }));
      setSources((current) => ({ ...current, [reply.assistant_message.id]: reply.sources }));
      setDraft("");
    } catch (error) {
      const next = failureFrom(error);
      setFailure(next);
      // El mensaje ya está guardado en el servidor: se enseña en su conversación y no se vuelve a enviar.
      if (next.kind === "unavailable" && next.conversationId) {
        try {
          hydrate(await api.getCeoConversation(next.conversationId));
          setDraft("");
        } catch {
          // la conversación se ve al reabrir; el aviso ya está puesto
        }
      }
    } finally {
      setThinking(false);
    }
  }

  async function act(proposal: CeoProposal, run: () => Promise<{ proposal: CeoProposal; result_message: CeoMessage | null }>) {
    setActionBusy(true);
    setFailure(null);
    try {
      const reply = await run();
      setProposals((current) => ({ ...current, [proposal.id]: reply.proposal }));
      const result = reply.result_message;
      if (result) setMessages((current) => (current.some((m) => m.id === result.id) ? current : [...current, result]));
    } catch (error) {
      setFailure(failureFrom(error));
    } finally {
      setActionBusy(false);
    }
  }

  const confirm = (proposal: CeoProposal) =>
    act(proposal, () =>
      intent.run({ operation: OPERATIONS.ceoConfirm, target: proposal.id, params: {} }, (key) => api.confirmCeoAction(proposal.id, key)),
    );
  const reject = (proposal: CeoProposal) => act(proposal, () => api.rejectCeoAction(proposal.id));

  const lines = conversationLines(messages);
  const byMessage = (messageId: string) => Object.values(proposals).filter((proposal) => proposal.message_id === messageId);

  return (
    <div data-ceo-chat className="flex h-full min-h-0 flex-col gap-2">
      <div role="log" aria-live="polite" aria-label="Conversación con el CEO" className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
        {loaded && lines.length === 0 && !blocked ? (
          <div className="space-y-2" data-chat-empty>
            <p className="flex items-center gap-2 text-xs text-muted-foreground">
              <ShieldCheck aria-hidden className="size-4 shrink-0 text-primary" />
              El CEO lee el estado guardado y propone; tú confirmas.
            </p>
            {SUGGESTIONS.map((suggestion) => (
              <button
                key={suggestion}
                type="button"
                onClick={() => setDraft(suggestion)}
                className="block w-full rounded-lg border border-border bg-muted/20 px-3 py-2 text-left text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
              >
                {suggestion}
              </button>
            ))}
          </div>
        ) : null}

        {lines.map((message) =>
          message.role === "user" ? (
            <div key={message.id} data-chat-role="user" className="ml-6 rounded-lg bg-primary/15 px-3 py-2 text-sm whitespace-pre-wrap">
              {message.content}
            </div>
          ) : (
            <div key={message.id} data-chat-role="assistant" className="mr-2 space-y-2">
              <div className="rounded-lg bg-muted/40 px-3 py-2 text-sm whitespace-pre-wrap">{message.content}</div>
              {sourcesLabel(sources[message.id] ?? []) ? (
                <span data-chat-sources className="block text-[0.7rem] text-muted-foreground">
                  {sourcesLabel(sources[message.id] ?? [])}
                </span>
              ) : null}
              <CostLine message={message} />
              {byMessage(message.id).map((proposal) => (
                <ProposalCard key={proposal.id} proposal={proposal} busy={actionBusy} onConfirm={confirm} onReject={reject} />
              ))}
            </div>
          ),
        )}

        {thinking ? (
          <p data-chat-thinking className="flex items-center gap-2 text-xs text-muted-foreground" role="status">
            <span aria-hidden className="size-2 rounded-full bg-primary motion-safe:animate-pulse" />
            CEO analizando…
          </p>
        ) : null}
        <div ref={logEnd} />
      </div>

      {failure ? (
        <div
          role="alert"
          data-chat-failure={failure.kind}
          className="flex items-start gap-2 rounded-lg border border-border bg-muted/30 p-2.5 text-xs"
        >
          {failure.kind === "unavailable" ? (
            <CircleSlash aria-hidden className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
          ) : (
            <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-warning" />
          )}
          <p className="leading-snug">{failure.message}</p>
        </div>
      ) : null}

      <form
        className="flex items-end gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          void send();
        }}
      >
        <textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void send();
            }
          }}
          rows={2}
          maxLength={CHAT_MAX_CHARS}
          disabled={blocked}
          aria-label="Mensaje para el CEO"
          placeholder={blocked ? "Solo el propietario" : "Escribe al CEO…"}
          className="min-h-9 min-w-0 flex-1 resize-none rounded-lg border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-60"
        />
        <Button type="submit" size="icon" disabled={blocked || !canSend(draft, thinking)} aria-label="Enviar mensaje">
          <Send aria-hidden />
        </Button>
      </form>
    </div>
  );
}
