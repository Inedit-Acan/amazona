"use client";

import {
  Activity,
  Bot,
  CalendarClock,
  Check,
  ClipboardList,
  FileWarning,
  Gauge,
  Map as MapIcon,
  PackageCheck,
  PackageSearch,
  Percent,
  ReceiptText,
  RotateCcw,
  ShieldCheck,
  Timer,
  Truck,
  UserRound,
  Wallet,
  Workflow,
} from "lucide-react";
import type { EconomicAnalysis, OperationsRecord, SupplierQuote } from "@/lib/api";
import { formatAmount, formatInteger, formatPercent } from "@/lib/format";
import { OPERATIONS_VERDICT, stageDurations, stageLabel, ticketTypeLabel } from "@/lib/operations";
import { regionLabel } from "@/lib/regions";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { KpiCard, type KpiTone } from "@/components/kpi-card";
import { PendingFeatures, type PendingFeature } from "@/components/pending-features";
import { RiskList } from "@/components/risk-list";
import { VerdictBanner } from "@/components/verdict-banner";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const STATUS_KPI_TONE: Record<"ok" | "warn" | "bad", KpiTone> = { ok: "success", warn: "warning", bad: "danger" };

/** Lo que el mockup y la spec (parte 2 §3) enseñan y el backend no puede dar: hoy
 * no existen pedidos, clientes, transportistas ni ticketing reales. */
const PENDING_CONTROL_TOWER: PendingFeature[] = [
  {
    icon: Gauge,
    title: "KPIs de la operación",
    description: "Pedidos activos, en tránsito, entregados hoy, % a tiempo, entrega media, tasa de devoluciones y SLA.",
  },
  {
    icon: Workflow,
    title: "Pipeline de pedidos",
    description: "Confirmado → proveedor → preparación → despachado → en tránsito → entregado, con conteos y cuellos de botella.",
  },
  {
    icon: ClipboardList,
    title: "Pedidos recientes",
    description: "Tabla con canal, producto, proveedor, estado, entrega estimada, SLA, riesgo y filtros.",
  },
  {
    icon: FileWarning,
    title: "Centro de incidencias",
    description: "Incidencias de pedido con prioridad, proveedor, tiempo, SLA, responsable y acción recomendada.",
  },
  {
    icon: UserRound,
    title: "Rendimiento de proveedores",
    description: "Aceptación, despacho en SLA, entrega a tiempo, cancelaciones, defectos, tracking válido y score operativo.",
  },
  {
    icon: Truck,
    title: "Transportistas",
    description: "Entrega a tiempo, tiempo medio e incidencias por transportista.",
  },
  {
    icon: RotateCcw,
    title: "Devoluciones reales",
    description: "Abiertas, en revisión, en tránsito y recibidas, tasa y principales motivos.",
  },
  {
    icon: Bot,
    title: "Automatizaciones operativas",
    description: "Reglas (pago → pedido al proveedor, recordatorios, escalados) y modo operativo.",
  },
  {
    icon: Activity,
    title: "Operational Health",
    description: "Score explicable de pedidos, proveedores, logística, entregas, devoluciones e incidencias.",
  },
  {
    icon: MapIcon,
    title: "Mapa logístico",
    description: "Pedidos y tiempos de entrega por región, con retrasos e incidencias.",
  },
];

function DlRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 py-1.5">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-right font-medium">{children}</dd>
    </div>
  );
}

function Days({ value }: { value: number | null }) {
  return <>{value === null ? "—" : `${formatInteger(value)} día${value === 1 ? "" : "s"}`}</>;
}

export function OperationsPanels({
  record,
  economic,
  quote,
}: {
  record: OperationsRecord;
  economic?: Pick<EconomicAnalysis, "sale_price">;
  quote?: SupplierQuote;
}) {
  const verdict = OPERATIONS_VERDICT[record.operations_status];
  const order = record.data?.order;
  const coordination = record.data?.supplier_coordination;
  const returns = record.data?.return_policy;
  const ticket = record.data?.support_ticket_example;
  const risks = record.data?.risks ?? [];
  const durations = order ? stageDurations(order.tracking.stages) : undefined;

  return (
    <div className="space-y-4">
      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6" aria-label="Indicadores de la simulación">
        <KpiCard
          label="Estado de la operación"
          value={verdict.title}
          icon={ShieldCheck}
          tone={STATUS_KPI_TONE[verdict.tone]}
          caption={`Recomendación del agente · confianza ${formatPercent(record.confidence, 0)}`}
          provenance="estimated"
          provenanceTooltip="Estado calculado por el agente de operaciones a partir de los análisis económico y legal."
        />
        <KpiCard
          label="Pedido de muestra"
          value={order ? order.order_id : "—"}
          icon={PackageCheck}
          caption={order ? `${formatInteger(order.quantity)} unidad${order.quantity === 1 ? "" : "es"}` : "Sin pedido simulado"}
          provenance="estimated"
          provenanceTooltip="Un único pedido ilustrativo: no hay pedidos reales."
        />
        <KpiCard
          label="Entrega prevista"
          value={durations?.total != null ? `día ${durations.total}` : "—"}
          icon={CalendarClock}
          caption="Días desde el pedido, según el plazo del proveedor"
          provenance="estimated"
          provenanceTooltip="Se apoya en el plazo de entrega real de la cotización más otros tiempos fijos de simulación."
        />
        <KpiCard
          label="Ventana de devolución"
          value={returns ? `${formatInteger(returns.eligibility_window_days)} días` : "—"}
          icon={RotateCcw}
          caption="Política por mercado"
          provenance="estimated"
          provenanceTooltip="Política de devoluciones simulada por mercado."
        />
        <KpiCard
          label="Cargo de reposición"
          value={returns ? formatPercent(returns.restocking_fee_percent, 0) : "—"}
          icon={Percent}
          caption="Sobre el precio de venta"
          provenance="estimated"
          provenanceTooltip="Política de devoluciones simulada por mercado."
        />
        <KpiCard
          label="Reembolso estimado"
          value={returns?.refund_estimate != null ? formatAmount(returns.refund_estimate) : "—"}
          icon={ReceiptText}
          caption={returns?.refund_estimate != null ? "Precio de venta menos el cargo" : "Falta el análisis económico"}
          provenance="estimated"
          provenanceTooltip="Calculado por el agente a partir del precio de venta del análisis económico."
        />
      </section>

      <section className="grid gap-4 xl:grid-cols-12">
        <Card className="xl:col-span-7">
          <CardHeader>
            <CardTitle>Seguimiento del pedido de muestra</CardTitle>
            <CardAction>
              <DataProvenanceBadge
                status="estimated"
                tooltip="Línea de tiempo simulada: los días son relativos al pedido y usan el plazo de entrega real de la cotización."
              />
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-5">
            {order ? (
              <>
                <ol className="space-y-0">
                  {order.tracking.stages.map((stage, index, all) => (
                    <li key={stage.stage} className="relative flex gap-3 pb-4 last:pb-0">
                      {index < all.length - 1 ? (
                        <span className="absolute top-5 left-[7px] h-full w-px bg-border" aria-hidden />
                      ) : null}
                      <span
                        className={cn(
                          "relative mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full border",
                          index === all.length - 1 ? "border-primary bg-primary text-primary-foreground" : "border-primary/60 bg-background",
                        )}
                      >
                        {index === all.length - 1 ? <Check className="size-2.5" /> : null}
                      </span>
                      <div className="flex flex-1 items-baseline justify-between gap-3">
                        <p className="text-sm font-medium">{stageLabel(stage.stage)}</p>
                        <p className="shrink-0 text-xs tabular-nums text-muted-foreground">día {stage.day_offset}</p>
                      </div>
                    </li>
                  ))}
                </ol>
                {durations ? (
                  <dl className="grid grid-cols-2 gap-3 border-t pt-4 text-xs sm:grid-cols-4">
                    <div>
                      <dt className="text-muted-foreground">Procesamiento</dt>
                      <dd className="mt-0.5 text-sm font-medium">
                        <Days value={durations.processing} />
                      </dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">Hasta el despacho</dt>
                      <dd className="mt-0.5 text-sm font-medium">
                        <Days value={durations.toShip} />
                      </dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">Tránsito</dt>
                      <dd className="mt-0.5 text-sm font-medium">
                        <Days value={durations.transit} />
                      </dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">Total</dt>
                      <dd className="mt-0.5 text-sm font-medium text-primary">
                        <Days value={durations.total} />
                      </dd>
                    </div>
                  </dl>
                ) : null}
              </>
            ) : (
              <p className="text-sm text-muted-foreground">El informe no incluye pedido de muestra.</p>
            )}
            <div className="flex flex-wrap items-center gap-2 rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
              <DataProvenanceBadge
                status="pending"
                tooltip="No hay transportistas ni tracking real: no existen horas de recogida ni números de seguimiento."
              />
              Fechas y horas reales, transportista y número de tracking: sin datos.
            </div>
          </CardContent>
        </Card>

        <Card className="xl:col-span-5">
          <CardHeader>
            <CardTitle>Proveedor y modelo sin stock</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <dl className="divide-y text-sm">
              <DlRow label="Proveedor">
                {quote ? (
                  <>
                    {quote.data?.name ?? quote.supplier_id}
                    <span className="block text-xs font-normal text-muted-foreground">{regionLabel(quote.data?.region)}</span>
                  </>
                ) : (
                  "—"
                )}
              </DlRow>
              <DlRow label="Plazo de entrega usado">
                {order ? `${formatInteger(order.tracking.lead_time_days_used)} días` : "—"}
              </DlRow>
              <DlRow label="Plazo real del proveedor">
                {coordination?.lead_time_days != null ? `${formatInteger(coordination.lead_time_days)} días` : "Desconocido"}
              </DlRow>
              <DlRow label="Proveedor verificado">
                {coordination?.supplier_verified == null ? "Sin dato" : coordination.supplier_verified ? "Sí" : "No"}
              </DlRow>
            </dl>

            <div>
              <p className="mb-1.5 text-xs font-medium text-muted-foreground">Pedido de muestra: cobro y pago</p>
              <dl className="divide-y rounded-lg border px-3 text-sm">
                <DlRow label="Cobro al cliente">{economic ? formatAmount(economic.sale_price) : "—"}</DlRow>
                <DlRow label="Pago al proveedor (precio unitario)">{quote ? formatAmount(quote.unit_price) : "—"}</DlRow>
                <DlRow label="Logística y aduana">{quote ? formatAmount(quote.logistics_cost_per_unit) : "—"}</DlRow>
              </dl>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <DataProvenanceBadge
                  status="pending"
                  tooltip="No hay fechas de cobro y pago reales, así que no se puede calcular el capital adelantado ni el desfase."
                />
                Capital adelantado, desfase entre cobro y pago y cobertura.
              </div>
            </div>
          </CardContent>
        </Card>
      </section>

      <section className="grid gap-4 xl:grid-cols-12">
        <Card className="xl:col-span-4">
          <CardHeader>
            <CardTitle>Devoluciones</CardTitle>
            <CardAction>
              <RotateCcw className="size-4 text-primary" />
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-3">
            {returns ? (
              <dl className="divide-y text-sm">
                <DlRow label="Ventana de devolución">{formatInteger(returns.eligibility_window_days)} días</DlRow>
                <DlRow label="Cargo de reposición">{formatPercent(returns.restocking_fee_percent, 0)}</DlRow>
                <DlRow label="Reembolso estimado">
                  {returns.refund_estimate != null ? formatAmount(returns.refund_estimate) : "Desconocido"}
                </DlRow>
              </dl>
            ) : (
              <p className="text-sm text-muted-foreground">El informe no incluye política de devoluciones.</p>
            )}
            <div className="flex flex-wrap items-center gap-2 rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
              <DataProvenanceBadge status="pending" tooltip="No hay devoluciones reales que contar." />
              Tasa de devolución, abiertas/en revisión/recibidas y principales motivos.
            </div>
          </CardContent>
        </Card>

        <Card className="xl:col-span-4">
          <CardHeader>
            <CardTitle>Soporte postventa</CardTitle>
            <CardAction>
              <PackageSearch className="size-4 text-primary" />
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-3">
            {ticket ? (
              <>
                <div className="rounded-lg border bg-background/50 p-3">
                  <p className="text-xs text-muted-foreground">Ticket de ejemplo</p>
                  <p className="mt-1 text-sm font-medium">{ticketTypeLabel(ticket.ticket_type)}</p>
                  <p className={cn("mt-2 text-sm font-medium", ticket.ai_resolvable ? "text-primary" : "text-amber-500")}>
                    {ticket.ai_resolvable ? "Lo resuelve la IA" : "Se escala a una persona"}
                  </p>
                  {ticket.escalation_reason ? (
                    <p className="mt-1 text-xs text-muted-foreground">{ticket.escalation_reason}</p>
                  ) : null}
                </div>
                <p className="text-[11px] text-muted-foreground">
                  Triaje IA/humano de un único ticket ilustrativo (motivo en inglés, tal cual el backend); no hay
                  sistema de tickets.
                </p>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">El informe no incluye ticket de soporte.</p>
            )}
          </CardContent>
        </Card>

        <Card className="xl:col-span-4">
          <CardHeader>
            <CardTitle>Estado y riesgos</CardTitle>
            <CardAction>
              <Timer className="size-4 text-primary" />
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-4">
            <VerdictBanner tone={verdict.tone} title={verdict.title} detail={verdict.detail} />
            <RiskList risks={risks} />
            {risks.length > 0 ? (
              <p className="text-[11px] text-muted-foreground">Textos de la plantilla del agente (en inglés).</p>
            ) : (
              <p className="text-xs text-muted-foreground">El agente no registra riesgos.</p>
            )}
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Wallet className="size-3.5" />
              Siguiente: Finanzas y control.
            </div>
          </CardContent>
        </Card>
      </section>

      <PendingFeatures
        title="Control Tower — pendiente de backend"
        tooltip="Requieren pedidos, clientes, transportistas y ticketing reales; hoy el agente solo simula un pedido."
        items={PENDING_CONTROL_TOWER}
        columns={4}
        note="La spec define Operaciones como el Control Tower de AMAZONA, no como un generador de informes. Hoy solo existe un agente que simula un pedido de muestra; sin pedidos reales no hay KPIs, pipeline, incidencias, proveedores ni transportistas que medir."
      />
    </div>
  );
}
