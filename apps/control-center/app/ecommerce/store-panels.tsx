"use client";

import { useState } from "react";
import {
  BarChart3,
  Check,
  Circle,
  CreditCard,
  FlaskConical,
  Funnel,
  Gauge,
  Lightbulb,
  Monitor,
  PackageSearch,
  Smartphone,
} from "lucide-react";
import type { EconomicAnalysis, LegalAnalysis, Storefront } from "@/lib/api";
import { contentChecklist, launchReadiness, marketRows, type ChecklistState, type MarketRow } from "@/lib/ecommerce";
import { formatAmount } from "@/lib/format";
import { marketLabel } from "@/lib/markets";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { PendingFeatures, type PendingFeature } from "@/components/pending-features";
import { RiskList } from "@/components/risk-list";
import { SectionNav } from "@/components/section-nav";
import { StatusChip } from "@/components/status-chip";
import { VerdictBanner, type VerdictTone } from "@/components/verdict-banner";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const LAUNCH_VERDICT: Record<Storefront["launch_status"], { tone: VerdictTone; title: string; detail: string }> = {
  READY: {
    tone: "ok",
    title: "Borrador listo para revisión",
    detail: "Economía y legal no bloquean. Sigue siendo un borrador simulado: no hay tienda, dominio ni pagos reales.",
  },
  NEEDS_REVIEW: {
    tone: "warn",
    title: "Requiere revisión",
    detail: "Falta algún análisis previo o alguno pide revisión humana antes de lanzar.",
  },
  BLOCKED: {
    tone: "bad",
    title: "Bloqueado",
    detail: "El análisis económico o el legal recomiendan no continuar.",
  },
};

const PENDING_STORE_FEATURES: PendingFeature[] = [
  {
    icon: Gauge,
    title: "Calidad del escaparate",
    description: "Score de contenido, conversión, SEO, confianza, legal, mobile y velocidad estimada.",
  },
  {
    icon: Funnel,
    title: "Funnel de compra (estimado / real)",
    description: "Visitas, producto, carrito, checkout, compra y conversión, distinguiendo estimado de real.",
  },
  {
    icon: FlaskConical,
    title: "A/B testing y páginas",
    description: "Variantes de la página, páginas adicionales y pruebas de conversión.",
  },
  {
    icon: BarChart3,
    title: "Analytics y tracking",
    description: "Medición de visitas y conversiones, píxeles y seguimiento de pedidos.",
  },
];

const READINESS_ICON: Record<ChecklistState, typeof Check> = { done: Check, todo: Circle, pending: Circle };

function DlRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 py-1.5">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-right font-medium">{children}</dd>
    </div>
  );
}

function StorefrontPreview({ storefront }: { storefront: Storefront }) {
  const [device, setDevice] = useState<"desktop" | "mobile">("desktop");
  const copy = storefront.data?.landing_page_copy;

  return (
    <Card id="vista-previa" className="scroll-mt-4 xl:col-span-7">
      <CardHeader>
        <CardTitle>Constructor de página (Tienda propia)</CardTitle>
        <CardAction>
          <DataProvenanceBadge
            status="estimated"
            tooltip="Texto de un generador de plantillas determinista, no de un modelo de IA ni de datos verificados."
          />
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-4">
        <SectionNav
          label="Secciones del constructor de página"
          items={[
            { label: "Vista previa", href: "#vista-previa" },
            { label: "Editar contenido", pendingReason: "Pendiente: el backend no permite editar el borrador" },
            { label: "SEO", pendingReason: "Pendiente: el generador no produce SEO" },
            { label: "Diseño", pendingReason: "Pendiente: no hay temas ni plantillas visuales" },
            { label: "Páginas", pendingReason: "Pendiente: solo se genera una página de producto" },
            { label: "A/B testing", pendingReason: "Pendiente: no hay experimentos" },
          ]}
        />

        <div className="overflow-hidden rounded-xl border bg-background/60">
          <div className="flex items-center justify-between gap-2 border-b px-3 py-2">
            <span className="truncate rounded-md bg-muted px-2 py-1 text-[11px] text-muted-foreground">
              Borrador sin publicar · {storefront.store_slug}
            </span>
            <div className="flex shrink-0 gap-1" role="group" aria-label="Tamaño de la vista previa">
              <Button
                type="button"
                size="xs"
                variant={device === "desktop" ? "secondary" : "ghost"}
                aria-pressed={device === "desktop"}
                onClick={() => setDevice("desktop")}
              >
                <Monitor /> Desktop
              </Button>
              <Button
                type="button"
                size="xs"
                variant={device === "mobile" ? "secondary" : "ghost"}
                aria-pressed={device === "mobile"}
                onClick={() => setDevice("mobile")}
              >
                <Smartphone /> Mobile
              </Button>
            </div>
          </div>

          {copy ? (
            <div className="flex justify-center bg-muted/30 p-4">
              <div
                data-testid="storefront-preview"
                data-device={device}
                className={cn(
                  "w-full rounded-lg bg-card p-4 ring-1 ring-foreground/10",
                  device === "mobile" ? "max-w-[300px]" : "max-w-full",
                )}
              >
                <div className={cn("grid gap-4", device === "desktop" && "sm:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]")}>
                  <div className="flex aspect-square items-center justify-center rounded-lg border border-dashed text-muted-foreground">
                    <div className="space-y-1 text-center">
                      <PackageSearch className="mx-auto size-8" />
                      <p className="text-[11px]">Sin imágenes: el backend aún no genera multimedia</p>
                    </div>
                  </div>
                  <div className="min-w-0 space-y-3">
                    <h3 className="text-lg leading-tight font-semibold">{copy.headline}</h3>
                    <p className="text-sm text-muted-foreground">{copy.subheadline}</p>
                    <p className="text-2xl font-semibold">{copy.price_display}</p>
                    <ul className="list-inside list-disc space-y-0.5 text-sm">
                      {copy.bullets.map((bullet) => (
                        <li key={bullet}>{bullet}</li>
                      ))}
                    </ul>
                    <Button type="button" className="w-full" disabled>
                      {copy.cta}
                    </Button>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <p className="p-6 text-center text-sm text-muted-foreground">El borrador no incluye texto de la página.</p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function CheckoutPlan({ storefront }: { storefront: Storefront }) {
  const plan = storefront.data?.payment_gateway_plan;
  return (
    <Card className="xl:col-span-5">
      <CardHeader>
        <CardTitle>Checkout y pagos</CardTitle>
        <CardAction>
          <DataProvenanceBadge
            status="estimated"
            tooltip="Plan de pasarela simulado por mercado. No hay procesamiento de pagos real."
          />
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-4">
        {plan ? (
          <>
            <div className="flex items-center gap-3 rounded-lg border bg-background/50 p-3">
              <CreditCard className="size-5 shrink-0 text-primary" />
              <div className="min-w-0">
                <p className="text-sm font-medium">{plan.gateway}</p>
                <p className="text-xs text-muted-foreground">
                  Modo {plan.mode === "test" ? "prueba" : plan.mode} ·{" "}
                  {plan.requires_human_approval
                    ? "salir en vivo requiere aprobación humana"
                    : "sin aprobación humana requerida"}
                </p>
              </div>
            </div>
            <div>
              <p className="mb-1.5 text-xs font-medium text-muted-foreground">Pasos hasta salir en vivo</p>
              <ol className="list-inside list-decimal space-y-1 text-sm">
                {plan.checklist.map((step) => (
                  <li key={step}>{step}</li>
                ))}
              </ol>
            </div>
          </>
        ) : (
          <p className="text-sm text-muted-foreground">El borrador no incluye plan de pasarela de pago.</p>
        )}
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
          <DataProvenanceBadge
            status="pending"
            tooltip="El backend no guarda el modo de checkout ni los métodos de pago elegidos."
          />
          Modo de checkout y métodos de pago (tarjeta, Apple Pay, Google Pay, PayPal…): no configurables todavía.
        </div>
      </CardContent>
    </Card>
  );
}

const MARKET_COLUMNS: DataTableColumn<MarketRow>[] = [
  { key: "market", header: "Mercado", cell: (row) => <span className="font-medium">{marketLabel(row.market)}</span>, sortValue: (row) => row.market },
  {
    key: "price",
    header: "Precio",
    cell: (row) => (row.price === null ? <span className="text-muted-foreground">Por definir</span> : formatAmount(row.price)),
  },
  { key: "status", header: "Estado", cell: (row) => <StatusChip status={row.launchStatus} /> },
];

export function StorePanels({
  storefront,
  storefronts,
  legal,
  economic,
  onOptimizeAmazon,
}: {
  storefront: Storefront;
  storefronts: Storefront[];
  legal?: Pick<LegalAnalysis, "recommendation">;
  economic?: Pick<EconomicAnalysis, "recommendation">;
  onOptimizeAmazon: () => void;
}) {
  const verdict = LAUNCH_VERDICT[storefront.launch_status];
  const readiness = launchReadiness({ economic, storefront, legal });
  const content = contentChecklist(storefront);
  const risks = storefront.data?.risks ?? [];
  const tips = storefront.data?.conversion_tips ?? [];
  const catalog = storefront.data?.catalog_entry;

  return (
    <div className="space-y-4">
      <section className="grid gap-4 xl:grid-cols-12">
        <StorefrontPreview storefront={storefront} />
        <CheckoutPlan storefront={storefront} />
      </section>

      <section className="grid gap-4 xl:grid-cols-12">
        <Card className="xl:col-span-6">
          <CardHeader>
            <CardTitle>Launch readiness</CardTitle>
            <CardAction>
              <DataProvenanceBadge
                status="estimated"
                tooltip="Estado calculado por el agente de e-commerce a partir de los análisis económico y legal más recientes."
              />
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-4">
            <VerdictBanner tone={verdict.tone} title={verdict.title} detail={verdict.detail} />
            <RiskList risks={risks} />
            <ul className="grid gap-x-4 gap-y-1.5 sm:grid-cols-2">
              {readiness.map((item) => {
                const Icon = READINESS_ICON[item.state];
                return (
                  <li key={item.key} className="flex items-start gap-2 text-sm" title={item.detail}>
                    <span
                      className={cn(
                        "mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full border",
                        item.state === "done" && "border-primary bg-primary text-primary-foreground",
                        item.state === "todo" && "border-amber-500/60 text-amber-500",
                        item.state === "pending" && "border-border text-muted-foreground",
                      )}
                    >
                      <Icon className="size-2.5" />
                    </span>
                    <span className={cn(item.state === "pending" && "text-muted-foreground")}>
                      {item.label}
                      <span className="block text-[11px] text-muted-foreground">
                        {item.state === "pending" ? "Pendiente de backend" : item.detail}
                      </span>
                    </span>
                  </li>
                );
              })}
            </ul>
            <div className="flex flex-wrap items-center gap-2 border-t pt-3">
              <Button type="button" disabled title="Pendiente: el backend aún no expone esta acción">
                Solicitar aprobación de lanzamiento
              </Button>
              <DataProvenanceBadge
                status="pending"
                tooltip="No existe un endpoint que cree la solicitud de aprobación de lanzamiento."
              />
              <Button type="button" variant="outline" onClick={onOptimizeAmazon}>
                Optimizar listado de Amazon
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card className="xl:col-span-6">
          <CardHeader>
            <CardTitle>Configuración por mercado</CardTitle>
            <CardAction>
              <DataProvenanceBadge status="estimated" tooltip="Un borrador de tienda por mercado, generado por el agente." />
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-3">
            <DataTable
              columns={MARKET_COLUMNS}
              rows={marketRows(storefronts)}
              getRowId={(row) => row.market}
              emptyMessage="Aún no hay mercados con tienda generada."
            />
            <p className="text-[11px] text-muted-foreground">
              Idioma y disponibilidad por país: pendientes, el backend no los guarda. Para añadir un mercado, cámbialo
              arriba y genera su tienda.
            </p>
          </CardContent>
        </Card>
      </section>

      <section className="grid gap-4 xl:grid-cols-12">
        <Card className="xl:col-span-4">
          <CardHeader>
            <CardTitle>Contenido generado</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-1.5">
              {content.map((item) => (
                <li key={item.label} className="flex items-center gap-2 text-sm">
                  <span
                    className={cn(
                      "flex size-4 shrink-0 items-center justify-center rounded-full border",
                      item.generated ? "border-primary bg-primary text-primary-foreground" : "border-border text-muted-foreground",
                    )}
                  >
                    {item.generated ? <Check className="size-2.5" /> : null}
                  </span>
                  <span className={cn("flex-1", !item.generated && "text-muted-foreground")}>{item.label}</span>
                  {!item.generated ? <DataProvenanceBadge status="pending" tooltip="El generador no produce esta pieza." /> : null}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>

        <Card className="xl:col-span-4">
          <CardHeader>
            <CardTitle>Producto maestro</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <dl className="divide-y text-sm">
              <DlRow label="SKU">{catalog?.sku ?? "—"}</DlRow>
              <DlRow label="Categoría">{catalog?.category ?? "—"}</DlRow>
              <DlRow label="Plazo de entrega">
                {catalog?.lead_time_days != null ? `${catalog.lead_time_days} días` : "Desconocido"}
              </DlRow>
              <DlRow label="Categoría restringida">
                {catalog?.restricted == null ? "Sin dato" : catalog.restricted ? "Sí" : "No"}
              </DlRow>
            </dl>
            <div className="flex flex-wrap items-center gap-2 rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
              <DataProvenanceBadge status="pending" tooltip="El backend no guarda estos campos del producto." />
              EAN/GTIN, peso, dimensiones, stock del proveedor, certificaciones y multimedia.
            </div>
          </CardContent>
        </Card>

        <Card className="xl:col-span-4">
          <CardHeader>
            <CardTitle>Consejos de conversión</CardTitle>
            <CardAction>
              <Lightbulb className="size-4 text-primary" />
            </CardAction>
          </CardHeader>
          <CardContent>
            {tips.length > 0 ? (
              <ul className="list-inside list-disc space-y-1.5 text-sm">
                {tips.map((tip) => (
                  <li key={tip}>{tip}</li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">El agente no ha dado consejos para este borrador.</p>
            )}
            <p className="mt-3 text-[11px] text-muted-foreground">Textos de la plantilla del agente (en inglés).</p>
          </CardContent>
        </Card>
      </section>

      <PendingFeatures
        title="Pendiente de backend"
        tooltip="Requieren una tienda publicada, analítica y datos de tráfico que el backend aún no tiene."
        items={PENDING_STORE_FEATURES}
        columns={4}
        note="Hoy el agente solo genera un borrador de tienda: texto de la página, plan de pasarela en modo prueba y entrada de catálogo. No hay tienda, dominio, tráfico ni pagos reales, así que no hay funnel ni score de calidad que mostrar."
      />
    </div>
  );
}
