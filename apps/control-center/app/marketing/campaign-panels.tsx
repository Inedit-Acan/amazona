"use client";

import { useState } from "react";
import {
  BarChart3,
  Brain,
  CircleDollarSign,
  Funnel,
  Lightbulb,
  LineChart,
  MousePointerClick,
  Percent,
  PieChart,
  ShieldCheck,
  Target,
  TrendingUp,
  Wallet,
} from "lucide-react";
import type { MarketingCampaign } from "@/lib/api";
import { formatAmount, formatInteger, formatPercent } from "@/lib/format";
import { AGENT_GUARDRAILS, CAMPAIGN_VERDICT, audienceBars, platformLabel } from "@/lib/marketing";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { KpiCard, type KpiTone } from "@/components/kpi-card";
import { PendingFeatures, type PendingFeature } from "@/components/pending-features";
import { RiskList } from "@/components/risk-list";
import { VerdictBanner } from "@/components/verdict-banner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const STATUS_KPI_TONE: Record<"ok" | "warn" | "bad", KpiTone> = { ok: "success", warn: "warning", bad: "danger" };

const PENDING_PERFORMANCE: PendingFeature[] = [
  {
    icon: CircleDollarSign,
    title: "Inversión, ingresos atribuidos, CAC y conversiones reales",
    description: "Se leen de las plataformas publicitarias: hoy no hay integración ni gasto real.",
  },
  {
    icon: Funnel,
    title: "Funnel de conversión",
    description: "Impresiones, clics, landing, carrito, checkout y compra, distinguiendo estimado de real.",
  },
  {
    icon: LineChart,
    title: "Rendimiento por canal",
    description: "Serie temporal de inversión, ingresos, ROAS y CAC por canal.",
  },
  {
    icon: PieChart,
    title: "Atribución de ingresos",
    description: "Último clic, primer clic, lineal y data-driven, con ingresos atribuidos por canal.",
  },
];

/** Vista previa del texto real de la propuesta en el formato de cada plataforma.
 * Solo Meta (feed) y Google (búsqueda) existen en el backend. */
type PreviewTab = "meta" | "google";

function AdPreview({ creative, initial }: { creative: NonNullable<NonNullable<MarketingCampaign["data"]>["ad_creative"]>; initial: PreviewTab }) {
  const [tab, setTab] = useState<PreviewTab>(initial);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Plataforma de la vista previa">
        {(["meta", "google"] as const).map((key) => (
          <Button
            key={key}
            type="button"
            size="xs"
            variant={tab === key ? "secondary" : "ghost"}
            aria-pressed={tab === key}
            onClick={() => setTab(key)}
          >
            {key === "meta" ? "Meta · feed" : "Google · búsqueda"}
          </Button>
        ))}
        {["Instagram", "TikTok"].map((name) => (
          <Button key={name} type="button" size="xs" variant="ghost" disabled title="Pendiente: no hay integración">
            {name}
          </Button>
        ))}
      </div>

      <div data-testid="ad-preview" data-platform={tab} className="mx-auto max-w-sm rounded-xl border bg-background/60 p-3">
        {tab === "meta" ? (
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-xs">
              <span className="flex size-6 items-center justify-center rounded-full bg-primary text-[10px] font-semibold text-primary-foreground">
                A
              </span>
              <span className="font-medium">Amazona</span>
              <span className="text-muted-foreground">· Publicidad</span>
            </div>
            <p className="text-sm">{creative.primary_text}</p>
            <div className="flex aspect-video items-center justify-center rounded-md border border-dashed p-3 text-center text-[11px] text-muted-foreground">
              Sin imagen: el backend solo genera un brief de texto
            </div>
            <div className="flex items-center justify-between gap-2 rounded-md bg-muted/40 p-2">
              <p className="min-w-0 text-sm font-semibold">{creative.headline}</p>
              <Button type="button" size="xs" disabled>
                {creative.cta}
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-1">
            <p className="text-[11px] font-semibold">Anuncio</p>
            <p className="text-base font-medium text-primary">{creative.headline}</p>
            <p className="text-sm text-muted-foreground">{creative.primary_text}</p>
          </div>
        )}
      </div>
    </div>
  );
}

export function CampaignPanels({
  campaign,
  onValidate,
}: {
  campaign: MarketingCampaign;
  onValidate: () => void;
}) {
  const verdict = CAMPAIGN_VERDICT[campaign.campaign_status];
  const performance = campaign.data?.performance_estimate;
  const creative = campaign.data?.ad_creative;
  const audiences = audienceBars(campaign.data?.audience_segments);
  const risks = campaign.data?.risks ?? [];
  const roas = performance?.projected_roas ?? null;
  const previewInitial: PreviewTab = campaign.platform === "google" ? "google" : "meta";

  return (
    <div className="space-y-4">
      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6" aria-label="Indicadores de la propuesta">
        <KpiCard
          label="Presupuesto diario"
          value={formatAmount(campaign.daily_budget)}
          icon={Wallet}
          caption={`Supuesto tuyo · ${platformLabel(campaign.platform)}`}
        />
        <KpiCard
          label="ROAS proyectado"
          value={roas !== null ? `${formatAmount(roas)} x` : "—"}
          icon={TrendingUp}
          caption={roas !== null ? "Conversión × precio ÷ CPC" : "Sin precio de venta todavía"}
          provenance="estimated"
          provenanceTooltip={performance?.data_origin ?? "Estimación simulada; no procede de una plataforma publicitaria."}
        />
        <KpiCard
          label="CPC estimado"
          value={performance ? formatAmount(performance.avg_cpc) : "—"}
          icon={MousePointerClick}
          caption="Coste medio por clic"
          provenance="estimated"
          provenanceTooltip={performance?.data_origin}
        />
        <KpiCard
          label="CTR estimado"
          value={performance ? formatPercent(performance.avg_ctr) : "—"}
          icon={BarChart3}
          caption="Clics sobre impresiones"
          provenance="estimated"
          provenanceTooltip={performance?.data_origin}
        />
        <KpiCard
          label="Conversión estimada"
          value={performance ? formatPercent(performance.conversion_rate) : "—"}
          icon={Percent}
          caption="Compras sobre clics"
          provenance="estimated"
          provenanceTooltip={performance?.data_origin}
        />
        <KpiCard
          label="Estado general"
          value={verdict.title}
          icon={ShieldCheck}
          tone={STATUS_KPI_TONE[verdict.tone]}
          caption={`Recomendación del agente · confianza ${formatPercent(campaign.confidence, 0)}`}
          provenance="estimated"
          provenanceTooltip="Estado calculado por el agente de marketing sobre estimaciones simuladas."
        />
      </section>

      <section className="grid gap-4 xl:grid-cols-12">
        <Card className="xl:col-span-5">
          <CardHeader>
            <CardTitle>Audiencias propuestas</CardTitle>
            <CardAction>
              <DataProvenanceBadge
                status="estimated"
                tooltip="Segmentos generados por plantilla a partir de la categoría y la competencia; el alcance es una cifra fija de simulación."
              />
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-4">
            {audiences.length > 0 ? (
              <ul className="space-y-3">
                {audiences.map((audience) => (
                  <li key={audience.name} className="space-y-1.5">
                    <div className="flex items-baseline justify-between gap-2">
                      <p className="text-sm font-medium">{audience.name}</p>
                      <p className="shrink-0 text-xs tabular-nums text-muted-foreground">
                        ~{formatInteger(audience.reach)} personas
                      </p>
                    </div>
                    <div
                      className="h-1.5 overflow-hidden rounded-full bg-muted"
                      role="img"
                      aria-label={`Alcance relativo de ${audience.name}`}
                    >
                      <div className="h-full rounded-full bg-primary" style={{ width: `${Math.round(audience.share * 100)}%` }} />
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Badge variant="outline">{audience.ageRange} años</Badge>
                      {audience.interests.map((interest) => (
                        <Badge key={interest} variant="outline">
                          {interest}
                        </Badge>
                      ))}
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">La propuesta no incluye segmentos de audiencia.</p>
            )}
            <div className="flex flex-wrap items-center gap-2 rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
              <DataProvenanceBadge
                status="pending"
                tooltip="El backend no puntúa las audiencias ni indica su intención o fuente."
              />
              Score, intención y fuente de cada audiencia (remarketing, lookalike…): sin datos.
            </div>
          </CardContent>
        </Card>

        <Card className="xl:col-span-7">
          <CardHeader>
            <CardTitle>Creatividad y vista previa</CardTitle>
            <CardAction>
              <DataProvenanceBadge
                status="estimated"
                tooltip="Texto generado por plantilla determinista, no por un modelo de IA. No se ha publicado en ninguna plataforma."
              />
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-4">
            {creative ? (
              <div className="grid gap-4 lg:grid-cols-2">
                <div className="space-y-3 text-sm">
                  <div>
                    <p className="text-xs text-muted-foreground">Titular</p>
                    <p className="font-medium">{creative.headline}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">Texto principal</p>
                    <p>{creative.primary_text}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">Llamada a la acción</p>
                    <p className="font-medium">{creative.cta}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">Brief de imagen (texto para un diseñador)</p>
                    <p className="text-xs text-muted-foreground">{creative.image_brief}</p>
                  </div>
                </div>
                <AdPreview key={campaign.correlation_id} creative={creative} initial={previewInitial} />
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">La propuesta no incluye creatividad.</p>
            )}
            <div className="flex flex-wrap items-center gap-2 rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
              <DataProvenanceBadge
                status="pending"
                tooltip="El generador produce una sola creatividad de texto, sin imagen ni vídeo, y no la puntúa."
              />
              Vídeos e imágenes, Creative Score, variantes y estado (aprobado / en revisión / ajustar): sin datos.
            </div>
          </CardContent>
        </Card>
      </section>

      <section className="grid gap-4 xl:grid-cols-12">
        <Card className="xl:col-span-6">
          <CardHeader>
            <CardTitle>Recomendación del agente</CardTitle>
            <CardAction>
              <Lightbulb className="size-4 text-primary" />
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-4">
            <VerdictBanner tone={verdict.tone} title={verdict.title} detail={verdict.detail} />
            {campaign.data?.budget_recommendation ? (
              <div className="rounded-lg border bg-background/50 p-3">
                <p className="text-xs text-muted-foreground">Recomendación de presupuesto</p>
                <p className="mt-1 text-sm">{campaign.data.budget_recommendation}</p>
              </div>
            ) : null}
            <RiskList risks={risks} />
            <p className="text-[11px] text-muted-foreground">Textos de la plantilla del agente (en inglés).</p>
            <div className="flex flex-wrap items-center gap-2 border-t pt-3">
              <Button type="button" onClick={onValidate}>
                <Brain />
                Validar inversión con el Director ejecutivo
              </Button>
              <DataProvenanceBadge
                status="pending"
                tooltip="No existe un endpoint que cree la solicitud de aprobación de inversión: el camino real es validar el gasto con el Director ejecutivo."
              />
            </div>
          </CardContent>
        </Card>

        <Card className="xl:col-span-6">
          <CardHeader>
            <CardTitle>Presupuesto y guardrails</CardTitle>
            <CardAction>
              <Target className="size-4 text-primary" />
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-4">
            <dl className="grid grid-cols-2 gap-3 text-sm">
              <div className="rounded-lg border bg-background/50 p-3">
                <dt className="text-xs text-muted-foreground">Asignado (diario)</dt>
                <dd className="mt-1 text-lg font-semibold">{formatAmount(campaign.daily_budget)}</dd>
              </div>
              <div className="rounded-lg border border-dashed p-3">
                <dt className="text-xs text-muted-foreground">Gastado · restante · pacing</dt>
                <dd className="mt-1">
                  <DataProvenanceBadge status="pending" tooltip="No hay gasto real: no existe integración con plataformas de anuncios." />
                </dd>
              </div>
              <div className="rounded-lg border border-dashed p-3">
                <dt className="text-xs text-muted-foreground">CAC actual · objetivo · máximo</dt>
                <dd className="mt-1">
                  <DataProvenanceBadge status="pending" tooltip="El motor económico no calcula un CAC máximo y no hay CAC real." />
                </dd>
              </div>
              <div className="rounded-lg border bg-background/50 p-3">
                <dt className="text-xs text-muted-foreground">Origen de las cifras</dt>
                <dd className="mt-1 text-xs">Estimación simulada</dd>
              </div>
            </dl>
            <div>
              <p className="mb-1.5 text-xs font-medium text-muted-foreground">Reglas que aplica el agente hoy</p>
              <ul className="divide-y rounded-lg border text-sm">
                {AGENT_GUARDRAILS.map((guardrail) => (
                  <li key={guardrail.rule} className="flex items-start justify-between gap-3 px-3 py-2">
                    <span>{guardrail.rule}</span>
                    <span
                      className={cn(
                        "shrink-0 text-xs font-medium",
                        guardrail.effect === "Bloquea la propuesta" ? "text-red-500" : "text-amber-500",
                      )}
                    >
                      {guardrail.effect}
                    </span>
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-[11px] text-muted-foreground">
                Pausar por CAC o ROAS reales, limitar subidas bruscas de presupuesto y bloquear claims o mercados no
                autorizados necesitan gasto real y siguen pendientes.
              </p>
            </div>
          </CardContent>
        </Card>
      </section>

      <PendingFeatures
        title="Rendimiento real — pendiente de backend"
        tooltip="Requieren integrar plataformas publicitarias y tráfico real; hoy solo hay estimaciones simuladas."
        items={PENDING_PERFORMANCE}
        columns={4}
        note="Todo lo que ves en esta pantalla son estimaciones simuladas por categoría y plataforma. Hasta que haya integración con Meta/Google/TikTok Ads no existen inversión, ingresos atribuidos, CAC, conversiones ni funnel reales."
      />
    </div>
  );
}
