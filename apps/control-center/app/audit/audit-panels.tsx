"use client";

import Link from "next/link";
import { AlertTriangle, ArrowRight, Check, CircleCheck, FileText, Link2, ShieldCheck } from "lucide-react";
import {
  DEMO_EVIDENCES,
  INTEGRITY_CHECKS,
  INTEGRITY_LAST_CHECK_MINUTES,
  RETENTION_POLICY,
  demoEvidenceCount,
  demoHash,
} from "@/lib/demo/audit";
import { formatInteger, formatPercent } from "@/lib/format";
import type { Anomaly, AuditRow, TraceStep } from "@/lib/audit-view";
import { actorActivity, correlationTrace, detailFields, projectActivity, rowChanges, rowsByDay } from "@/lib/audit-view";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { LevelChip, type LevelTone } from "@/components/level-chip";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function formatDateTime(at: number): string {
  return new Date(at).toLocaleString("es-ES", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "UTC" });
}

export function formatTime(at: number): string {
  return new Date(at).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit", timeZone: "UTC" });
}

export function formatDay(at: number): string {
  return new Date(at).toLocaleDateString("es-ES", { weekday: "long", day: "numeric", month: "long", timeZone: "UTC" });
}

// --- Detalle del evento -------------------------------------------------------------

export function EventFieldsCard({ row }: { row: AuditRow }) {
  const fields = detailFields(row);
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Datos del evento</CardTitle>
        <CardAction>
          <DataProvenanceBadge
            status={row.isDemo ? "demo" : "verified"}
            compact
            tooltip={row.isDemo ? "Evento de demostración: el registro real solo tiene una decena de entradas." : "Entrada real del registro de auditoría."}
          />
        </CardAction>
      </CardHeader>
      <CardContent className="grid gap-3 sm:grid-cols-2">
        <dl className="space-y-1.5 text-xs">
          {fields.real.map((field) => (
            <div key={field.label} className="flex items-start justify-between gap-2">
              <dt className="text-muted-foreground">{field.label}</dt>
              <dd className="min-w-0 text-right break-words">{field.value}</dd>
            </div>
          ))}
        </dl>
        <dl className="space-y-1.5 text-xs">
          {fields.demo.map((field) => (
            <div key={field.label} className="flex items-start justify-between gap-2">
              <dt className="text-muted-foreground">{field.label}</dt>
              <dd className="min-w-0 text-right break-words">{field.value}</dd>
            </div>
          ))}
          <p className="pt-1 text-[11px] text-muted-foreground">IP, user agent, hash y evidencias son de demostración.</p>
        </dl>
      </CardContent>
    </Card>
  );
}

export function ChangesCard({ row }: { row: AuditRow }) {
  const changes = rowChanges(row);
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Cambios relevantes</CardTitle>
      </CardHeader>
      <CardContent>
        {changes.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {row.isDemo ? "Los eventos de demostración no guardan estado antes y después." : "El backend no guardó estado antes/después de este evento."}
          </p>
        ) : (
          <div className="grid gap-2 sm:grid-cols-2">
            <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-2.5">
              <p className="mb-1 text-[11px] font-medium text-destructive">Antes</p>
              <ul className="space-y-0.5 font-mono text-[11px]">
                {changes.map((change) => (
                  <li key={change.key} className="break-words">
                    {change.key} = {change.before ?? "null"}
                  </li>
                ))}
              </ul>
            </div>
            <div className="rounded-lg border border-primary/30 bg-primary/5 p-2.5">
              <p className="mb-1 text-[11px] font-medium text-primary">Después</p>
              <ul className="space-y-0.5 font-mono text-[11px]">
                {changes.map((change) => (
                  <li key={change.key} className="break-words">
                    {change.key} = {change.after ?? "null"}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function TraceCard({ steps }: { steps: TraceStep[] }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Trazabilidad (Correlation Trace)</CardTitle>
        <CardAction>
          <Button size="xs" variant="outline" className="text-primary" nativeButton={false} render={<Link href="/projects" />}>
            Ver proyecto
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent>
        {steps.length === 0 ? (
          <p className="text-sm text-muted-foreground">Sin más eventos con este ID de correlación.</p>
        ) : (
          <ol className="flex flex-wrap items-start gap-x-2 gap-y-3">
            {steps.map((step, index) => (
              <li key={step.code} className="flex min-w-0 items-start gap-2">
                <span className="flex min-w-0 flex-col items-center gap-1 text-center">
                  <span className="flex size-8 items-center justify-center rounded-full border border-primary/40 bg-primary/10 text-primary">
                    <Check className="size-4" />
                  </span>
                  <span className="max-w-24 text-[11px] leading-tight font-medium">{step.title}</span>
                  <span className="max-w-24 text-[11px] leading-tight text-muted-foreground">{step.actor}</span>
                  <span className="text-[11px] text-muted-foreground tabular-nums">{formatTime(step.at)}</span>
                </span>
                {index < steps.length - 1 ? <ArrowRight className="mt-2 size-4 shrink-0 text-muted-foreground" /> : null}
              </li>
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}

export function EvidencesCard({ row }: { row: AuditRow }) {
  const count = demoEvidenceCount(row.id);
  const evidences = DEMO_EVIDENCES.slice(0, count);
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Evidencias asociadas ({count})</CardTitle>
        <CardAction>
          <DataProvenanceBadge status="demo" compact tooltip="No hay almacén de evidencias en el backend: los adjuntos son de demostración." />
        </CardAction>
      </CardHeader>
      <CardContent>
        {evidences.length === 0 ? (
          <p className="text-sm text-muted-foreground">Este evento no tiene evidencias asociadas.</p>
        ) : (
          <ul className="divide-y text-xs">
            {evidences.map((evidence) => (
              <li key={evidence.name} className="flex items-center gap-2 py-1.5 first:pt-0">
                <FileText className="size-3.5 shrink-0 text-primary" />
                <span className="min-w-0 flex-1 leading-tight">{evidence.name}</span>
                <span className="rounded border px-1 text-[10px] text-muted-foreground">{evidence.type}</span>
                <span className="text-muted-foreground tabular-nums">{evidence.sizeKb} KB</span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

export function IntegrityCard({ row }: { row: AuditRow }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Integridad del registro</CardTitle>
        <CardAction>
          <LevelChip tone="ok">100 %</LevelChip>
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-2">
        <ul className="space-y-1.5 text-xs">
          {INTEGRITY_CHECKS.map((check) => (
            <li key={check} className="flex items-center gap-2">
              <CircleCheck className="size-3.5 shrink-0 text-primary" />
              {check}
            </li>
          ))}
        </ul>
        <p className="border-t pt-2 text-[11px] text-muted-foreground">
          Hash {demoHash(row.id).slice(0, 12)} · última verificación hace {INTEGRITY_LAST_CHECK_MINUTES} min.
        </p>
        <DataProvenanceBadge status="demo" compact tooltip="El backend no firma ni encadena las entradas de auditoría: la integridad es de demostración." />
      </CardContent>
    </Card>
  );
}

export function ProjectContextCard({ row }: { row: AuditRow }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Contexto del proyecto</CardTitle>
        {row.projectCode ? (
          <CardAction>
            <Button size="xs" variant="outline" className="text-primary" nativeButton={false} render={<Link href="/projects" />}>
              Ver proyecto
            </Button>
          </CardAction>
        ) : null}
      </CardHeader>
      <CardContent>
        {row.projectCode ? (
          <dl className="space-y-1.5 text-xs">
            <div className="flex items-center justify-between gap-2">
              <dt className="text-muted-foreground">Proyecto</dt>
              <dd>{row.projectCode}</dd>
            </div>
            <div className="flex items-center justify-between gap-2">
              <dt className="text-muted-foreground">Producto</dt>
              <dd className="min-w-0 text-right break-words">{row.productName}</dd>
            </div>
            <div className="flex items-center justify-between gap-2">
              <dt className="text-muted-foreground">Tipo de evento</dt>
              <dd>{row.type}</dd>
            </div>
            <div className="flex items-center justify-between gap-2">
              <dt className="text-muted-foreground">Criticidad</dt>
              <dd>{row.criticality}</dd>
            </div>
          </dl>
        ) : (
          <p className="text-sm text-muted-foreground">Este evento no está atribuido a ningún proyecto.</p>
        )}
      </CardContent>
    </Card>
  );
}

export function JsonCard({ row }: { row: AuditRow }) {
  const payload = {
    id: row.code,
    action: row.action,
    actor: row.actor,
    resource: row.resource,
    correlation_id: row.correlationId,
    created_at: new Date(row.at).toISOString(),
    before: row.before,
    after: row.after,
  };
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>JSON del evento</CardTitle>
        <CardAction>
          <DataProvenanceBadge
            status={row.isDemo ? "demo" : "verified"}
            compact
            tooltip={row.isDemo ? "Evento de demostración." : "Tal cual lo devuelve /api/audit."}
          />
        </CardAction>
      </CardHeader>
      <CardContent>
        <pre className="overflow-x-auto rounded-lg border bg-background/60 p-2.5 text-[11px] leading-tight">{JSON.stringify(payload, null, 2)}</pre>
      </CardContent>
    </Card>
  );
}

// --- Otras pestañas -------------------------------------------------------------------

export function TimelineCard({ rows }: { rows: AuditRow[] }) {
  const days = rowsByDay(rows).slice(0, 5);
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Timeline</CardTitle>
        <CardDescription>Los cinco días más recientes del registro filtrado.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {days.map((day) => (
          <section key={day.day} className="space-y-2">
            <p className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
              {formatDay(day.day)} · {formatInteger(day.rows.length)} eventos
            </p>
            <ol className="space-y-1.5">
              {day.rows.slice(0, 8).map((row) => (
                <li key={row.id} className="grid grid-cols-[3rem_minmax(0,1fr)_auto] items-start gap-2 text-xs">
                  <span className="text-muted-foreground tabular-nums">{formatTime(row.at)}</span>
                  <span className="min-w-0 leading-tight">
                    <span className="block font-medium">{row.title}</span>
                    <span className="block text-muted-foreground">
                      {row.actor}
                      {row.projectCode ? ` · ${row.projectCode}` : ""}
                    </span>
                  </span>
                  <LevelChip tone={row.result === "Error" ? "bad" : row.result === "Creado" ? "neutral" : "ok"}>{row.result}</LevelChip>
                </li>
              ))}
            </ol>
            {day.rows.length > 8 ? <p className="text-[11px] text-muted-foreground">y {formatInteger(day.rows.length - 8)} eventos más ese día.</p> : null}
          </section>
        ))}
      </CardContent>
    </Card>
  );
}

export function ProjectsTabCard({ rows }: { rows: AuditRow[] }) {
  const projects = projectActivity(rows);
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Eventos por proyecto</CardTitle>
      </CardHeader>
      <CardContent>
        <table className="w-full text-xs">
          <thead className="text-muted-foreground">
            <tr>
              <th className="pb-2 text-left font-normal">Proyecto</th>
              <th className="pb-2 text-left font-normal">Producto</th>
              <th className="pb-2 text-right font-normal">Eventos</th>
              <th className="pb-2 text-right font-normal">Último</th>
            </tr>
          </thead>
          <tbody>
            {projects.map((project) => (
              <tr key={project.projectCode} className="border-t">
                <td className="py-1.5 font-medium">{project.projectCode}</td>
                <td className="py-1.5">{project.productName ?? "—"}</td>
                <td className="text-right tabular-nums">{formatInteger(project.events)}</td>
                <td className="text-right whitespace-nowrap text-muted-foreground">{formatDateTime(project.lastAt)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {projects.length === 0 ? <p className="py-3 text-sm text-muted-foreground">Ningún evento atribuido a un proyecto.</p> : null}
      </CardContent>
    </Card>
  );
}

export function ActorsTabCard({ rows }: { rows: AuditRow[] }) {
  const actors = actorActivity(rows);
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Actividad por actor</CardTitle>
      </CardHeader>
      <CardContent>
        <table className="w-full text-xs">
          <thead className="text-muted-foreground">
            <tr>
              <th className="pb-2 text-left font-normal">Actor</th>
              <th className="pb-2 text-left font-normal">Tipo</th>
              <th className="pb-2 text-right font-normal">Eventos</th>
              <th className="pb-2 text-right font-normal">Errores</th>
              <th className="pb-2 text-right font-normal">Último</th>
            </tr>
          </thead>
          <tbody>
            {actors.slice(0, 15).map((actor) => (
              <tr key={actor.actor} className="border-t">
                <td className="py-1.5 font-medium break-words">{actor.actor}</td>
                <td className="py-1.5">{actor.kind}</td>
                <td className="text-right tabular-nums">{formatInteger(actor.events)}</td>
                <td className={cn("text-right tabular-nums", actor.errors > 0 && "text-destructive")}>{formatInteger(actor.errors)}</td>
                <td className="text-right whitespace-nowrap text-muted-foreground">{formatDateTime(actor.lastAt)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

export function SecurityTabCard({ rows }: { rows: AuditRow[] }) {
  const security = rows.filter((row) => row.type === "Seguridad" || row.type === "Configuración");
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Seguridad y configuración</CardTitle>
        <CardDescription>Accesos, cambios de configuración y despliegues.</CardDescription>
      </CardHeader>
      <CardContent>
        {security.length === 0 ? (
          <p className="text-sm text-muted-foreground">Sin eventos de seguridad en el periodo.</p>
        ) : (
          <ul className="divide-y text-xs">
            {security.slice(0, 20).map((row) => (
              <li key={row.id} className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2 py-2 first:pt-0">
                <ShieldCheck className="size-4 shrink-0 text-primary" />
                <span className="min-w-0 leading-tight">
                  <span className="block font-medium">{row.title}</span>
                  <span className="block text-muted-foreground">
                    {row.actor} · {formatDateTime(row.at)}
                  </span>
                </span>
                <LevelChip tone={row.criticality === "Alta" ? "bad" : row.criticality === "Media" ? "warn" : "ok"}>{row.criticality}</LevelChip>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

export function IntegrityTabCard({ rows, evidenceRate }: { rows: AuditRow[]; evidenceRate: number }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Integridad del registro</CardTitle>
        <CardAction>
          <DataProvenanceBadge status="demo" compact tooltip="El backend no firma ni encadena las entradas: hash y verificación son de demostración." />
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-3">
        <dl className="grid gap-2 text-sm sm:grid-cols-3">
          <div className="rounded-lg border bg-background/40 p-2.5">
            <dt className="text-xs text-muted-foreground">Eventos verificados</dt>
            <dd className="mt-0.5 text-lg font-semibold">{formatInteger(rows.length)}</dd>
          </div>
          <div className="rounded-lg border bg-background/40 p-2.5">
            <dt className="text-xs text-muted-foreground">Evidencias completas</dt>
            <dd className="mt-0.5 text-lg font-semibold text-primary">{formatPercent(evidenceRate)}</dd>
          </div>
          <div className="rounded-lg border bg-background/40 p-2.5">
            <dt className="text-xs text-muted-foreground">Última verificación</dt>
            <dd className="mt-0.5 text-lg font-semibold">hace {INTEGRITY_LAST_CHECK_MINUTES} min</dd>
          </div>
        </dl>
        <ul className="space-y-1.5 text-xs">
          {rows.slice(0, 8).map((row) => (
            <li key={row.id} className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2">
              <Link2 className="size-3.5 shrink-0 text-muted-foreground" />
              <span className="min-w-0 truncate font-mono">{demoHash(row.id)}</span>
              <span className="text-muted-foreground">{row.code}</span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

export function RetentionTabCard() {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Política de retención</CardTitle>
        <CardAction>
          <DataProvenanceBadge status="demo" compact tooltip="No hay política de retención configurable en el backend." />
        </CardAction>
      </CardHeader>
      <CardContent>
        <table className="w-full text-xs">
          <thead className="text-muted-foreground">
            <tr>
              <th className="pb-2 text-left font-normal">Dato</th>
              <th className="pb-2 text-left font-normal">Retención</th>
              <th className="pb-2 text-left font-normal">Motivo</th>
            </tr>
          </thead>
          <tbody>
            {RETENTION_POLICY.map((policy) => (
              <tr key={policy.key} className="border-t">
                <td className="py-1.5 font-medium">{policy.label}</td>
                <td className="py-1.5">{policy.period}</td>
                <td className="py-1.5 text-muted-foreground">{policy.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

const ANOMALY_TONE: Record<Anomaly["level"], LevelTone> = { "Crítica": "bad", Media: "warn", Baja: "neutral" };

export function AnomaliesCard({ anomalies }: { anomalies: Anomaly[] }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>
          Anomalías detectadas <span className="font-normal text-muted-foreground">(últimos 7 días)</span>
        </CardTitle>
        <CardAction>
          <DataProvenanceBadge status="demo" compact tooltip="No hay detección de anomalías en el backend: el listado es de demostración salvo el recuento de errores." />
        </CardAction>
      </CardHeader>
      <CardContent>
        <ul className="flex flex-wrap items-center gap-3">
          {anomalies.map((anomaly) => (
            <li key={anomaly.text} className="flex items-center gap-2">
              <LevelChip tone={ANOMALY_TONE[anomaly.level]}>
                {anomaly.count} {anomaly.level}
              </LevelChip>
              <span className="text-xs">{anomaly.text}</span>
            </li>
          ))}
          {anomalies.length === 0 ? (
            <li className="flex items-center gap-2 text-sm text-muted-foreground">
              <CircleCheck className="size-4 text-primary" /> Sin anomalías esta semana.
            </li>
          ) : null}
        </ul>
      </CardContent>
    </Card>
  );
}

export const AUDIT_ALERT_ICON = AlertTriangle;
export { correlationTrace };
