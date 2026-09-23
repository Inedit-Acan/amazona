"use client";

import { useMemo, useState } from "react";
import {
  AlertTriangle,
  Bot,
  CircleDollarSign,
  Gauge,
  Landmark,
  Megaphone,
  Pause,
  Play,
  Plus,
  Scale,
  Search,
  ShoppingCart,
  Sparkles,
  Truck,
  type LucideIcon,
} from "lucide-react";
import type { Agent, AgentExecution } from "@/lib/api";
import { TEAMS, runsByTeam, teamOf, type Team } from "@/lib/agents";
import { demoExecutions } from "@/lib/demo/agents";
import {
  activityFeed,
  agentCards,
  costByAgent,
  filterCards,
  fleetAlerts,
  fleetKpis,
  groupCards,
  sortCards,
  usageByDay,
  SORT_LABELS,
  type SortKey,
} from "@/lib/agents-view";
import { formatEuro, formatInteger, formatPercent } from "@/lib/format";
import { AgentCard } from "@/components/agent-card";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { EmptyState } from "@/components/empty-state";
import { KpiCard } from "@/components/kpi-card";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { AGENTS_DESCRIPTION, AGENTS_TITLE } from "./copy";
import {
  ActivityTable,
  CostByAgentCard,
  DistributionCard,
  EvaluationsTable,
  FleetAlertsCard,
  PerformanceTable,
  RealtimeActivityCard,
  ResourcesCard,
  UsageCard,
  VersionsTable,
} from "./agents-panels";

const DEMO_TOOLTIP =
  "Incluye datos de demostración: el registro de agentes no guarda descripción, evaluaciones, coste por ejecución (devuelve 0), tarea en curso, herramientas ni histórico de versiones. Real: los agentes registrados con su rol, capacidades, estado y versión, y el log de ejecuciones, de donde salen la tasa de éxito, la latencia, la actividad, la distribución por equipo y las alertas.";

const TEAM_ICON: Record<Team, LucideIcon> = {
  Investigación: Search,
  Abastecimiento: Truck,
  Economía: Gauge,
  Legal: Scale,
  Comercio: ShoppingCart,
  Marketing: Megaphone,
  Operaciones: Truck,
  Finanzas: Landmark,
  Otros: Bot,
};

const MAIN_TABS = [
  { key: "agentes", label: "Agentes" },
  { key: "actividad", label: "Actividad" },
  { key: "rendimiento", label: "Rendimiento" },
  { key: "evaluaciones", label: "Evaluaciones" },
  { key: "versiones", label: "Versiones" },
] as const;

type MainTab = (typeof MAIN_TABS)[number]["key"];

const INPUT_CLASS = "min-w-0 rounded-md border bg-background px-2.5 py-1.5 text-xs";

export function AgentsWorkspace({ agents, executions, now }: { agents: Agent[]; executions: AgentExecution[]; now: number }) {
  const [tab, setTab] = useState<MainTab>("agentes");
  const [team, setTeam] = useState("all");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortKey>("name");
  const [expanded, setExpanded] = useState<string | null>(null);

  // El log del backend está vacío mientras nadie lance agentes: entonces la
  // pantalla trabaja con ejecuciones de demostración deterministas.
  const runs = useMemo(() => (executions.length > 0 ? executions : demoExecutions(agents, teamOf, now, 7)), [agents, executions, now]);
  const runsAreDemo = executions.length === 0;

  const cards = useMemo(() => agentCards(agents, runs, now), [agents, runs, now]);
  const alerts = useMemo(() => fleetAlerts(cards), [cards]);
  const kpis = fleetKpis(cards, alerts);
  const visible = sortCards(filterCards(cards, { team, query }), sort);
  const groups = groupCards(visible);
  const usage = useMemo(() => usageByDay(agents, runs, 7, now), [agents, runs, now]);
  const distribution = runsByTeam(agents, runs);
  const feed = activityFeed(agents, runs, 6);

  if (agents.length === 0) {
    return (
      <div>
        <PageHeader title={AGENTS_TITLE} description={AGENTS_DESCRIPTION} />
        <Card>
          <CardContent>
            <EmptyState icon={Bot} title="No hay agentes registrados" description="El registro de agentes del backend está vacío." />
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title={AGENTS_TITLE}
        description={AGENTS_DESCRIPTION}
        actions={
          <>
            <DataProvenanceBadge status="demo" tooltip={DEMO_TOOLTIP} />
            <Button disabled title="Pendiente: el backend no permite crear versiones de agente">
              <Plus /> Nueva versión de agente
            </Button>
          </>
        }
      />

      <div className="grid gap-4 min-[106.25rem]:grid-cols-[minmax(0,1fr)_minmax(0,0.28fr)]">
        <div className="min-w-0 space-y-4">
          {/* KPIs */}
          <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-6" aria-label="Indicadores de la flota">
            <KpiCard label="Agentes registrados" leading={<Bot className="size-7 shrink-0 text-primary" />} value={formatInteger(kpis.registered)} />
            <KpiCard label="Ejecutando ahora" leading={<Play className="size-7 shrink-0 text-primary" />} value={formatInteger(kpis.running)} />
            <KpiCard label="Disponibles" leading={<Pause className="size-7 shrink-0 text-primary" />} value={formatInteger(kpis.available)} />
            <KpiCard
              label="Tasa de éxito"
              leading={<Gauge className="size-7 shrink-0 text-primary" />}
              value={kpis.successRate === null ? "—" : formatPercent(kpis.successRate)}
              accent={kpis.successRate !== null && kpis.successRate >= 0.95}
              caption={runsAreDemo ? "Ejecuciones de demostración" : "Ejecuciones registradas"}
            />
            <KpiCard
              label="Coste hoy"
              leading={<CircleDollarSign className="size-7 shrink-0 text-primary" />}
              value={formatEuro(kpis.costToday)}
              caption="Coste de demostración"
            />
            <KpiCard
              label="Alertas"
              leading={<AlertTriangle className={cn("size-7 shrink-0", kpis.alerts > 0 ? "text-warning" : "text-primary")} />}
              value={formatInteger(kpis.alerts)}
              tone={kpis.criticalAlerts > 0 ? "danger" : kpis.alerts > 0 ? "warning" : "default"}
              caption={`${formatInteger(kpis.criticalAlerts)} críticas`}
            />
          </section>

          {/* Pestañas y filtros */}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Tabs value={tab} onValueChange={(value) => setTab(value as MainTab)}>
              <TabsList className="flex flex-wrap justify-start group-data-horizontal/tabs:h-auto">
                {MAIN_TABS.map((item) => (
                  <TabsTrigger key={item.key} value={item.key} className="flex-none px-2.5 text-xs">
                    {item.label}
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>
            <div className="flex flex-wrap items-center gap-2">
              <select value={team} onChange={(e) => setTeam(e.target.value)} aria-label="Equipo" className={INPUT_CLASS}>
                <option value="all">Todos los equipos</option>
                {[...TEAMS, "Otros"].map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                type="search"
                placeholder="Buscar agente…"
                aria-label="Buscar agente"
                className={cn(INPUT_CLASS, "w-44")}
              />
              <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)} aria-label="Orden" className={INPUT_CLASS}>
                {Object.entries(SORT_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {tab === "agentes" ? (
            <>
              {groups.length === 0 ? (
                <Card>
                  <CardContent>
                    <EmptyState icon={Search} title="Sin agentes con estos filtros" description="Prueba con otro equipo o con otra búsqueda." />
                  </CardContent>
                </Card>
              ) : (
                <div className="space-y-4">
                  {groups.map((group) => (
                    <section key={group.team} aria-label={`Equipo ${group.team}`} className="space-y-2">
                      <p className="flex items-center gap-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
                        {group.team}
                        <span className="font-normal normal-case">
                          {group.agents.length} {group.agents.length === 1 ? "agente" : "agentes"}
                        </span>
                      </p>
                      <div className="grid gap-3 md:grid-cols-2 min-[112.5rem]:grid-cols-4">
                        {group.agents.map((agent) => (
                          <AgentCard
                            key={agent.id}
                            agent={agent}
                            icon={TEAM_ICON[agent.team] ?? Bot}
                            now={now}
                            expanded={expanded === agent.id}
                            onToggle={() => setExpanded((current) => (current === agent.id ? null : agent.id))}
                          />
                        ))}
                      </div>
                    </section>
                  ))}
                </div>
              )}

              <section className="grid gap-4 md:grid-cols-2 min-[106.25rem]:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_minmax(0,1fr)]">
                <UsageCard points={usage} isDemo={runsAreDemo} />
                <DistributionCard rows={distribution} isDemo={runsAreDemo} />
                <CostByAgentCard rows={costByAgent(cards)} />
              </section>
            </>
          ) : null}

          {tab === "actividad" ? <ActivityTable entries={activityFeed(agents, runs, 200)} now={now} isDemo={runsAreDemo} /> : null}
          {tab === "rendimiento" ? (
            <div className="space-y-4">
              <PerformanceTable cards={visible} isDemo={runsAreDemo} />
              <div className="grid gap-4 md:grid-cols-2">
                <UsageCard points={usage} isDemo={runsAreDemo} />
                <DistributionCard rows={distribution} isDemo={runsAreDemo} />
              </div>
            </div>
          ) : null}
          {tab === "evaluaciones" ? <EvaluationsTable cards={visible} /> : null}
          {tab === "versiones" ? <VersionsTable cards={visible} /> : null}
        </div>

        {/* Barra lateral */}
        <div className="min-w-0 space-y-4">
          <RealtimeActivityCard entries={feed} now={now} isDemo={runsAreDemo} />
          <FleetAlertsCard alerts={alerts} />
          <ResourcesCard />
        </div>
      </div>

      <p className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
        <Sparkles className="size-3.5" />
        {runsAreDemo
          ? `El log del Director ejecutivo está vacío: ${formatInteger(runs.length)} ejecuciones de demostración de los últimos 7 días`
          : `${formatInteger(executions.length)} ejecuciones registradas en el log del Director ejecutivo`}{" "}
        · el coste, la evaluación, la tarea en curso y las herramientas son de demostración.
      </p>
    </div>
  );
}
