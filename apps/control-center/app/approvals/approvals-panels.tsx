"use client";

import Link from "next/link";
import { AlertTriangle, Check, CircleCheck, CircleDot, Clock, FileText, MessageSquare, X } from "lucide-react";
import { APPROVAL_FLOW, DEMO_COMMENTS, DEMO_DOCUMENTS, RESOLVED_STATS, demoCommentMinutes } from "@/lib/demo/approvals";
import { formatEuro, formatInteger, formatPercent } from "@/lib/format";
import type { ApprovalRequest, StatusShare, ValidationRow } from "@/lib/approvals-view";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { DonutChart } from "@/components/donut-chart";
import { LevelChip, type LevelTone } from "@/components/level-chip";
import { Sparkline } from "@/components/sparkline";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const KIND_COLORS = ["#e056c8", "#f2994a", "#4f8df7", "#00d69a", "#f2c94c", "#a8a4f0", "#5aa9e6"];

const VALIDATION_TONE: Record<ValidationRow["state"], LevelTone> = { ok: "ok", warn: "warn", bad: "bad" };

// --- Detalle -----------------------------------------------------------------------

export function RequestFieldsCard({ request }: { request: ApprovalRequest }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Detalles de la solicitud</CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="space-y-1.5 text-sm">
          {request.fields.map((field) => (
            <div key={field.label} className="flex items-center justify-between gap-2">
              <dt className="text-muted-foreground">{field.label}</dt>
              <dd className="text-right tabular-nums">{field.value}</dd>
            </div>
          ))}
        </dl>
      </CardContent>
    </Card>
  );
}

export function ValidationsCard({ validations }: { validations: ValidationRow[] }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Estado de validaciones</CardTitle>
        <CardAction>
          <DataProvenanceBadge status="verified" compact tooltip="Cada validación es la de su pantalla: Economía, Legal Gate, readiness de Tienda y presupuesto de Finanzas." />
        </CardAction>
      </CardHeader>
      <CardContent>
        {validations.length === 0 ? (
          <p className="text-sm text-muted-foreground">Esta aprobación del backend no trae validaciones.</p>
        ) : (
          <ul className="space-y-2 text-sm">
            {validations.map((validation) => (
              <li key={validation.label} className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-2">
                  {validation.state === "ok" ? (
                    <CircleCheck className="size-4 text-primary" />
                  ) : validation.state === "warn" ? (
                    <Clock className="size-4 text-warning" />
                  ) : (
                    <AlertTriangle className="size-4 text-destructive" />
                  )}
                  {validation.label}
                </span>
                <LevelChip tone={VALIDATION_TONE[validation.state]}>{validation.detail}</LevelChip>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

export function BudgetCard({ budget }: { budget: NonNullable<ApprovalRequest["budget"]> }) {
  const used = budget.assigned > 0 ? (budget.spent + budget.committed) / budget.assigned : 0;
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Presupuesto marketing</CardTitle>
        <CardAction>
          <Button size="xs" variant="outline" className="text-primary" nativeButton={false} render={<Link href="/cfo" />}>
            Ver detalle
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        {[
          ["Asignado", budget.assigned],
          ["Gastado", budget.spent],
          ["Comprometido", budget.committed],
          ["Disponible", budget.available],
        ].map(([label, value]) => (
          <div key={label as string} className="flex items-center justify-between gap-2">
            <span className="text-muted-foreground">{label as string}</span>
            <span className="tabular-nums">{formatEuro(value as number, 0)}</span>
          </div>
        ))}
        <div className="h-2 rounded-full bg-muted">
          <div className="h-full rounded-full bg-primary" style={{ width: `${Math.min(100, Math.round(used * 100))}%` }} />
        </div>
        <div className="flex items-center justify-between gap-2 border-t pt-2">
          <span className="text-muted-foreground">Nueva solicitud</span>
          <span className="font-medium tabular-nums">{formatEuro(budget.request, 0)}</span>
        </div>
        <div className="flex items-center justify-between gap-2">
          <span className="text-muted-foreground">Después de aprobar</span>
          <span className={cn("tabular-nums", budget.available - budget.request < 0 && "text-destructive")}>
            {formatEuro(Math.max(0, budget.available - budget.request), 0)}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}

export function AgentAnalysisCard({ request }: { request: ApprovalRequest }) {
  const consulted = request.opinions.length;
  const agreed = request.opinions.filter((opinion) => opinion.ok).length;
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Análisis de AMAZONA</CardTitle>
        <CardDescription>{consulted} agentes consultados</CardDescription>
        <CardAction>
          <DataProvenanceBadge status="estimated" compact tooltip="Los agentes son los registrados; su veredicto se deriva de los análisis del producto." />
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-2">
        {consulted === 0 ? (
          <p className="text-sm text-muted-foreground">Sin análisis de agentes para esta solicitud.</p>
        ) : (
          <>
            <div className="h-1.5 rounded-full bg-muted">
              <div className="h-full rounded-full bg-primary" style={{ width: `${Math.round((agreed / consulted) * 100)}%` }} />
            </div>
            <ul className="space-y-1.5 text-xs">
              {request.opinions.map((opinion) => (
                <li key={opinion.agent} className="grid grid-cols-[auto_minmax(0,1fr)_minmax(0,1.1fr)] items-start gap-2">
                  {opinion.ok ? <Check className="mt-0.5 size-3.5 shrink-0 text-primary" /> : <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warning" />}
                  <span className="min-w-0 leading-tight font-medium">{opinion.agent}</span>
                  <span className="min-w-0 leading-tight text-muted-foreground">{opinion.verdict}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </CardContent>
    </Card>
  );
}

export function FindingsCard({ request }: { request: ApprovalRequest }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Hallazgos</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <ul className="space-y-1.5 text-xs">
          {request.findings.map((finding) => (
            <li key={finding} className="flex items-start gap-2">
              <CircleDot className="mt-0.5 size-3.5 shrink-0 text-primary" />
              <span className="min-w-0 leading-tight">{finding}</span>
            </li>
          ))}
          {request.findings.length === 0 ? <li className="text-muted-foreground">Sin hallazgos registrados.</li> : null}
        </ul>
        <div className="border-t pt-2">
          <p className="mb-1.5 text-xs font-medium">Riesgos</p>
          <ul className="space-y-1.5 text-xs">
            {request.risks.map((risk) => (
              <li key={risk} className="flex items-start gap-2">
                <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warning" />
                <span className="min-w-0 leading-tight">{risk}</span>
              </li>
            ))}
            {request.risks.length === 0 ? <li className="text-muted-foreground">Sin riesgos registrados.</li> : null}
          </ul>
        </div>
      </CardContent>
    </Card>
  );
}

export function ImpactCard({ request }: { request: ApprovalRequest }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Impacto de la decisión</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="rounded-lg border border-primary/40 bg-primary/5 p-2.5">
          <p className="flex items-center gap-1.5 text-xs font-medium text-primary">
            <CircleCheck className="size-3.5" /> Si apruebas
          </p>
          <ul className="mt-1.5 space-y-1 text-xs">
            {request.approveImpact.map((line) => (
              <li key={line} className="flex items-start gap-1.5">
                <span className="mt-1 size-1 shrink-0 rounded-full bg-primary" aria-hidden />
                <span className="min-w-0 leading-tight">{line}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-2.5">
          <p className="flex items-center gap-1.5 text-xs font-medium text-destructive">
            <X className="size-3.5" /> Si rechazas
          </p>
          <ul className="mt-1.5 space-y-1 text-xs">
            {request.rejectImpact.map((line) => (
              <li key={line} className="flex items-start gap-1.5">
                <span className="mt-1 size-1 shrink-0 rounded-full bg-destructive" aria-hidden />
                <span className="min-w-0 leading-tight">{line}</span>
              </li>
            ))}
          </ul>
        </div>
      </CardContent>
    </Card>
  );
}

export function FlowCard({ request }: { request: ApprovalRequest }) {
  const currentIndex = request.status === "PENDING" ? 2 : 3;
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Flujo de aprobación</CardTitle>
        <CardAction>
          <DataProvenanceBadge status="demo" compact tooltip="El backend guarda un solo estado por aprobación: el flujo por pasos es de demostración." />
        </CardAction>
      </CardHeader>
      <CardContent>
        <ol className="space-y-3">
          {APPROVAL_FLOW.map((step, index) => (
            <li key={step.key} className="flex items-start gap-2 text-sm">
              {index < currentIndex ? (
                <CircleCheck className="mt-0.5 size-4 shrink-0 text-primary" />
              ) : index === currentIndex ? (
                <CircleDot className="mt-0.5 size-4 shrink-0 text-primary" />
              ) : (
                <Clock className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
              )}
              <span className={cn("min-w-0 leading-tight", index > currentIndex && "text-muted-foreground")}>{step.label}</span>
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}

export function DocumentsCard() {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Documentos</CardTitle>
        <CardAction>
          <DataProvenanceBadge status="demo" compact tooltip="No hay gestor documental: los adjuntos son de demostración." />
        </CardAction>
      </CardHeader>
      <CardContent>
        <ul className="divide-y text-sm">
          {DEMO_DOCUMENTS.map((document) => (
            <li key={document.name} className="flex items-center gap-2 py-2 first:pt-0">
              <FileText className="size-4 shrink-0 text-primary" />
              <span className="min-w-0 flex-1 leading-tight">{document.name}</span>
              <span className="text-xs text-muted-foreground">{document.type}</span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

export function CommentsCard({ request }: { request: ApprovalRequest }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <MessageSquare className="size-4 text-primary" /> Comentarios
        </CardTitle>
        <CardAction>
          <DataProvenanceBadge status="demo" compact tooltip="No hay hilo de comentarios en el backend: el ejemplo es de demostración." />
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-3">
        <ul className="space-y-2.5">
          {DEMO_COMMENTS.map((comment, index) => (
            <li key={comment.text} className="rounded-lg border bg-background/40 p-2.5 text-xs">
              <p className="flex flex-wrap items-center gap-1.5">
                <span className="font-medium">{comment.author}</span>
                <span className="text-muted-foreground">{comment.role}</span>
                <span className="text-muted-foreground">· hace {demoCommentMinutes(request.id, index)} min</span>
              </p>
              <p className="mt-1 leading-tight text-muted-foreground">{comment.text}</p>
            </li>
          ))}
        </ul>
        <div className="flex gap-2">
          <input
            placeholder="Escribe un comentario…"
            aria-label="Escribe un comentario"
            disabled
            className="min-w-0 flex-1 rounded-md border bg-background px-2.5 py-1.5 text-sm"
          />
          <Button size="sm" disabled title="Pendiente: no hay hilo de comentarios en el backend">
            Enviar
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

// --- Estadísticas de la bandeja ------------------------------------------------------

export function KindDonutCard({ rows }: { rows: { key: string; label: string; value: number }[] }) {
  const total = rows.reduce((sum, row) => sum + row.value, 0);
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>
          Solicitudes por tipo <span className="font-normal text-muted-foreground">(30 días)</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-wrap items-center gap-3">
        <DonutChart
          ariaLabel="Solicitudes por tipo"
          segments={rows.map((row, k) => ({ key: row.key, value: row.value, color: KIND_COLORS[k % KIND_COLORS.length] }))}
          centerLabel={formatInteger(total)}
          centerCaption="Total"
          size={104}
        />
        <ul className="min-w-28 flex-1 space-y-1 text-xs">
          {rows.map((row, k) => (
            <li key={row.key} className="flex items-center justify-between gap-2">
              <span className="flex min-w-0 items-center gap-1.5">
                <span className="size-2.5 shrink-0 rounded-full" style={{ background: KIND_COLORS[k % KIND_COLORS.length] }} aria-hidden />
                {row.label}
              </span>
              <span className="tabular-nums">{row.value}</span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

const SHARE_TONE: Record<StatusShare["tone"], string> = {
  ok: "bg-primary",
  warn: "bg-warning",
  bad: "bg-destructive",
  neutral: "bg-muted-foreground",
};

export function StatusSharesCard({ rows }: { rows: StatusShare[] }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Estado de solicitudes</CardTitle>
        <CardAction>
          <DataProvenanceBadge status="demo" compact tooltip="Solo las pendientes son reales de la bandeja; las resueltas son de demostración." />
        </CardAction>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2 text-xs">
          {rows.map((row) => (
            <li key={row.label} className="grid grid-cols-[minmax(0,5rem)_1fr_2.6rem] items-center gap-2">
              <span className="truncate text-muted-foreground">{row.label}</span>
              <span className="h-1.5 rounded-full bg-muted">
                <span className={cn("block h-full rounded-full", SHARE_TONE[row.tone])} style={{ width: `${Math.round(row.share * 100)}%` }} />
              </span>
              <span className="text-right tabular-nums">{formatPercent(row.share, 0)}</span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

export function ResolutionTimeCard({ minutes }: { minutes: number }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Tiempo medio de resolución</CardTitle>
        <CardAction>
          <DataProvenanceBadge status="demo" compact tooltip="El backend no mide el tiempo de resolución: la serie es de demostración." />
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-2">
        <p className="text-3xl font-semibold">{minutes} min</p>
        <p className="flex items-center gap-1.5 text-xs text-primary">
          {formatPercent(RESOLVED_STATS.averageTrend, 0)} vs. periodo anterior
        </p>
        <Sparkline values={RESOLVED_STATS.daily} width={140} height={44} />
      </CardContent>
    </Card>
  );
}
