import { ListChecks } from "lucide-react";
import type { TaskAgentRow, TaskAgentTone } from "@/lib/task-agent";
import type { TaskAgentPanel } from "@/lib/task-agent-reads";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/empty-state";
import { ReadErrorNotice } from "@/components/read-error-notice";

// La relación TAREA ↔ AGENTE de la última misión (M48, Commit 7): Tarea / Agente asignado / Ejecutado por / Estado. La relación la calcula el
// backend; esta vista solo la escribe (`lib/task-agent.ts`). Un error de lectura NO es «sin tareas» y «No disponible» NO es «Sin asignar».

const TONE_CLASS: Record<TaskAgentTone, string> = {
  ok: "text-emerald-400",
  warn: "text-amber-400",
  bad: "text-red-400",
  neutral: "text-muted-foreground",
};

export function TaskAgentTable({ rows }: { rows: TaskAgentRow[] }) {
  return (
    <div className="overflow-x-auto" data-section="tareas-y-agentes-tabla">
      <table className="w-full min-w-[34rem] text-left text-xs">
        <thead className="text-muted-foreground">
          <tr>
            <th className="py-1.5 pr-3 font-medium">Tarea</th>
            <th className="py-1.5 pr-3 font-medium">Agente asignado</th>
            <th className="py-1.5 pr-3 font-medium">Ejecutado por</th>
            <th className="py-1.5 font-medium">Estado</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.taskId} className="border-t border-white/10 align-top" data-relation={row.status} data-deviation={row.deviation ? "true" : undefined}>
              <td className="py-1.5 pr-3">
                <p className="font-medium break-words">{row.taskName}</p>
                <p className="text-[11px] text-muted-foreground">{row.capability}</p>
              </td>
              <td className="py-1.5 pr-3 break-words">{row.assigned.label}</td>
              <td className="py-1.5 pr-3 break-words">{row.executedBy === null ? "—" : row.executedBy.label}</td>
              <td className="py-1.5">
                <span className={TONE_CLASS[row.tone]}>{row.state}</span>
                {row.note ? <p className="text-[11px] text-muted-foreground">{row.note}</p> : null}
                {row.historical ? <p className="text-[11px] text-muted-foreground">Anterior al vínculo: sale de la auditoría.</p> : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function TaskAgentCard({ panel }: { panel: TaskAgentPanel }) {
  return (
    <Card className="min-w-0" data-section="tareas-y-agentes" data-read-state={panel.kind}>
      <CardHeader>
        <CardTitle>Tareas y agentes</CardTitle>
        {panel.kind === "loaded" ? (
          <p className="text-xs text-muted-foreground">
            {panel.projectName} · {panel.counts.tasks} tareas · {panel.counts.assigned} con agente asignado · {panel.counts.executed} ejecutadas
            {panel.counts.deviations > 0 ? ` · ${panel.counts.deviations} con desviación` : ""}
            {panel.counts.inconsistent > 0 ? ` · ${panel.counts.inconsistent} inconsistentes` : ""}
          </p>
        ) : null}
      </CardHeader>
      <CardContent>
        {panel.kind === "error" ? <ReadErrorNotice title="No se pudo leer la relación tarea ↔ agente" message={panel.message} /> : null}
        {panel.kind === "unread" ? <p className="text-xs text-muted-foreground">No disponible. {panel.reason}</p> : null}
        {panel.kind === "empty" ? <EmptyState icon={ListChecks} title="La última misión no tiene tareas registradas" /> : null}
        {panel.kind === "loaded" ? <TaskAgentTable rows={panel.rows} /> : null}
      </CardContent>
    </Card>
  );
}
