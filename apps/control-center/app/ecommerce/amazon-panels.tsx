"use client";

import { ArrowRight } from "lucide-react";
import type { MarketplaceListing } from "@/lib/api";
import { formatAmount, formatInteger, formatPercent } from "@/lib/format";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { RiskList } from "@/components/risk-list";
import { VerdictBanner, type VerdictTone } from "@/components/verdict-banner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const LISTING_VERDICT: Record<MarketplaceListing["listing_status"], { tone: VerdictTone; title: string; detail: string }> = {
  READY: {
    tone: "ok",
    title: "Listado listo para revisión",
    detail: "Economía y legal no bloquean. Es un borrador simulado: no se ha publicado nada en Amazon.",
  },
  NEEDS_REVIEW: {
    tone: "warn",
    title: "Requiere revisión",
    detail: "Falta algún análisis previo o alguno pide revisión humana antes de publicar.",
  },
  BLOCKED: {
    tone: "bad",
    title: "Bloqueado",
    detail: "El análisis económico o el legal recomiendan no continuar.",
  },
};

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border bg-background/50 p-3">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-1 text-lg font-semibold">{value}</dd>
    </div>
  );
}

export function AmazonPanels({
  listing,
  onPlanMarketing,
}: {
  listing: MarketplaceListing;
  onPlanMarketing: () => void;
}) {
  const content = listing.data?.listing_content;
  const competition = listing.data?.competition_analysis;
  const commission = listing.data?.commission_breakdown;
  const inventory = listing.data?.inventory_policy;
  const verdict = LISTING_VERDICT[listing.listing_status];
  const netMargin = commission?.net_margin_per_unit;

  return (
    <div className="space-y-4">
      <section className="grid gap-4 xl:grid-cols-12">
        <Card className="xl:col-span-7">
          <CardHeader>
            <CardTitle>Listado de Amazon</CardTitle>
            <CardAction>
              <DataProvenanceBadge
                status="estimated"
                tooltip="Contenido generado por plantilla determinista; no se ha publicado en Amazon."
              />
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-4">
            {content ? (
              <>
                <div className="rounded-lg border bg-background/50 p-4">
                  <p className="text-xs text-muted-foreground">Título</p>
                  <p className="mt-1 font-medium">{content.title}</p>
                </div>
                <div>
                  <p className="mb-1.5 text-xs font-medium text-muted-foreground">Puntos clave</p>
                  <ul className="list-inside list-disc space-y-1 text-sm">
                    {content.bullet_points.map((bullet) => (
                      <li key={bullet}>{bullet}</li>
                    ))}
                  </ul>
                </div>
                <div>
                  <p className="mb-1.5 text-xs font-medium text-muted-foreground">Palabras clave internas</p>
                  <div className="flex flex-wrap gap-1.5">
                    {content.backend_keywords.map((keyword) => (
                      <Badge key={keyword} variant="outline">
                        {keyword}
                      </Badge>
                    ))}
                  </div>
                </div>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">El borrador no incluye contenido del listado.</p>
            )}
          </CardContent>
        </Card>

        <Card className="xl:col-span-5">
          <CardHeader>
            <CardTitle>Comisiones del canal</CardTitle>
            <CardAction>
              <DataProvenanceBadge
                status="estimated"
                tooltip="Tarifas de un directorio de marketplaces simulado; el margen neto usa el coste entregado real de la cotización."
              />
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-4">
            {commission ? (
              <>
                <dl className="grid grid-cols-2 gap-3">
                  <Metric label="Comisión de referencia" value={formatPercent(commission.referral_fee_percent, 0)} />
                  <Metric label="Logística por unidad" value={formatAmount(commission.fulfillment_fee_per_unit)} />
                </dl>
                <div className="rounded-lg border bg-background/50 p-4">
                  <p className="text-xs text-muted-foreground">Margen neto por unidad</p>
                  <p
                    className={cn(
                      "mt-1 text-2xl font-semibold",
                      netMargin != null && netMargin < 0 && "text-destructive",
                    )}
                  >
                    {netMargin != null ? formatAmount(netMargin) : "—"}
                  </p>
                  {netMargin == null ? (
                    <p className="mt-1 text-xs text-muted-foreground">
                      Desconocido: falta el análisis económico con precio de venta.
                    </p>
                  ) : null}
                </div>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">El borrador no incluye desglose de comisiones.</p>
            )}
          </CardContent>
        </Card>
      </section>

      <section className="grid gap-4 xl:grid-cols-12">
        <Card className="xl:col-span-6">
          <CardHeader>
            <CardTitle>Análisis de competencia</CardTitle>
            <CardAction>
              <DataProvenanceBadge
                status="estimated"
                tooltip={competition?.data_origin ?? "Datos de competencia de un directorio simulado."}
              />
            </CardAction>
          </CardHeader>
          <CardContent>
            {competition ? (
              <dl className="grid grid-cols-2 gap-3">
                <Metric label="Competidores" value={formatInteger(competition.competitor_count)} />
                <Metric label="Precio medio" value={formatAmount(competition.avg_price)} />
                <Metric label="Valoración media" value={competition.avg_rating.toFixed(1).replace(".", ",")} />
                <Metric label="Dificultad de buy-box" value={competition.buy_box_difficulty} />
              </dl>
            ) : (
              <p className="text-sm text-muted-foreground">El borrador no incluye análisis de competencia.</p>
            )}
          </CardContent>
        </Card>

        <Card className="xl:col-span-6">
          <CardHeader>
            <CardTitle>Estado del listado</CardTitle>
            <CardAction>
              <DataProvenanceBadge
                status="estimated"
                tooltip="Estado calculado por el agente a partir de los análisis económico y legal más recientes."
              />
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-4">
            <VerdictBanner tone={verdict.tone} title={verdict.title} detail={verdict.detail} />
            {inventory ? (
              <dl className="space-y-1.5 text-sm">
                <div className="flex justify-between gap-3">
                  <dt className="text-muted-foreground">Cumplimiento (fulfillment)</dt>
                  <dd className="text-right font-medium">{inventory.fulfillment_method}</dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-muted-foreground">Seguimiento de inventario</dt>
                  <dd className="font-medium">{inventory.tracking_enabled ? "Activado" : "Desactivado"}</dd>
                </div>
              </dl>
            ) : null}
            <RiskList risks={listing.data?.risks ?? []} />
            <Button type="button" onClick={onPlanMarketing}>
              Planificar campaña de marketing
              <ArrowRight />
            </Button>
          </CardContent>
        </Card>
      </section>
    </div>
  );
}
