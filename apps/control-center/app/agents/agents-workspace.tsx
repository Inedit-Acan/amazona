"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import {
  Activity,
  AlertTriangle,
  Bot,
  CheckCircle2,
  CircleDollarSign,
  ClipboardCheck,
  GitBranch,
  Gauge,
  Search,
  ShieldAlert,
  Timer,
  Wrench,
  Zap,
} from "lucide-react";
import type { Agent, AgentExecution } from "@/lib/api";
import {
  WINDOW_LABELS,
  agentStats,
  executionsByAgent,
  fleetSummary,
  groupByTeam,
  runsByTeam,
  teamOf,
  withinWindow,
  type ActivityWindow,
} from "@/lib/agents";
import { parseUtc } from "@/lib/dates";
import { formatDuration, formatInteger, formatPercent } from "@/lib/format";
import { AgentCard } from "@/components/agent-card";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { KpiCard } from "@/components/kpi-card";
import { PendingFeatures, type PendingFeature } from "@/components/pending-features";
import { RankedBars } from "@/components/ranked-bars";
import { StackedBar } from "@/components/stacked-bar";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

const INPUT_CLASS = "rounded-md border bg-background px-3 py-2 text-sm";

const PENDING_EVALUATIONS: PendingFeature[] = [
  {
    icon: ClipboardCheck,
    title: "Evaluation Suite",
    description: "Relevancia, errores, grounding, coste, latencia y cumplimiento de políticas por agente y versión.",
  },
  {
    icon: Gauge,
    title: "Umbral de despliegue",
    description: "No desplegar una versión que no supere el umbral definido.",
  },
];

const PENDING_OPERATIONS: PendingFeature[] = [
  {
    icon: CircleDollarSign,
    title: "Costes medidos por agente",
    description: "Tokens, llamadas a API, búsquedas y servicios externos; hoy solo hay un coste nominal declarado.",
  },
  {
    icon: Wrench,
    title: "Herramientas y permisos",
    description: "Qué herramienta tiene cada agente y qué permiso se le ha otorgado (leer, crear análisis, gastar dinero…).",
  },
  {
    icon: GitBranch,
    title: "Versionado e historial",
    description: "Historial de versiones, producción vs staging, comparación y rollback.",
  },
  {
    icon: Zap,
    title: "Handoffs, trazas y alertas",
    description: "Traspasos entre agentes, trazas operativas y alertas de error rate, coste o latencia.",
  },
];

interface ExecutionRow {
  execution: AgentExecution;
  agentName: string;
}

interface PerformanceRow {
  agent: Agent;
  runs: number;
  failures: number;
  successRate: number | null;
  avgLatencyMs: number | null;
  lastActivity: Date | null;
}

function DateCell({ value }: { value: Date | null }) {
  return <>{value ? value.toLocaleString("es-ES") : "—"}</>;
}

export function AgentsWorkspace({ agents, executions }: { agents: Agent[]; executions: AgentExecution[] }) {
  const [query, setQuery] = useState("");
  const [team, setTeam] = useState<string>("all");
  const [windowKey, setWindowKey] = useState<ActivityWindow>("all");
  // Se fija una sola vez: mantener el render puro y la ventana estable entre renders.
  const [now] = useState(() => Date.now());

  const byAgent = useMemo(() => executionsByAgent(executions), [executions]);
  const agentById = useMemo(() => new Map(agents.map((a) => [a.id, a] as const)), [agents]);
  const summary = useMemo(() => fleetSummary(agents, executions), [agents, executions]);
  const windowed = useMemo(() => withinWindow(executions, windowKey, now), [executions, windowKey, now]);
  const windowedByAgent = useMemo(() => executionsByAgent(windowed), [windowed]);

  const visibleGroups = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    const filtered = agents.filter((a) => {
      const matchesQuery =
        !normalized || a.name.toLowerCase().includes(normalized) || a.capabilities.some((c) => c.toLowerCase().includes(normalized));
      return matchesQuery && (team === "all" || teamOf(a.role) === team);
    });
    return groupByTeam(filtered);
  }, [agents, query, team]);
  const teamOptions = useMemo(() => groupByTeam(agents).map((g) => g.team), [agents]);

  const failedAgents = agents
    .map((agent) => ({ agent, stats: agentStats(byAgent.get(agent.id) ?? []) }))
    .filter((item) => item.stats.failures > 0);

  const activityRows: ExecutionRow[] = useMemo(
    () =>
      [...executions]
        .sort((a, b) => b.created_at.localeCompare(a.created_at))
        .map((execution) => ({ execution, agentName: agentById.get(execution.agent_id)?.name ?? execution.agent_id })),
    [executions, agentById],
  );

  const activityColumns: DataTableColumn<ExecutionRow>[] = [
    { key: "agent", header: "Agente", cell: (row) => <span className="font-medium">{row.agentName}</span>, sortValue: (row) => row.agentName, exportValue: (row) => row.agentName },
    { key: "capability", header: "Capacidad", cell: (row) => <span className="font-mono text-xs text-muted-foreground">{row.execution.capability}</span>, exportValue: (row) => row.execution.capability },
    {
      key: "result",
      header: "Resultado",
      cell: (row) =>
        row.execution.success ? (
          <span className="flex items-center gap-1 text-primary">
            <CheckCircle2 className="size-3.5" /> Correcta
          </span>
        ) : (
          <span className="flex items-center gap-1 text-destructive">
            <AlertTriangle className="size-3.5" /> Fallida
          </span>
        ),
      sortValue: (row) => (row.execution.success ? 1 : 0),
      exportValue: (row) => (row.execution.success ? "correcta" : "fallida"),
    },
    { key: "duration", header: "Duración", cell: (row) => formatDuration(row.execution.duration_ms), sortValue: (row) => row.execution.duration_ms, exportValue: (row) => row.execution.duration_ms },
    {
      key: "when",
      header: "Cuándo",
      cell: (row) => <DateCell value={new Date(parseUtc(row.execution.created_at))} />,
      sortValue: (row) => row.execution.created_at,
      exportValue: (row) => row.execution.created_at,
    },
    {
      key: "trace",
      header: "Traza",
      cell: (row) => (
        <Link href={`/audit?correlation_id=${row.execution.correlation_id}`} className="font-mono text-xs text-primary underline underline-offset-4">
          {row.execution.correlation_id.slice(0, 8)}
        </Link>
      ),
    },
  ];

  const performanceRows: PerformanceRow[] = agents.map((agent) => ({ agent, ...agentStats(windowedByAgent.get(agent.id) ?? []) }));
  const performanceColumns: DataTableColumn<PerformanceRow>[] = [
    { key: "agent", header: "Agente", cell: (row) => <span className="font-medium">{row.agent.name}</span>, sortValue: (row) => row.agent.name, exportValue: (row) => row.agent.name },
    { key: "team", header: "Equipo", cell: (row) => teamOf(row.agent.role), sortValue: (row) => teamOf(row.agent.role), exportValue: (row) => teamOf(row.agent.role) },
    { key: "runs", header: "Runs", cell: (row) => formatInteger(row.runs), sortValue: (row) => row.runs, exportValue: (row) => row.runs, align: "right" },
    {
      key: "success",
      header: "Éxito",
      cell: (row) => (row.successRate !== null ? formatPercent(row.successRate, 0) : <span className="text-muted-foreground">—</span>),
      sortValue: (row) => row.successRate ?? -1,
      align: "right",
    },
    { key: "latency", header: "Latencia", cell: (row) => (row.avgLatencyMs !== null ? formatDuration(row.avgLatencyMs) : "—"), sortValue: (row) => row.avgLatencyMs ?? -1, align: "right" },
    {
      key: "errors",
      header: "Errores",
      cell: (row) => <span className={cn(row.failures > 0 && "font-medium text-destructive")}>{row.failures}</span>,
      sortValue: (row) => row.failures,
      exportValue: (row) => row.failures,
      align: "right",
    },
    { key: "last", header: "Última actividad", cell: (row) => <DateCell value={row.lastActivity} /> },
    { key: "eval", header: "Eval.", cell: () => <DataProvenanceBadge status="pending" tooltip="No existe una Evaluation Suite." /> },
    { key: "cost", header: "Coste", cell: () => <DataProvenanceBadge status="pending" tooltip="El coste por ejecución no se mide: solo hay un coste nominal declarado." /> },
  ];

  const versionColumns: DataTableColumn<Agent>[] = [
    { key: "agent", header: "Agente", cell: (row) => <span className="font-medium">{row.name}</span>, sortValue: (row) => row.name, exportValue: (row) => row.name },
    { key: "team", header: "Equipo", cell: (row) => teamOf(row.role), sortValue: (row) => teamOf(row.role) },
    { key: "version", header: "Versión", cell: (row) => <span className="font-mono text-xs">{row.version}</span>, sortValue: (row) => row.version, exportValue: (row) => row.version },
    {
      key: "cost",
      header: "Coste nominal por tarea",
      cell: (row) => {
        const cost = row.cost_profile.simulated_cost_per_task;
        return typeof cost === "number" ? <span className="tabular-nums">{cost.toLocaleString("es-ES", { minimumFractionDigits: 2 })}</span> : "—";
      },
    },
    { key: "env", header: "Producción / staging", cell: () => <DataProvenanceBadge status="pending" tooltip="El registro guarda una única versión vigente por agente." /> },
  ];

  const teamRuns = runsByTeam(agents, executions);
  const maxRuns = Math.max(0, ...teamRuns.map((t) => t.runs));

  if (agents.length === 0) {
    return (
      <Card>
        <CardContent>
          <EmptyState icon={Bot} title="No hay agentes registrados" description="El registro de agentes está vacío." />
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6" aria-label="Indicadores de la flota de agentes">
        <KpiCard label="Agentes registrados" value={formatInteger(summary.registered)} icon={Bot} caption="En el registro de agentes" provenance="verified" />
        <KpiCard
          label="Disponibles"
          value={formatInteger(summary.available)}
          icon={CheckCircle2}
          caption={`${summary.busy} ocupados${summary.other > 0 ? ` · ${summary.other} en otro estado` : ""}`}
          provenance="verified"
          provenanceTooltip="Estado actual que informa el registro."
        />
        <KpiCard
          label="Ejecuciones"
          value={formatInteger(summary.runs)}
          icon={Activity}
          caption="Registradas por el CEO"
          provenance="verified"
          provenanceTooltip="Filas del log de ejecuciones de agentes. Solo el CEO las registra hoy."
        />
        <KpiCard
          label="Tasa de éxito"
          value={summary.successRate !== null ? formatPercent(summary.successRate, 0) : "—"}
          icon={Gauge}
          caption={summary.runs > 0 ? "Ejecuciones correctas" : "Sin ejecuciones"}
          provenance={summary.successRate !== null ? "verified" : "pending"}
        />
        <KpiCard
          label="Latencia media"
          value={summary.avgLatencyMs !== null ? formatDuration(summary.avgLatencyMs) : "—"}
          icon={Timer}
          caption="Simulada: los agentes son deterministas"
          provenance={summary.avgLatencyMs !== null ? "estimated" : "pending"}
          provenanceTooltip="Duración de agentes simulados sin llamadas externas; no refleja un modelo real."
        />
        <KpiCard
          label="Agentes con errores"
          value={formatInteger(summary.agentsWithErrors)}
          icon={ShieldAlert}
          tone={summary.agentsWithErrors > 0 ? "danger" : "default"}
          caption="Con alguna ejecución fallida"
          provenance="verified"
        />
      </section>

      <Tabs defaultValue="agents" className="gap-4">
        <div className="max-w-full overflow-x-auto">
          <TabsList>
            <TabsTrigger value="agents">Agentes</TabsTrigger>
            <TabsTrigger value="activity">Actividad</TabsTrigger>
            <TabsTrigger value="performance">Rendimiento</TabsTrigger>
            <TabsTrigger value="evaluations">Evaluaciones</TabsTrigger>
            <TabsTrigger value="versions">Versiones</TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="agents" className="space-y-6">
          <div className="flex flex-wrap items-center gap-3">
            <label className="relative block min-w-0 max-w-xs flex-1">
              <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Buscar agente o capacidad…"
                aria-label="Buscar agente o capacidad"
                className={cn(INPUT_CLASS, "w-full py-1.5 pl-9")}
              />
            </label>
            <select value={team} onChange={(e) => setTeam(e.target.value)} aria-label="Filtrar por equipo" className={INPUT_CLASS}>
              <option value="all">Todos los equipos</option>
              {teamOptions.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </div>

          {visibleGroups.length === 0 ? (
            <Card>
              <CardContent>
                <EmptyState icon={Search} title="Ningún agente coincide" description="Prueba con otro nombre, capacidad o equipo." />
              </CardContent>
            </Card>
          ) : (
            visibleGroups.map((group) => (
              <section key={group.team} className="space-y-3" aria-label={`Equipo ${group.team}`}>
                <h2 className="flex items-baseline gap-2 text-sm font-semibold tracking-wide uppercase">
                  {group.team}
                  <span className="text-xs font-normal text-muted-foreground normal-case">
                    {group.agents.length} agente{group.agents.length === 1 ? "" : "s"}
                  </span>
                </h2>
                <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                  {group.agents.map((agent) => (
                    <AgentCard key={agent.id} agent={agent} executions={byAgent.get(agent.id) ?? []} />
                  ))}
                </div>
              </section>
            ))
          )}
          <p className="text-[11px] text-muted-foreground">
            El equipo de cada agente se deduce de su rol: el registro no guarda equipos. Tampoco guarda el proyecto o la
            tarea en curso, así que las tarjetas no muestran el progreso de una tarea.
          </p>
        </TabsContent>

        <TabsContent value="activity" className="space-y-4">
          <div className="grid gap-4 xl:grid-cols-12">
            <Card className="xl:col-span-9">
              <CardHeader>
                <CardTitle>Ejecuciones recientes</CardTitle>
                <CardAction>
                  <DataProvenanceBadge status="verified" tooltip="Filas del log de ejecuciones de agentes." />
                </CardAction>
              </CardHeader>
              <CardContent>
                <DataTable
                  columns={activityColumns}
                  rows={activityRows}
                  getRowId={(row) => row.execution.id}
                  getSearchText={(row) => `${row.agentName} ${row.execution.capability}`}
                  searchPlaceholder="Buscar ejecución…"
                  exportFileName="ejecuciones-agentes.csv"
                  emptyMessage="Todavía no hay ejecuciones registradas."
                />
              </CardContent>
            </Card>

            <Card className="xl:col-span-3">
              <CardHeader>
                <CardTitle>Alertas</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {failedAgents.length > 0 ? (
                  <ul className="space-y-2">
                    {failedAgents.map(({ agent, stats }) => (
                      <li key={agent.id} className="rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-sm">
                        <p className="font-medium">{agent.name}</p>
                        <p className="text-xs text-muted-foreground">
                          {stats.failures} de {stats.runs} ejecuciones fallidas
                        </p>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-muted-foreground">Ninguna ejecución registrada ha fallado.</p>
                )}
                <p className="text-[11px] text-muted-foreground">
                  Solo se alerta de ejecuciones fallidas. Error rate por umbral, coste anómalo, latencia alta y versión
                  degradada: pendientes.
                </p>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="performance" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Rendimiento por agente</CardTitle>
              <CardAction>
                <select
                  value={windowKey}
                  onChange={(e) => setWindowKey(e.target.value as ActivityWindow)}
                  aria-label="Periodo"
                  className={cn(INPUT_CLASS, "py-1")}
                >
                  {(Object.keys(WINDOW_LABELS) as ActivityWindow[]).map((key) => (
                    <option key={key} value={key}>
                      {WINDOW_LABELS[key]}
                    </option>
                  ))}
                </select>
              </CardAction>
            </CardHeader>
            <CardContent className="space-y-3">
              <DataTable
                columns={performanceColumns}
                rows={performanceRows}
                getRowId={(row) => row.agent.id}
                getSearchText={(row) => `${row.agent.name} ${teamOf(row.agent.role)}`}
                searchPlaceholder="Buscar agente…"
                exportFileName="rendimiento-agentes.csv"
              />
              <p className="text-[11px] text-muted-foreground">
                Sale del log de ejecuciones, que devuelve las 100 más recientes. Filtros por proyecto y modelo:
                pendientes (la ejecución no guarda el proyecto ni el modelo).
              </p>
            </CardContent>
          </Card>

          <div className="grid gap-4 xl:grid-cols-12">
            <Card className="xl:col-span-6">
              <CardHeader>
                <CardTitle>Ejecuciones por equipo</CardTitle>
              </CardHeader>
              <CardContent>
                {teamRuns.length > 0 ? (
                  <StackedBar
                    ariaLabel="Ejecuciones por equipo"
                    segments={teamRuns.map((item, index) => ({
                      key: item.team,
                      label: item.team,
                      value: item.runs,
                      valueLabel: `${item.runs} (${formatPercent(item.runs / (summary.runs || 1), 0)})`,
                      className: ["bg-primary", "bg-sky-500", "bg-amber-500", "bg-violet-500", "bg-rose-500", "bg-teal-500", "bg-orange-500", "bg-muted-foreground/60"][index % 8],
                    }))}
                  />
                ) : (
                  <p className="text-sm text-muted-foreground">Todavía no hay ejecuciones que repartir.</p>
                )}
              </CardContent>
            </Card>

            <Card className="xl:col-span-6">
              <CardHeader>
                <CardTitle>Ejecuciones por agente</CardTitle>
              </CardHeader>
              <CardContent>
                {maxRuns > 0 ? (
                  <RankedBars
                    ariaLabel="Ejecuciones por agente"
                    items={performanceRows
                      .filter((row) => row.runs > 0)
                      .sort((a, b) => b.runs - a.runs)
                      .map((row) => ({
                        key: row.agent.id,
                        label: row.agent.name,
                        sublabel: teamOf(row.agent.role),
                        value: row.runs,
                        valueLabel: formatInteger(row.runs),
                      }))}
                  />
                ) : (
                  <p className="text-sm text-muted-foreground">Ningún agente tiene ejecuciones en este periodo.</p>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="evaluations" className="space-y-4">
          <PendingFeatures
            title="Evaluaciones — pendiente de backend"
            tooltip="No existe una Evaluation Suite: ningún agente tiene evaluación ni umbral de despliegue."
            items={PENDING_EVALUATIONS}
            note="Las tarjetas de agente muestran una fiabilidad nominal declarada en el descriptor y las cifras reales del log de ejecuciones; no hay una evaluación medida que mostrar."
          />
        </TabsContent>

        <TabsContent value="versions" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Versiones vigentes</CardTitle>
              <CardAction>
                <DataProvenanceBadge status="verified" tooltip="Versión que asigna el registro de agentes." />
              </CardAction>
            </CardHeader>
            <CardContent className="space-y-3">
              <DataTable
                columns={versionColumns}
                rows={[...agents].sort((a, b) => a.name.localeCompare(b.name, "es"))}
                getRowId={(row) => row.id}
                getSearchText={(row) => `${row.name} ${row.version}`}
                searchPlaceholder="Buscar agente o versión…"
                exportFileName="versiones-agentes.csv"
              />
              <p className="text-[11px] text-muted-foreground">
                El coste por tarea es un valor nominal declarado (simulado), no un coste medido.
              </p>
            </CardContent>
          </Card>
          <PendingFeatures
            title="Operación de agentes — pendiente de backend"
            tooltip="Requieren medición de costes, gestión de versiones y permisos que el backend aún no tiene."
            items={PENDING_OPERATIONS}
            columns={4}
            note="El registro guarda una versión vigente y un coste nominal por agente. No hay historial de versiones, staging, rollback, herramientas, permisos, tokens ni handoffs."
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}
