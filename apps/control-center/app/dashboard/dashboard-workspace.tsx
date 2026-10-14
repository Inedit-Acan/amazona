"use client";

import { useMemo } from "react";
import Link from "next/link";
import { Bot, ClipboardCheck, Coins, Plus, ReceiptText, Scale } from "lucide-react";
import type { RevenueEntriesPage, RevenueSeries, RevenueSummary } from "@/lib/api";
import { demoRequests } from "@/lib/approvals-view";
import type { DashboardReads } from "@/lib/dashboard-reads";
import {
  activityView,
  agentsKpiView,
  decisionRows,
  decisionsKpiView,
  decisionsView,
  demoContext,
  opportunitiesView,
  readIssues,
} from "@/lib/dashboard-view";
import { listOf } from "@/lib/read-state";
import { type RevenueWindow } from "@/lib/revenue-query";
import { periodLabel, revenueKpis, type KpiText, type Settled } from "@/lib/revenue-view";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { HeaderClock } from "@/components/header-clock";
import { KpiCard } from "@/components/kpi-card";
import { PageHeader } from "@/components/page-header";
import { ReadErrorNotice } from "@/components/read-error-notice";
import { PeriodSelect } from "@/components/period-select";
import { Button } from "@/components/ui/button";
import { DASHBOARD_DESCRIPTION, DASHBOARD_TITLE } from "./copy";
import { ActivityCard, DecisionsCard, OpportunitiesCard } from "./dashboard-panels";
import { OutsideVerifiedCard, RevenueBreakdownCard, RevenueEntriesCard, RevenueSeriesCard } from "./revenue-panels";

const DEMO_TOOLTIP =
  "Incluye datos de demostración: la tarea en curso de cada agente, las solicitudes de decisión que no vienen del backend y las señales de mercado de las oportunidades. Del backend: los ingresos (de su registro de hechos de pago verificados), los productos del catálogo y sus análisis, los agentes registrados con su estado, el log de ejecuciones y las aprobaciones y revisiones de pipeline pendientes. El Panel ya no enseña ventas ni beneficio modelados: el margen y el beneficio esperan a una fuente que el backend pueda demostrar (Finanzas).";

/** Qué demuestra el backend detrás de las cifras de ingresos, y qué NO demuestra. */
const LEDGER_TOOLTIP =
  "Hechos de pago verificados y registrados por el backend (ADR 0030): no es un modelo ni una estimación. Cada cifra lleva el origen (provider_kind) que el backend guardó en el hecho; un hecho verificado no es dinero liquidado.";

const ACTIVITY_LIMIT = 5;
const DECISION_LIMIT = 4;
const OPPORTUNITY_LIMIT = 5;

/** Barras de ejecuciones por día (los siete días de la tarjeta de agentes). */
function RunBars({ values }: { values: number[] }) {
  const max = Math.max(1, ...values);
  return (
    <span className="flex h-7 shrink-0 items-end gap-0.5" aria-hidden>
      {values.map((value, index) => (
        <span key={index} className="w-1.5 rounded-sm bg-primary" style={{ height: `${Math.max(8, (value / max) * 100)}%` }} />
      ))}
    </span>
  );
}

const iconBox = (icon: React.ReactNode) => (
  <span className="flex size-10 shrink-0 items-center justify-center rounded-lg border bg-background/40">{icon}</span>
);

/** Una cifra de ingresos: el valor y su pie salen tal cual de `lib/revenue-view.ts`; si la lectura falló, se dice. */
function RevenueKpi({
  label,
  icon,
  summary,
  pick,
  tooltip,
  accent = false,
  tone = "default",
}: {
  label: string;
  icon: React.ReactNode;
  summary: Settled<RevenueSummary>;
  pick: (kpis: ReturnType<typeof revenueKpis>) => KpiText;
  tooltip: string;
  accent?: boolean;
  tone?: "default" | "warning";
}) {
  if (!summary.ok) {
    return <KpiCard label={label} value="No disponible" leading={iconBox(icon)} caption={summary.message} tone="danger" />;
  }
  const text = pick(revenueKpis(summary.data));
  return (
    <KpiCard
      label={label}
      value={text.value}
      leading={iconBox(icon)}
      caption={text.caption}
      accent={accent && !text.isNoData}
      tone={tone}
      provenance="ledger"
      provenanceCompact
      provenanceTooltip={tooltip}
    />
  );
}

export function DashboardWorkspace({
  reads,
  now,
  days,
  revenue,
}: {
  /** Las lecturas del Panel, cada una con su estado (`loaded` / `empty` / `unread` / `error`). */
  reads: DashboardReads;
  now: number;
  /** Periodo de los ingresos (7, 14 o 30 días): lo elige la URL y lo lee el servidor. */
  days: number;
  revenue: {
    window: RevenueWindow;
    summary: Settled<RevenueSummary>;
    series: Settled<RevenueSeries>;
    entries: Settled<RevenueEntriesPage>;
  };
}) {
  // Mismo criterio que Agentes: si el log es VÁLIDO y está vacío se usan las ejecuciones de demostración. Un log que no se
  // pudo leer NO es un log vacío: se dice (`activity.kind === "unavailable"`) y no se sustituye por demostración.
  const activity = useMemo(
    () => activityView({ agents: reads.agents, executions: reads.executions, now, limit: ACTIVITY_LIMIT }),
    [reads.agents, reads.executions, now],
  );

  // Mismas solicitudes que Aprobaciones: las reales primero y las de demostración sobre el producto más avanzado. Si una de
  // las lecturas del backend falló no hay lista parcial ni conteo (`decisions.kind === "unavailable"`).
  const demo = useMemo(
    () => (reads.agents.kind === "loaded" || reads.agents.kind === "empty" ? demoRequests(demoContext(reads.catalog), listOf(reads.agents) ?? [], now) : []),
    [reads.agents, reads.catalog, now],
  );
  const decisions = useMemo(
    () => decisionsView({ approvals: reads.approvals, reviews: reads.reviews, demo, now }),
    [reads.approvals, reads.reviews, demo, now],
  );
  const decisionList = useMemo(
    () => (decisions.kind === "ready" ? decisionRows(decisions.requests, DECISION_LIMIT) : []),
    [decisions],
  );

  // El margen es el mismo que enseña Economía: el del modelo sobre los supuestos del producto. Es una ESTIMACIÓN del modelo,
  // no un margen medido; y si el producto no se pudo leer, el margen y la fase se dicen como no disponibles.
  const opportunities = useMemo(
    () => opportunitiesView({ products: reads.products, catalog: reads.catalog, limit: OPPORTUNITY_LIMIT }),
    [reads.products, reads.catalog],
  );

  const agentsKpi = useMemo(() => agentsKpiView(reads.agents, reads.executions), [reads.agents, reads.executions]);
  const decisionsKpi = useMemo(() => decisionsKpiView(decisions), [decisions]);
  const issues = useMemo(() => readIssues(reads, revenue), [reads, revenue]);

  const period = periodLabel(days);

  return (
    <div className="space-y-4">
      <PageHeader
        title={DASHBOARD_TITLE}
        description={DASHBOARD_DESCRIPTION}
        actions={
          <>
            <DataProvenanceBadge status="ledger" tooltip={LEDGER_TOOLTIP} />
            <DataProvenanceBadge status="demo" tooltip={DEMO_TOOLTIP} />
            <PeriodSelect days={days} />
            <HeaderClock />
            <Button nativeButton={false} render={<Link href="/ceo" />}>
              <Plus /> Nuevo objetivo
            </Button>
          </>
        }
      />

      {issues.length > 0 ? (
        <ReadErrorNotice
          title="Algunos datos no están disponibles en este momento"
          message={`No se pudieron cargar: ${issues.map((issue) => issue.label).join(", ")}. Las cifras de esas secciones no se muestran hasta que la lectura funcione; no se han sustituido por datos de demostración ni por un cero.`}
        />
      ) : null}

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5" aria-label="Indicadores del negocio">
        <RevenueKpi
          label={`Ingresos verificados · ${period}`}
          icon={<Coins className="size-5 text-primary" />}
          summary={revenue.summary}
          pick={(k) => k.verified}
          accent
          tooltip="Cobros verificados del registro de ingresos, en EUR (la única moneda consolidada). Otras monedas se enseñan aparte y nunca se suman. Sin entradas en EUR el valor es «Sin datos», no 0."
        />
        <RevenueKpi
          label={`En revisión · ${period}`}
          icon={<Scale className="size-5 text-primary" />}
          summary={revenue.summary}
          pick={(k) => k.underReview}
          tone="warning"
          tooltip="Dinero recibido como duplicado o con discrepancia y aún sin resolver, en EUR. No suma a lo verificado ni se compensa con ello."
        />
        <RevenueKpi
          label={`Evidencia pendiente · ${period}`}
          icon={<ReceiptText className="size-5 text-primary" />}
          summary={revenue.summary}
          pick={(k) => k.pending}
          tooltip="Eventos de pago (cobros o reembolsos) que no se pudieron asentar. No son ingreso ni reembolso y no entran en ningún total."
        />
        {agentsKpi.kind === "error" || agentsKpi.kind === "unread" ? (
          <KpiCard
            label="Agentes operativos"
            value={agentsKpi.value}
            leading={iconBox(<Bot className="size-5 text-primary" />)}
            caption={agentsKpi.caption}
            tone={agentsKpi.kind === "error" ? "danger" : "default"}
          />
        ) : (
          <KpiCard
            label="Agentes operativos"
            value={agentsKpi.value}
            leading={iconBox(<Bot className="size-5 text-primary" />)}
            trailing={activity.kind === "rows" ? <RunBars values={activity.runsPerDay} /> : undefined}
            caption={agentsKpi.caption}
            provenance="recorded"
            provenanceCompact
            provenanceTooltip="Agentes del registro cuyo estado es Disponible, Ejecutando o En espera. «Operativo» es una clasificación de esta interfaz, no un estado del backend, y no mide conectividad: un agente Bloqueado, Degradado, Deshabilitado o Fallido no cuenta. Las barras son sus ejecuciones de los últimos siete días."
          />
        )}
        {decisionsKpi.kind === "error" || decisionsKpi.kind === "unread" ? (
          <KpiCard
            label="Aprobaciones pendientes"
            value={decisionsKpi.value}
            leading={iconBox(<ClipboardCheck className="size-5 text-primary" />)}
            caption={decisionsKpi.caption}
            tone={decisionsKpi.kind === "error" ? "danger" : "default"}
          />
        ) : (
          <KpiCard
            label="Aprobaciones pendientes"
            value={decisionsKpi.value}
            leading={iconBox(<ClipboardCheck className="size-5 text-primary" />)}
            tone={decisions.kind === "ready" && decisions.pending > 0 ? "warning" : "default"}
            caption={decisionsKpi.caption}
            footer={
              <Button size="sm" variant="ghost" nativeButton={false} render={<Link href="/approvals" />}>
                Revisar
              </Button>
            }
            provenance={decisions.kind === "ready" && decisions.fromBackend === decisions.pending ? "recorded" : "demo"}
            provenanceCompact
            provenanceTooltip="Solicitudes pendientes de decisión: las del backend (aprobaciones y revisiones de pipeline) más las de demostración de Aprobaciones."
          />
        )}
      </section>

      <section className="grid gap-3 lg:grid-cols-2 2xl:grid-cols-12" aria-label="Actividad y decisiones">
        <div className="min-w-0 2xl:col-span-7">
          <ActivityCard view={activity} now={now} />
        </div>
        <div className="min-w-0 2xl:col-span-5">
          <DecisionsCard view={decisions} rows={decisionList} now={now} />
        </div>
      </section>

      <section className="grid gap-3 lg:grid-cols-2" aria-label="Oportunidades e ingresos por día">
        <OpportunitiesCard view={opportunities} />
        <RevenueSeriesCard key={revenue.window.from} series={revenue.series} window={revenue.window} days={days} />
      </section>

      <section className="grid gap-3 lg:grid-cols-2" aria-label="Ingresos por moneda y dinero fuera de lo verificado">
        <RevenueBreakdownCard summary={revenue.summary} days={days} />
        <OutsideVerifiedCard summary={revenue.summary} days={days} />
      </section>

      <section aria-label="Entradas del registro de ingresos">
        <RevenueEntriesCard key={revenue.window.from} initial={revenue.entries} window={revenue.window} days={days} />
      </section>
    </div>
  );
}
