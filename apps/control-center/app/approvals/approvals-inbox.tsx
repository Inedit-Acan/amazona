"use client";

import { useMemo, useState } from "react";
import { ChevronRight, Clock, Inbox, Search, ShieldCheck, TimerReset, Workflow, CheckCheck, Siren } from "lucide-react";
import { formatAmount, formatInteger } from "@/lib/format";
import {
  decisionImpact,
  entryAmount,
  entryStatus,
  entryTitle,
  expiryLabel,
  inboxStats,
  isEntryPending,
  sortInbox,
  type InboxEntry,
} from "@/lib/approvals";
import { ApprovalCard } from "@/components/approval-card";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { EmptyState } from "@/components/empty-state";
import { KpiCard } from "@/components/kpi-card";
import { PendingFeatures, type PendingFeature } from "@/components/pending-features";
import { PipelineReviewCard } from "@/components/pipeline-review-card";
import { ProjectHealth } from "@/components/project-health";
import { StatusChip } from "@/components/status-chip";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type Filter = "pending" | "decided" | "all";

const PENDING_DECISION_TOOLS: PendingFeature[] = [
  {
    icon: Workflow,
    title: "Cadena de aprobación y separación de funciones",
    description: "Quién debe aprobar en cada paso y que quien solicita no apruebe. Hoy hay un único aprobador.",
  },
  {
    icon: ShieldCheck,
    title: "Guardrails condicionados",
    description: "Aprobar solo dentro de límites (presupuesto, CAC, mercado, duración); si algo cambia, nueva aprobación.",
  },
  {
    icon: Clock,
    title: "Presupuesto visible, documentos y comentarios",
    description: "Asignado, gastado, comprometido y disponible antes de aprobar, más documentos y conversación.",
  },
  {
    icon: TimerReset,
    title: "Solicitar cambios y motivo de rechazo",
    description: "Pedir cambios sin rechazar y exigir un motivo al rechazar, que alimente a los agentes.",
  },
];

const FILTER_LABEL: Record<Filter, string> = { pending: "Pendientes", decided: "Decididas", all: "Todas" };

function entrySubtitle(entry: InboxEntry): string {
  if (entry.kind === "approval") return entry.project?.name ?? "Proyecto desconocido";
  return `Ejecución ${entry.review.pipeline_run_id.slice(0, 8)}`;
}

export function ApprovalsInbox({ entries }: { entries: InboxEntry[] }) {
  // Se fija una vez: mantiene el render puro y estable; router.refresh() trae entradas nuevas.
  const [now] = useState(() => new Date());
  const [filter, setFilter] = useState<Filter>("pending");
  const [query, setQuery] = useState("");
  const [actionFilter, setActionFilter] = useState("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const sorted = useMemo(() => sortInbox(entries, now), [entries, now]);
  const stats = useMemo(() => inboxStats(entries, now), [entries, now]);
  const actionOptions = useMemo(
    () => [...new Set(entries.map(entryTitle))].sort((a, b) => a.localeCompare(b, "es")),
    [entries],
  );

  const visible = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return sorted.filter((entry) => {
      const pending = isEntryPending(entry, now);
      if (filter === "pending" && !pending) return false;
      if (filter === "decided" && pending) return false;
      if (actionFilter !== "all" && entryTitle(entry) !== actionFilter) return false;
      if (!normalized) return true;
      return `${entryTitle(entry)} ${entrySubtitle(entry)}`.toLowerCase().includes(normalized);
    });
  }, [sorted, filter, actionFilter, query, now]);

  const selected =
    entries.find((e) => e.id === selectedId) ?? visible[0] ?? sorted.find((e) => isEntryPending(e, now)) ?? sorted[0];

  if (entries.length === 0) {
    return (
      <Card>
        <CardContent>
          <EmptyState
            icon={Inbox}
            title="Todavía no hay solicitudes"
            description="Cuando el director ejecutivo o el pipeline necesiten una decisión humana, aparecerán aquí."
          />
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5" aria-label="Indicadores de la bandeja">
        <KpiCard
          label="Pendientes"
          value={formatInteger(stats.pending)}
          icon={Inbox}
          tone={stats.pending > 0 ? "warning" : "default"}
          caption="Aprobaciones y revisiones por decidir"
          provenance="verified"
        />
        <KpiCard
          label="Críticas"
          value="—"
          icon={Siren}
          caption="Las solicitudes no tienen criticidad"
          provenance="pending"
          provenanceTooltip="El backend no clasifica las solicitudes por prioridad (crítica, alta, media, baja)."
        />
        <KpiCard
          label="Vencen en 24 h"
          value={formatInteger(stats.expiringSoon)}
          icon={Clock}
          tone={stats.expiringSoon > 0 ? "danger" : "default"}
          caption="Pendientes que caducan pronto"
          provenance="verified"
          provenanceTooltip="Aprobaciones pendientes cuya fecha de vencimiento cae en las próximas 24 horas."
        />
        <KpiCard
          label="Aprobadas hoy"
          value={formatInteger(stats.approvedToday)}
          icon={CheckCheck}
          caption="Resueltas como aprobadas hoy"
          provenance="verified"
        />
        <KpiCard
          label="Tiempo medio"
          value="—"
          icon={TimerReset}
          caption="No se guarda cuándo se solicitó"
          provenance="pending"
          provenanceTooltip="La aprobación no devuelve la fecha de solicitud, así que no se puede medir el tiempo de resolución."
        />
      </section>

      <div className="grid gap-4 xl:grid-cols-12">
        <Card className="xl:col-span-5">
          <CardHeader>
            <CardTitle>Bandeja</CardTitle>
            <CardAction>
              <DataProvenanceBadge status="verified" tooltip="Aprobaciones de gasto y revisiones de pipeline guardadas en la base de datos." />
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap gap-2" role="group" aria-label="Filtrar solicitudes">
              {(Object.keys(FILTER_LABEL) as Filter[]).map((key) => {
                const count = key === "pending" ? stats.pending : key === "decided" ? stats.decided : stats.total;
                return (
                  <Button
                    key={key}
                    type="button"
                    size="sm"
                    variant={filter === key ? "secondary" : "outline"}
                    aria-pressed={filter === key}
                    onClick={() => setFilter(key)}
                  >
                    {FILTER_LABEL[key]} <span className="tabular-nums text-muted-foreground">{count}</span>
                  </Button>
                );
              })}
              <Button type="button" size="sm" variant="outline" disabled title="Pendiente: no hay reglas de aprobación configurables">
                Reglas
              </Button>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <label className="relative block min-w-0 flex-1">
                <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
                <input
                  type="search"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Buscar solicitud…"
                  aria-label="Buscar solicitud"
                  className="w-full rounded-md border bg-background py-1.5 pr-3 pl-9 text-sm"
                />
              </label>
              <select
                value={actionFilter}
                onChange={(e) => setActionFilter(e.target.value)}
                aria-label="Filtrar por tipo"
                className="rounded-md border bg-background px-3 py-1.5 text-sm"
              >
                <option value="all">Todos los tipos</option>
                {actionOptions.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </div>

            {visible.length === 0 ? (
              <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
                {filter === "pending" ? "No hay solicitudes pendientes." : "Ninguna solicitud coincide con el filtro."}
              </p>
            ) : (
              <ul className="space-y-2">
                {visible.map((entry) => {
                  const active = selected?.id === entry.id;
                  const amount = entryAmount(entry);
                  const pending = isEntryPending(entry, now);
                  return (
                    <li key={entry.id}>
                      <button
                        type="button"
                        onClick={() => setSelectedId(entry.id)}
                        aria-current={active ? "true" : undefined}
                        className={cn(
                          "flex w-full items-center gap-3 rounded-lg border p-3 text-left transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                          active ? "border-primary bg-primary/5" : "bg-background/40 hover:bg-muted/50",
                        )}
                      >
                        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg border bg-muted text-primary">
                          {entry.kind === "approval" ? <ShieldCheck className="size-4" /> : <Workflow className="size-4" />}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-medium">{entryTitle(entry)}</span>
                          <span className="block truncate text-xs text-muted-foreground">{entrySubtitle(entry)}</span>
                        </span>
                        <span className="shrink-0 space-y-1 text-right">
                          {amount != null && amount > 0 ? (
                            <span className="block text-sm font-medium tabular-nums">{formatAmount(amount)}</span>
                          ) : null}
                          {pending ? (
                            <span className="block text-[11px] text-muted-foreground">
                              {entry.kind === "approval" ? expiryLabel(entry.approval.expires_at, now) : "Pendiente"}
                            </span>
                          ) : (
                            <StatusChip status={entryStatus(entry, now)} />
                          )}
                        </span>
                        <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
            <p className="text-[11px] text-muted-foreground">
              Las revisiones de pipeline ya resueltas no aparecen aquí: el backend solo lista las pendientes. Las
              aprobaciones de gasto se conservan con su estado.
            </p>
          </CardContent>
        </Card>

        <div className="space-y-4 xl:col-span-7" aria-label="Detalle de la solicitud">
          {selected ? (
            selected.kind === "approval" ? (
              <>
                <ApprovalCard
                  key={`${selected.approval.id}:${selected.approval.status}`}
                  approval={selected.approval}
                  decision={selected.decision}
                  project={selected.project}
                />
                <div className="grid gap-4 md:grid-cols-2">
                  <Card>
                    <CardHeader>
                      <CardTitle>Estado de las validaciones</CardTitle>
                      <CardAction>
                        <DataProvenanceBadge status="verified" tooltip="Recomendación real de cada especialista en la decisión del director ejecutivo." />
                      </CardAction>
                    </CardHeader>
                    <CardContent>
                      <ProjectHealth decision={selected.decision} />
                    </CardContent>
                  </Card>
                  <Card>
                    <CardHeader>
                      <CardTitle>Impacto de la decisión</CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      {(() => {
                        const impact = decisionImpact(selected.approval);
                        return (
                          <>
                            <div className="rounded-lg border border-primary/40 bg-primary/5 p-3">
                              <p className="mb-1 text-sm font-semibold text-primary">Si apruebas</p>
                              <ul className="list-inside list-disc space-y-0.5 text-xs">
                                {impact.approve.map((line) => (
                                  <li key={line}>{line}</li>
                                ))}
                              </ul>
                            </div>
                            <div className="rounded-lg border border-red-500/40 bg-red-500/5 p-3">
                              <p className="mb-1 text-sm font-semibold text-red-500">Si rechazas</p>
                              <ul className="list-inside list-disc space-y-0.5 text-xs">
                                {impact.reject.map((line) => (
                                  <li key={line}>{line}</li>
                                ))}
                              </ul>
                            </div>
                          </>
                        );
                      })()}
                    </CardContent>
                  </Card>
                </div>
              </>
            ) : (
              <PipelineReviewCard key={`${selected.review.id}:${selected.review.status}`} review={selected.review} />
            )
          ) : (
            <Card>
              <CardContent>
                <EmptyState icon={Inbox} title="Elige una solicitud" description="Selecciona una de la bandeja para ver su detalle." />
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      <PendingFeatures
        title="Human Decision Center — pendiente de backend"
        tooltip="Requieren un modelo de política de aprobación (cadena, límites, roles y reglas) que el backend aún no tiene."
        items={PENDING_DECISION_TOOLS}
        columns={4}
        note="Hoy cada aprobación autoriza una sola acción con un importe, la resuelve un único aprobador y no guarda motivo ni criticidad. No hay reglas de autoaprobación, Workflow Builder ni simulador de políticas."
      />
    </div>
  );
}
