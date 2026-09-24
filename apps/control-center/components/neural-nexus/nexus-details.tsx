"use client";

import Link from "next/link";
import { ArrowRight, X } from "lucide-react";
import { relativeTime } from "@/lib/dates";
import { formatDuration, formatEuro, formatInteger, formatPercent } from "@/lib/format";
import { STATUS_LABEL, type GraphEdge, type GraphNode } from "@/lib/neural-nexus";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { Button } from "@/components/ui/button";
import { NODE_ICON, STATUS_COLOR } from "./nexus-theme";

function Field({ label, value, title }: { label: string; value: string; title?: string }) {
  return (
    <div className="flex items-start justify-between gap-3 text-xs">
      <span className="shrink-0 text-muted-foreground">{label}</span>
      <span className="min-w-0 text-right break-words" title={title}>
        {value}
      </span>
    </div>
  );
}

/** A dónde lleva «Ver …» según el tipo de nodo. */
const LINK: Record<string, { href: string; label: string }> = {
  ceo: { href: "/ceo", label: "Ver Director ejecutivo" },
  core: { href: "/audit", label: "Ver trazabilidad" },
  domain: { href: "/agents", label: "Ver módulo" },
  agent: { href: "/agents", label: "Ver agente" },
};

/** Panel de detalle del nodo seleccionado (especificación §24–27). Solo enseña
 * lo que el nodo tiene: nunca rellena un hueco con un cero. */
export function NexusDetails({
  node,
  edges,
  nodes,
  now,
  onClose,
}: {
  node: GraphNode;
  edges: GraphEdge[];
  nodes: GraphNode[];
  now: number;
  onClose: () => void;
}) {
  const color = STATUS_COLOR[node.status];
  const Icon = NODE_ICON[node.icon];
  const link = LINK[node.type];
  const byId = new Map(nodes.map((item) => [item.id, item]));
  const connected = edges
    .filter((edge) => edge.source === node.id || edge.target === node.id)
    .map((edge) => byId.get(edge.source === node.id ? edge.target : edge.source))
    .filter((item): item is GraphNode => item !== undefined);
  const ownAgents = node.type === "domain" ? nodes.filter((item) => item.type === "agent" && item.domain === node.domain) : [];

  return (
    <div className="pointer-events-auto w-72 rounded-xl border border-white/10 bg-[#071713]/95 p-3 backdrop-blur-sm">
      <div className="mb-2 flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-start gap-2">
          {Icon ? (
            <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg border" style={{ borderColor: `${color}55` }}>
              <Icon className="size-3.5" style={{ color }} />
            </span>
          ) : null}
          <div className="min-w-0">
            <p className="text-sm leading-tight font-semibold break-words">{node.label}</p>
            <p className="flex items-center gap-1.5 text-[11px] font-medium" style={{ color }}>
              <span className="size-1.5 rounded-full" style={{ background: color }} aria-hidden />
              {STATUS_LABEL[node.status]}
              {node.domain && node.type === "agent" ? <span className="text-muted-foreground">· {node.domain}</span> : null}
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Cerrar detalle"
          className="shrink-0 rounded-md p-1 text-muted-foreground transition-colors hover:bg-white/10 hover:text-foreground"
        >
          <X className="size-3.5" />
        </button>
      </div>

      <p className="mb-2.5 text-[11px] text-muted-foreground">{node.description}</p>

      <div className="space-y-1.5 border-t border-white/10 pt-2.5">
        {node.projectName ? <Field label="Proyecto" value={node.projectName} /> : null}
        {node.task ? <Field label="Tarea actual" value={node.task} /> : null}
        {node.progress !== undefined ? (
          <div className="space-y-1">
            <Field label="Progreso" value={formatPercent(node.progress, 0)} />
            <div className="h-1.5 overflow-hidden rounded-full bg-white/10">
              <div className="h-full rounded-full" style={{ width: `${Math.round(node.progress * 100)}%`, background: color }} />
            </div>
          </div>
        ) : null}
        {node.lastActivityAt ? <Field label="Última actividad" value={relativeTime(node.lastActivityAt, now)} /> : null}
        {ownAgents.length > 0 ? (
          <>
            <Field label="Agentes" value={formatInteger(ownAgents.length)} />
            <Field label="Ejecutando" value={formatInteger(ownAgents.filter((item) => item.status === "running").length)} />
            <Field
              label="Con incidencia"
              value={formatInteger(ownAgents.filter((item) => item.status === "blocked" || item.status === "error").length)}
            />
          </>
        ) : null}
      </div>

      {node.metrics && node.type === "agent" ? (
        <div className="mt-2.5 grid grid-cols-2 gap-x-3 gap-y-1.5 border-t border-white/10 pt-2.5">
          <Field label="Ejecuciones" value={formatInteger(node.metrics.runs ?? 0)} />
          <Field label="Éxito" value={node.metrics.successRate === undefined ? "—" : formatPercent(node.metrics.successRate)} />
          <Field label="Latencia" value={node.metrics.latencyMs === undefined ? "—" : formatDuration(node.metrics.latencyMs)} />
          <Field label="Coste hoy" value={formatEuro(node.metrics.costToday ?? 0)} />
        </div>
      ) : null}

      {connected.length > 0 ? (
        <div className="mt-2.5 border-t border-white/10 pt-2.5">
          <p className="mb-1.5 text-[11px] text-muted-foreground">Conectado con</p>
          <div className="flex flex-wrap gap-1">
            {connected.slice(0, 8).map((item) => (
              <span
                key={item.id}
                className="max-w-full truncate rounded-md border border-white/10 px-1.5 py-0.5 text-[10px] text-muted-foreground"
                title={item.label}
              >
                {item.label}
              </span>
            ))}
            {connected.length > 8 ? <span className="px-1 text-[10px] text-muted-foreground">+{connected.length - 8}</span> : null}
          </div>
        </div>
      ) : null}

      <div className="mt-2.5 flex items-center justify-between gap-2 border-t border-white/10 pt-2.5">
        <DataProvenanceBadge
          status={node.isDemo ? "demo" : "verified"}
          compact
          tooltip={
            node.isDemo
              ? "Nodo de demostración: el backend no lo proporciona todavía."
              : "Agente del registro real; la tarea en curso y el progreso son de demostración."
          }
        />
        {link ? (
          <Button size="sm" variant="outline" nativeButton={false} render={<Link href={link.href} />}>
            {link.label} <ArrowRight />
          </Button>
        ) : null}
      </div>
    </div>
  );
}
