"use client";

import { useMemo, useState } from "react";
import {
  AlertTriangle,
  Bot,
  CircleCheck,
  Clock,
  Inbox,
  Megaphone,
  Package,
  Scale,
  ShoppingCart,
  Truck,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import type { Agent } from "@/lib/api";
import {
  INBOX_FILTERS,
  SORT_LABELS,
  countFor,
  demoRequests,
  filterRequests,
  hoursLeft,
  inboxKpis,
  requestsByKind,
  sortRequests,
  statusShares,
  type ApprovalRequest,
  type InboxFilter,
  type InboxSort,
} from "@/lib/approvals-view";
import type { RequestKind, Severity } from "@/lib/demo/approvals";
import { relativeTime } from "@/lib/dates";
import { formatEuro, formatInteger } from "@/lib/format";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { KpiCard } from "@/components/kpi-card";
import { LevelChip, type LevelTone } from "@/components/level-chip";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import type { ApprovalContextData } from "@/lib/approvals-reads";
import {
  AgentAnalysisCard,
  BudgetCard,
  CommentsCard,
  DocumentsCard,
  FindingsCard,
  FlowCard,
  ImpactCard,
  KindDonutCard,
  RequestFieldsCard,
  ResolutionTimeCard,
  StatusSharesCard,
  ValidationsCard,
} from "./approvals-panels";

const DEMO_TOOLTIP =
  "Incluye datos de demostración: una aprobación del backend solo guarda acción, importe, vencimiento y estado, sin tipo, severidad, proyecto, agente solicitante, análisis, documentos ni impacto, y hoy la bandeja está vacía. Del backend: las aprobaciones y revisiones de pipeline cuando existan (con sus botones de aprobar y rechazar), los agentes registrados y los análisis del producto que alimentan validaciones, hallazgos y riesgos.";

const KIND_ICON: Record<RequestKind, LucideIcon> = {
  marketing: Megaphone,
  suppliers: Package,
  operations: Truck,
  commerce: ShoppingCart,
  agents: Bot,
  legal: Scale,
  finance: Wallet,
};

const SEVERITY_TONE: Record<Severity, LevelTone> = { "Crítica": "bad", Alta: "warn", Media: "neutral", Baja: "ok" };

const DETAIL_TABS = [
  { key: "resumen", label: "Resumen" },
  { key: "agentes", label: "Análisis de agentes" },
  { key: "documentos", label: "Documentos" },
  { key: "flujo", label: "Flujo de aprobación" },
  { key: "comentarios", label: "Comentarios" },
] as const;

type DetailTab = (typeof DETAIL_TABS)[number]["key"];

const INPUT_CLASS = "min-w-0 rounded-md border bg-background px-2.5 py-1.5 text-xs";

/** La DEMOSTRACIÓN de /approvals (M47, Commit 6b): la bandeja de ejemplo del mockup, sobre productos y análisis reales pero con solicitudes,
 * severidades, solicitantes, validaciones, documentos, comentarios e indicadores INVENTADOS. Vive aparte de la bandeja real: no comparte
 * lista, indicadores ni detalle con ella, no se puede aprobar ni rechazar nada, y todo lo que enseña está rotulado «Datos de demostración». */
export function DemoInbox({ agents, context, notice, now }: { agents: Agent[]; context: ApprovalContextData[]; notice: string | null; now: number }) {
  const [filter, setFilter] = useState<InboxFilter>("pending");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<InboxSort>("recent");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detailTab, setDetailTab] = useState<DetailTab>("resumen");

  // El producto con más análisis es el que ilustra las solicitudes de demostración.
  const best = useMemo(() => [...context].sort((a, b) => b.depth - a.depth)[0], [context]);

  const requests = useMemo<ApprovalRequest[]>(() => demoRequests(best, agents, now), [best, agents, now]);

  const kpis = inboxKpis(requests, now);
  const visible = sortRequests(filterRequests(requests, { filter, query }), sort);
  const selected = requests.find((request) => request.id === selectedId) ?? visible[0] ?? requests[0];

  return (
    <div className="space-y-5">
      <div className="space-y-2" data-section="demo-banner">
        <div className="flex flex-wrap items-center gap-2">
          <DataProvenanceBadge status="demo" tooltip={DEMO_TOOLTIP} />
          <p className="text-sm font-medium">Datos de demostración</p>
        </div>
        <p className="text-xs text-muted-foreground">
          Esta pestaña es un ejemplo del diseño: las solicitudes, severidades, solicitantes, análisis, documentos, comentarios e indicadores de aquí
          NO existen en el backend y no se pueden aprobar ni rechazar. Las del backend están en la pestaña «Solicitudes del backend».
        </p>
        {notice ? (
          <p data-section="demo-context-notice" className="text-xs text-muted-foreground">
            {notice}
          </p>
        ) : null}
      </div>

      {/* KPIs */}
      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-5" aria-label="Indicadores de la bandeja">
        <KpiCard label="Pendientes" leading={<Inbox className="size-7 shrink-0 text-primary" />} value={formatInteger(kpis.pending)} />
        <KpiCard
          label="Críticas"
          leading={<AlertTriangle className={cn("size-7 shrink-0", kpis.critical > 0 ? "text-destructive" : "text-primary")} />}
          value={formatInteger(kpis.critical)}
          tone={kpis.critical > 0 ? "danger" : "default"}
        />
        <KpiCard label="Vencen pronto" leading={<Clock className="size-7 shrink-0 text-warning" />} value={formatInteger(kpis.expiringSoon)} tone={kpis.expiringSoon > 0 ? "warning" : "default"} />
        <KpiCard label="Aprobadas hoy" leading={<CircleCheck className="size-7 shrink-0 text-primary" />} value={formatInteger(kpis.approvedToday)} caption="Dato de demostración" />
        <KpiCard label="Tiempo medio" leading={<Clock className="size-7 shrink-0 text-primary" />} value={`${kpis.averageMinutes} min`} caption="Dato de demostración" />
      </section>

      {/* Filtros */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Tabs value={filter} onValueChange={(value) => setFilter(value as InboxFilter)}>
          <TabsList className="flex flex-wrap justify-start group-data-horizontal/tabs:h-auto">
            {INBOX_FILTERS.map((item) => (
              <TabsTrigger key={item.key} value={item.key} className="flex-none px-2.5 text-xs">
                {item.label} ({countFor(requests, item.key)})
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        <div className="flex flex-wrap items-center gap-2">
          <select value={sort} onChange={(e) => setSort(e.target.value as InboxSort)} aria-label="Orden" className={INPUT_CLASS}>
            {Object.entries(SORT_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            type="search"
            placeholder="Buscar solicitud…"
            aria-label="Buscar solicitud"
            className={cn(INPUT_CLASS, "w-48")}
          />
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
        {/* Bandeja */}
        <div className="min-w-0 space-y-4">
          <Card className="min-w-0">
            <CardContent className="space-y-2">
              {visible.length === 0 ? (
                <p className="py-4 text-sm text-muted-foreground">Sin solicitudes con estos filtros.</p>
              ) : (
                <ul className="space-y-2">
                  {visible.map((request) => {
                    const Icon = KIND_ICON[request.kind];
                    const left = hoursLeft(request, now);
                    return (
                      <li key={request.id}>
                        <button
                          type="button"
                          onClick={() => {
                            setSelectedId(request.id);
                            setDetailTab("resumen");
                          }}
                          aria-pressed={selected?.id === request.id}
                          className={cn(
                            "grid w-full grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 rounded-xl border p-3 text-left transition hover:border-primary/50",
                            selected?.id === request.id && "border-primary bg-primary/5",
                          )}
                        >
                          <span className="flex size-10 shrink-0 items-center justify-center rounded-xl border border-primary/30 bg-primary/10 text-primary">
                            <Icon className="size-5" />
                          </span>
                          <span className="min-w-0">
                            <span className="flex flex-wrap items-center gap-2">
                              <span className="text-[15px] leading-tight font-medium">{request.title}</span>
                              <LevelChip tone={SEVERITY_TONE[request.severity]}>{request.severity}</LevelChip>
                            </span>
                            <span className="block text-xs text-muted-foreground">
                              {[request.projectCode, request.productName].filter(Boolean).join(" · ") || request.kindLabel}
                            </span>
                            <span className="block text-xs text-muted-foreground">{request.requestedBy}</span>
                          </span>
                          <span className="text-right text-xs">
                            <span className="block font-medium tabular-nums">
                              {request.amount === null ? "—" : formatEuro(request.amount, 0)}
                            </span>
                            <span className="block text-muted-foreground">{request.amountLabel}</span>
                            <span className={cn("block", left < 4 ? "text-warning" : "text-muted-foreground")}>
                              {relativeTime(request.requestedAt, now)}
                            </span>
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </CardContent>
          </Card>

          <div className="grid gap-4 sm:grid-cols-2 min-[106.25rem]:grid-cols-3">
            <KindDonutCard rows={requestsByKind(requests)} />
            <StatusSharesCard rows={statusShares(requests)} />
            <ResolutionTimeCard minutes={kpis.averageMinutes} />
          </div>

        </div>

        {/* Detalle */}
        <div className="min-w-0 space-y-4">
          {selected ? (
            <>
              <Card className="min-w-0">
                <CardContent className="space-y-3">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="flex min-w-0 gap-3">
                      <span className="flex size-12 shrink-0 items-center justify-center rounded-xl border border-primary/30 bg-primary/10 text-primary">
                        {(() => {
                          const Icon = KIND_ICON[selected.kind];
                          return <Icon className="size-6" />;
                        })()}
                      </span>
                      <div className="min-w-0">
                        <p className="flex flex-wrap items-center gap-2 text-xl leading-tight font-semibold">
                          {selected.title}
                          <LevelChip tone={SEVERITY_TONE[selected.severity]}>{selected.severity}</LevelChip>
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {[selected.projectCode, selected.productName].filter(Boolean).join(" · ") || selected.kindLabel}
                        </p>
                        <p className="text-xs text-muted-foreground">Solicitada por: {selected.requestedBy}</p>
                      </div>
                    </div>
                    <div className="text-right text-xs text-muted-foreground">
                      <p>ID solicitud: {selected.code}</p>
                      <p>{relativeTime(selected.requestedAt, now)}</p>
                      {selected.isDemo ? (
                        <DataProvenanceBadge status="demo" compact tooltip="Solicitud de demostración: no se puede aprobar ni rechazar." />
                      ) : null}
                    </div>
                  </div>

                  <Tabs value={detailTab} onValueChange={(value) => setDetailTab(value as DetailTab)}>
                    <TabsList className="flex w-full flex-wrap justify-start group-data-horizontal/tabs:h-auto">
                      {DETAIL_TABS.map((item) => (
                        <TabsTrigger key={item.key} value={item.key} className="flex-none px-2.5 text-xs">
                          {item.label}
                        </TabsTrigger>
                      ))}
                    </TabsList>
                  </Tabs>
                </CardContent>
              </Card>

              {detailTab === "resumen" ? (
                <>
                  <div className="grid gap-4 md:grid-cols-2 min-[106.25rem]:grid-cols-3">
                    <RequestFieldsCard request={selected} />
                    <ValidationsCard validations={selected.validations} />
                    {selected.budget ? <BudgetCard budget={selected.budget} /> : <ImpactCard request={selected} />}
                  </div>
                  <div className="grid gap-4 md:grid-cols-2 min-[106.25rem]:grid-cols-3">
                    <AgentAnalysisCard request={selected} />
                    <FindingsCard request={selected} />
                    {selected.budget ? <ImpactCard request={selected} /> : <FlowCard request={selected} />}
                  </div>
                </>
              ) : null}
              {detailTab === "agentes" ? <AgentAnalysisCard request={selected} /> : null}
              {detailTab === "documentos" ? <DocumentsCard /> : null}
              {detailTab === "flujo" ? <FlowCard request={selected} /> : null}
              {detailTab === "comentarios" ? <CommentsCard request={selected} /> : null}

              <div className="flex flex-wrap items-center justify-end gap-2">
                {selected.isDemo ? (
                  <p className="mr-auto text-[11px] text-muted-foreground">
                    Solicitud de demostración: aprobar o rechazar solo funciona con las aprobaciones del backend.
                  </p>
                ) : null}
                <Button
                  variant="outline"
                  className="border-destructive/50 text-destructive"
                  disabled
                  title="Solicitud de demostración"
                >
                  Rechazar
                </Button>
                <Button variant="outline" disabled title="Pendiente: el backend no admite pedir cambios">
                  Solicitar cambios
                </Button>
                <Button
                  disabled
                  title="Solicitud de demostración"
                >
                  Aprobar
                </Button>
              </div>
            </>
          ) : null}
        </div>
      </div>

      <p className="text-[11px] text-muted-foreground">
        Todas las solicitudes de esta pestaña son de demostración, construidas sobre productos y análisis del backend.
      </p>
    </div>
  );
}
