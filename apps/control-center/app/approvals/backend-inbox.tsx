"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, CircleDashed, Clock, Inbox, Loader2 } from "lucide-react";
import { ApiError, api } from "@/lib/api";
import {
  REAL_FILTERS,
  REAL_SORT_LABELS,
  filterReal,
  sortReal,
  type RealFilter,
  type RealInbox,
  type RealRequest,
  type RealSort,
} from "@/lib/approvals-inbox";
import { formatUtcDateTime } from "@/lib/ceo-block-view";
import { formatAmount, formatInteger } from "@/lib/format";
import { EmptyState } from "@/components/empty-state";
import { KpiCard } from "@/components/kpi-card";
import { LevelChip, type LevelTone } from "@/components/level-chip";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

const NOT_AVAILABLE = "No disponible";

const STATUS_LABEL: Record<string, { text: string; tone: LevelTone }> = {
  PENDING: { text: "Pendiente", tone: "warn" },
  APPROVED: { text: "Aprobada", tone: "ok" },
  REJECTED: { text: "Rechazada", tone: "bad" },
  EXPIRED: { text: "Vencida", tone: "bad" },
  CANCELLED: { text: "Cancelada", tone: "neutral" },
  CONSUMED: { text: "Consumida", tone: "neutral" },
};

function statusOf(request: RealRequest): { text: string; tone: LevelTone } {
  if (request.expired) return { text: "Vencida sin resolver", tone: "bad" };
  return STATUS_LABEL[request.status] ?? { text: request.status, tone: "neutral" };
}

const requestedText = (request: RealRequest) =>
  request.requestedAt === null ? "Sin fecha de solicitud" : `Solicitada ${formatUtcDateTime(request.requestedAt)}`;
const expiryText = (request: RealRequest) => (request.expiresAt === null ? "Sin vencimiento" : `vence ${formatUtcDateTime(request.expiresAt)}`);
const kpi = (value: number | null) => (value === null ? NOT_AVAILABLE : formatInteger(value));

/** La bandeja REAL de /approvals (M47, Commit 6b): solo lo que el backend guarda. Sin severidad, sin solicitante ni fechas inventadas, sin
 * una sola fila de demostración. Cada fuente que no se pudo leer lo dice (y sus cifras pasan a «No disponible»): nunca «no hay nada». */
export function BackendInboxPanel({ inbox }: { inbox: RealInbox }) {
  const router = useRouter();
  const [filter, setFilter] = useState<RealFilter>("pending");
  const [sort, setSort] = useState<RealSort>("expiry");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const visible = useMemo(() => sortReal(filterReal(inbox.requests, filter), sort), [inbox.requests, filter, sort]);
  const selected = visible.find((request) => request.id === selectedId) ?? visible[0] ?? null;
  const notices = [inbox.sources.approvals, inbox.sources.reviews].flatMap((notice) => (notice === null ? [] : [notice]));
  const actionable = selected !== null && selected.status === "PENDING" && !selected.expired;

  async function act(action: "approve" | "reject") {
    if (selected === null || !actionable) return;
    setError(null);
    setPendingAction(action);
    try {
      if (selected.source === "approval") {
        if (action === "approve") await api.approveApproval(selected.id);
        else await api.rejectApproval(selected.id);
      } else if (action === "approve") await api.approvePipelineReview(selected.id);
      else await api.rejectPipelineReview(selected.id);
      router.refresh();
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 409
          ? "Esta solicitud ya no se puede accionar: se resolvió o venció."
          : "No se pudo registrar la decisión. Vuelve a intentarlo o revisa el estado del backend.",
      );
    } finally {
      setPendingAction(null);
    }
  }

  return (
    <div className="space-y-4" data-section="backend-inbox" data-inbox-state={inbox.state}>
      {notices.map((notice) => (
        <Alert key={notice.text} data-source-notice={notice.kind} variant={notice.kind === "error" ? "destructive" : "default"}>
          {notice.kind === "error" ? <AlertTriangle className="size-4" /> : <CircleDashed className="size-4" />}
          <AlertTitle>{notice.kind === "error" ? "No se pudo leer una fuente" : "Fuente sin leer"}</AlertTitle>
          <AlertDescription>
            {notice.text}
            {inbox.state === "partial" ? " Lo que se ve abajo es solo lo que sí se pudo leer; los recuentos no están disponibles." : ""}
          </AlertDescription>
        </Alert>
      ))}

      <section className="grid gap-3 sm:grid-cols-3" aria-label="Indicadores de la bandeja del backend">
        <KpiCard
          label="Pendientes"
          leading={<Inbox className="size-7 shrink-0 text-primary" />}
          value={kpi(inbox.kpis.pending)}
          caption={inbox.kpis.pending === null ? "Falta una fuente" : "Aprobaciones y revisiones sin resolver y sin vencer"}
        />
        <KpiCard
          label="Vencidas sin resolver"
          leading={<AlertTriangle className={cn("size-7 shrink-0", inbox.kpis.expired ? "text-destructive" : "text-primary")} />}
          value={kpi(inbox.kpis.expired)}
          tone={inbox.kpis.expired ? "danger" : "default"}
          caption="Ya no se pueden resolver"
        />
        <KpiCard
          label="Vencen en 4 h"
          leading={<Clock className="size-7 shrink-0 text-warning" />}
          value={kpi(inbox.kpis.expiringSoon)}
          tone={inbox.kpis.expiringSoon ? "warning" : "default"}
        />
      </section>

      {inbox.state === "empty" ? (
        <Card>
          <CardContent>
            <EmptyState
              icon={Inbox}
              title="No hay solicitudes"
              description="El backend respondió y no tiene aprobaciones ni revisiones. Cuando un agente pida autorizar un gasto o una ejecución de riesgo, aparecerá aquí."
            />
          </CardContent>
        </Card>
      ) : null}

      {inbox.state === "loaded" || inbox.state === "partial" ? (
        <>
          {error ? (
            <Alert variant="destructive">
              <AlertTriangle className="size-4" />
              <AlertTitle>No se pudo completar la operación</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}

          <div className="flex flex-wrap items-center justify-between gap-2">
            <Tabs value={filter} onValueChange={(value) => setFilter(value as RealFilter)}>
              <TabsList className="flex flex-wrap justify-start group-data-horizontal/tabs:h-auto">
                {REAL_FILTERS.map((item) => (
                  <TabsTrigger key={item.key} value={item.key} className="flex-none px-2.5 text-xs">
                    {item.label}
                    {inbox.state === "partial" ? "" : ` (${filterReal(inbox.requests, item.key).length})`}
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>
            <select
              value={sort}
              onChange={(event) => setSort(event.target.value as RealSort)}
              aria-label="Orden"
              className="min-w-0 rounded-md border bg-background px-2.5 py-1.5 text-xs"
            >
              {Object.entries(REAL_SORT_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </div>

          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
            <Card className="min-w-0">
              <CardContent className="space-y-2">
                {visible.length === 0 ? (
                  <p className="py-4 text-sm text-muted-foreground">
                    {inbox.state === "partial"
                      ? "Ninguna solicitud en la fuente que sí se pudo leer. Falta la otra: no se sabe si hay más."
                      : "Sin solicitudes con este filtro."}
                  </p>
                ) : (
                  <ul className="space-y-2">
                    {visible.map((request) => {
                      const status = statusOf(request);
                      return (
                        <li key={`${request.source}:${request.id}`} data-request={request.id} data-source={request.source}>
                          <button
                            type="button"
                            onClick={() => setSelectedId(request.id)}
                            aria-pressed={selected?.id === request.id}
                            className={cn(
                              "grid w-full grid-cols-[minmax(0,1fr)_auto] items-start gap-3 rounded-xl border p-3 text-left transition hover:border-primary/50",
                              selected?.id === request.id && "border-primary bg-primary/5",
                            )}
                          >
                            <span className="min-w-0">
                              <span className="flex flex-wrap items-center gap-2">
                                <span className="text-[15px] leading-tight font-medium [overflow-wrap:anywhere]">{request.title}</span>
                                <LevelChip tone={status.tone}>{status.text}</LevelChip>
                              </span>
                              <span className="block text-xs text-muted-foreground">{request.originLabel}</span>
                              <span className="block text-xs text-muted-foreground" data-field="requested">
                                {requestedText(request)}
                              </span>
                              <span className="block text-xs text-muted-foreground">{expiryText(request)}</span>
                            </span>
                            <span className="text-right text-xs">
                              <span className="block font-medium tabular-nums">{request.amount === null ? "—" : formatAmount(request.amount)}</span>
                              <span className="block text-muted-foreground">{request.amount === null ? "Sin importe" : "Importe"}</span>
                            </span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </CardContent>
            </Card>

            {selected ? (
              <div className="min-w-0 space-y-4" data-section="backend-detail">
                <Card className="min-w-0">
                  <CardHeader>
                    <CardTitle className="flex flex-wrap items-center gap-2 text-lg [overflow-wrap:anywhere]">
                      {selected.title}
                      <LevelChip tone={statusOf(selected).tone}>{statusOf(selected).text}</LevelChip>
                    </CardTitle>
                    <p className="text-xs text-muted-foreground">
                      {selected.originLabel} · ID {selected.code}
                    </p>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <dl className="grid gap-x-4 gap-y-1.5 text-sm sm:grid-cols-[auto_minmax(0,1fr)]">
                      {selected.fields.map((field) => (
                        <div key={field.label} className="contents">
                          <dt className="text-muted-foreground">{field.label}</dt>
                          <dd className="[overflow-wrap:anywhere]">{field.value}</dd>
                        </div>
                      ))}
                    </dl>
                    {selected.resolution.length > 0 ? (
                      <div data-section="resolution">
                        <p className="text-xs font-medium">Resultado</p>
                        <ul className="list-disc space-y-0.5 pl-4 text-xs text-muted-foreground">
                          {selected.resolution.map((line) => (
                            <li key={line}>{line}</li>
                          ))}
                        </ul>
                      </div>
                    ) : (
                      <div className="grid gap-3 sm:grid-cols-2" data-section="impact">
                        <div>
                          <p className="text-xs font-medium">Si se aprueba</p>
                          <ul className="list-disc space-y-0.5 pl-4 text-xs text-muted-foreground">
                            {selected.approveImpact.map((line) => (
                              <li key={line}>{line}</li>
                            ))}
                          </ul>
                        </div>
                        <div>
                          <p className="text-xs font-medium">Si se rechaza</p>
                          <ul className="list-disc space-y-0.5 pl-4 text-xs text-muted-foreground">
                            {selected.rejectImpact.map((line) => (
                              <li key={line}>{line}</li>
                            ))}
                          </ul>
                        </div>
                      </div>
                    )}
                  </CardContent>
                </Card>
                <div className="flex flex-wrap items-center justify-end gap-2">
                  {!actionable ? (
                    <p className="mr-auto text-[11px] text-muted-foreground">
                      {selected.expired ? "Vencida: el backend ya no deja resolverla." : "Ya está resuelta: no se puede accionar."}
                    </p>
                  ) : null}
                  <Button
                    variant="outline"
                    className="border-destructive/50 text-destructive"
                    disabled={!actionable || pendingAction !== null}
                    onClick={() => void act("reject")}
                  >
                    {pendingAction === "reject" ? <Loader2 className="animate-spin" /> : null}
                    Rechazar
                  </Button>
                  <Button disabled={!actionable || pendingAction !== null} onClick={() => void act("approve")}>
                    {pendingAction === "approve" ? <Loader2 className="animate-spin" /> : null}
                    Aprobar
                  </Button>
                </div>
              </div>
            ) : null}
          </div>
        </>
      ) : null}
    </div>
  );
}
