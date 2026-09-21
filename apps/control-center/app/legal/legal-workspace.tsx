"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  ArrowRight,
  Bell,
  Brain,
  Calculator,
  FileText,
  Gauge,
  Landmark,
  Layers,
  Loader2,
  Megaphone,
  PackageSearch,
  Scale,
  ScrollText,
  Share2,
  ShieldAlert,
  Store,
  Users,
  Award,
  Gavel,
} from "lucide-react";
import { ApiError, api, type LegalAnalysis, type Product, type SupplierQuote } from "@/lib/api";
import {
  certificationsDeclared,
  changesNewestFirst,
  gateReasons,
  legalGate,
  requirementRows,
  type RequirementRow,
} from "@/lib/legal";
import { MARKET_LABELS, latestForMarket, marketLabel } from "@/lib/markets";
import { formatPercent } from "@/lib/format";
import { regionLabel } from "@/lib/regions";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { KpiCard, type KpiTone } from "@/components/kpi-card";
import { NextStepBar } from "@/components/next-step-bar";
import { PendingFeatures, type PendingFeature } from "@/components/pending-features";
import { ProductHeader } from "@/components/product-header";
import { RiskList } from "@/components/risk-list";
import { SectionNav } from "@/components/section-nav";
import { StatusChip } from "@/components/status-chip";
import { VerdictBanner } from "@/components/verdict-banner";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const INPUT_CLASS = "w-full rounded-md border bg-background px-3 py-2 text-sm";
const SIMULATED_SOURCE = "Dataset regulatorio simulado";

/** Secciones del mockup (spec §8) que el agente legal no puede alimentar: hoy
 * solo consulta un dataset regulatorio simulado por categoría × mercado. */
const PENDING_SECTIONS: PendingFeature[] = [
  {
    icon: Landmark,
    title: "Fuentes regulatorias",
    description:
      "Consulta automática de Comisión Europea, Access2Markets, ECHA/REACH/SCIP, Safety Gate y legislación nacional, con fecha de la última consulta.",
  },
  {
    icon: Users,
    title: "Rol en la operación",
    description:
      "Fabricante, importador, distribuidor, vendedor al consumidor, marketplace o representante autorizado, con aviso de obligaciones adicionales.",
  },
  {
    icon: Share2,
    title: "Mapa de responsabilidades",
    description: "Obligaciones por actor en la cadena proveedor → AMAZONA → cliente.",
  },
  {
    icon: FileText,
    title: "Documentación del producto",
    description:
      "Declaración de conformidad, informes, manuales y etiquetas con versión, fecha, proveedor, revisión, hash y estado.",
  },
];

const PENDING_NAV = [
  { label: "Documentación", icon: FileText },
  { label: "Fuentes regulatorias", icon: Landmark },
  { label: "Responsabilidades", icon: Share2 },
];

function Field({ label, htmlFor, children }: { label: string; htmlFor: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 space-y-1.5">
      <label htmlFor={htmlFor} className="text-xs font-medium text-muted-foreground">
        {label}
      </label>
      {children}
    </div>
  );
}

function ContextItem({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 space-y-1 rounded-lg border bg-background/50 p-3">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-sm font-medium">{children}</dd>
    </div>
  );
}

function quoteName(quote: SupplierQuote): string {
  return quote.data?.name ?? quote.supplier_id;
}

const GATE_KPI_TONE: Record<"ok" | "warn" | "bad", KpiTone> = { ok: "success", warn: "warning", bad: "danger" };

const REQUIREMENT_COLUMNS: DataTableColumn<RequirementRow>[] = [
  {
    key: "name",
    header: "Requisito",
    cell: (row) => <span className="font-medium">{row.name}</span>,
    sortValue: (row) => row.name,
  },
  { key: "market", header: "Mercado", cell: (row) => marketLabel(row.market) },
  {
    key: "status",
    header: "Estado",
    cell: (row) =>
      row.status === "declared" ? (
        <div className="space-y-1">
          <StatusChip status="NEEDS_REVIEW" />
          <p className="text-[11px] text-muted-foreground">Declarada por ti, sin evidencia</p>
        </div>
      ) : (
        <StatusChip status="PENDING" />
      ),
    sortValue: (row) => row.status,
  },
  {
    key: "evidence",
    header: "Evidencia",
    cell: () => <span className="text-xs text-muted-foreground">Sin evidencia adjunta</span>,
  },
  { key: "source", header: "Fuente", cell: () => <span className="text-xs">{SIMULATED_SOURCE}</span> },
];

export function LegalWorkspace({
  products,
  initialProductId,
  initialAnalyses,
  initialQuotes,
}: {
  products: Product[];
  initialProductId?: string;
  initialAnalyses: LegalAnalysis[];
  initialQuotes: SupplierQuote[];
}) {
  const router = useRouter();

  const [productId, setProductId] = useState(initialProductId ?? "");
  const [history, setHistory] = useState(initialAnalyses);
  const [quotes, setQuotes] = useState(initialQuotes);
  const [market, setMarket] = useState(initialAnalyses[0]?.market ?? "eu");
  const [certificationAvailable, setCertificationAvailable] = useState(
    initialAnalyses[0] ? certificationsDeclared(initialAnalyses[0]) : false,
  );
  const [changingProduct, setChangingProduct] = useState(false);
  const [loadingProduct, setLoadingProduct] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const latestProductRequest = useRef(initialProductId ?? "");

  const product = products.find((p) => p.id === productId);
  const analysis = latestForMarket(history, market);

  function selectMarket(next: string) {
    setMarket(next);
    const existing = latestForMarket(history, next);
    setCertificationAvailable(existing ? certificationsDeclared(existing) : false);
  }

  async function changeProduct(id: string) {
    latestProductRequest.current = id;
    setProductId(id);
    setChangingProduct(false);
    setError(null);
    setLoadingProduct(true);
    try {
      const [nextHistory, nextQuotes] = await Promise.all([api.listProductLegal(id), api.listProductSuppliers(id)]);
      if (latestProductRequest.current !== id) return;
      setHistory(nextHistory);
      setQuotes(nextQuotes);
      const nextMarket = nextHistory[0]?.market ?? market;
      setMarket(nextMarket);
      const existing = latestForMarket(nextHistory, nextMarket);
      setCertificationAvailable(existing ? certificationsDeclared(existing) : false);
    } catch (err) {
      if (latestProductRequest.current !== id) return;
      setHistory([]);
      setQuotes([]);
      setError(err instanceof ApiError ? err.detail : "No se pudo cargar el historial legal del producto.");
    } finally {
      if (latestProductRequest.current === id) setLoadingProduct(false);
    }
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!product) return;
    setError(null);
    setSubmitting(true);
    try {
      const result = await api.createLegalAnalysisRun({
        product_id: product.id,
        market,
        certification_available: certificationAvailable,
      });
      setHistory((current) => [result, ...current]);
      // el análisis nuevo puede haber usado una cotización más reciente
      setQuotes(await api.listProductSuppliers(product.id));
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "El análisis legal falló.");
    } finally {
      setSubmitting(false);
    }
  }

  if (products.length === 0 || !product) {
    return (
      <Card>
        <CardContent>
          <EmptyState
            icon={PackageSearch}
            title="Aún no hay productos que analizar"
            description="La revisión legal parte de un producto investigado."
            action={
              <Button size="sm" variant="outline" nativeButton={false} render={<Link href="/research" />}>
                Ir a Investigación
              </Button>
            }
          />
        </CardContent>
      </Card>
    );
  }

  // --- Resultados: todo sale del análisis devuelto por el backend ---
  const gate = analysis ? legalGate(analysis.recommendation) : undefined;
  const requirements = analysis ? requirementRows(analysis) : [];
  const reasons = analysis ? gateReasons(analysis) : [];
  const risks = analysis?.data?.risks ?? [];
  const changes = changesNewestFirst(analysis?.data?.recent_changes);
  const declared = analysis ? certificationsDeclared(analysis) : false;
  const analysisQuote = analysis?.supplier_quote_id ? quotes.find((q) => q.id === analysis.supplier_quote_id) : undefined;
  const terms = analysis?.data?.terms_and_conditions;

  function validateWithCeo() {
    if (!analysis) return;
    const requiresCertification = (analysis.data?.required_certifications?.length ?? 0) > 0;
    const params = new URLSearchParams({
      title: `Validar cumplimiento legal del producto ${analysis.product_id} en ${analysis.market}`,
      restricted_category: String(analysis.restricted ?? false),
      requires_certification: String(requiresCertification),
      certification_available: String(declared),
    });
    router.push(`/ceo?${params.toString()}`);
  }

  function generateStorefront() {
    if (!analysis) return;
    router.push(`/ecommerce?${new URLSearchParams({ product_id: analysis.product_id }).toString()}`);
  }

  return (
    <div className="space-y-6">
      <form onSubmit={handleSubmit} className="grid gap-4 xl:grid-cols-12">
        <Card className="xl:col-span-8">
          <CardHeader>
            <CardTitle>Producto y contexto</CardTitle>
            <CardAction>
              <Button type="button" variant="ghost" size="xs" onClick={() => setChangingProduct((v) => !v)}>
                Cambiar producto
              </Button>
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-4">
            {changingProduct ? (
              <Field label="Producto" htmlFor="legal-product">
                <select
                  id="legal-product"
                  value={productId}
                  onChange={(e) => void changeProduct(e.target.value)}
                  className={INPUT_CLASS}
                >
                  {products.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} · {p.category}
                    </option>
                  ))}
                </select>
              </Field>
            ) : null}

            <ProductHeader product={product} />

            <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <ContextItem label="Proveedor">
                {loadingProduct ? (
                  <span className="flex items-center gap-1.5 text-muted-foreground">
                    <Loader2 className="size-3.5 animate-spin" /> Cargando…
                  </span>
                ) : analysisQuote ? (
                  <>
                    <span className="block truncate">{quoteName(analysisQuote)}</span>
                    <span className="block text-xs font-normal text-muted-foreground">
                      {regionLabel(analysisQuote.data?.region)}
                    </span>
                  </>
                ) : (
                  <span className="text-xs font-normal text-muted-foreground">
                    {analysis
                      ? "El análisis se hizo sin proveedor cotizado"
                      : "Se usa la última cotización del producto, si existe"}
                  </span>
                )}
              </ContextItem>
              <ContextItem label="Mercado objetivo">{marketLabel(market)}</ContextItem>
              <ContextItem label="Modelo logístico">
                <DataProvenanceBadge status="pending" tooltip="El backend no guarda el modelo logístico del producto." />
              </ContextItem>
              <ContextItem label="Canal previsto">
                <DataProvenanceBadge status="pending" tooltip="El backend no guarda el canal de venta previsto." />
              </ContextItem>
            </dl>
          </CardContent>
        </Card>

        <Card className="xl:col-span-4">
          <CardHeader>
            <CardTitle>Parámetros del análisis</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <Field label="Mercado" htmlFor="legal-market">
              <select
                id="legal-market"
                value={market}
                onChange={(e) => selectMarket(e.target.value)}
                className={INPUT_CLASS}
              >
                {Object.entries(MARKET_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </Field>
            <label className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                checked={certificationAvailable}
                onChange={(e) => setCertificationAvailable(e.target.checked)}
                className="mt-0.5 size-4"
              />
              <span>
                Ya se cuenta con las certificaciones requeridas
                <span className="block text-xs text-muted-foreground">
                  Es una declaración tuya: AMAZONA aún no guarda los documentos que la respalden.
                </span>
              </span>
            </label>
            <Button type="submit" size="lg" className="w-full" disabled={submitting || loadingProduct}>
              {submitting ? <Loader2 className="animate-spin" /> : <Scale />}
              {submitting ? "Analizando…" : "Ejecutar análisis"}
            </Button>
          </CardContent>
        </Card>
      </form>

      {error ? (
        <Alert variant="destructive">
          <AlertTriangle className="size-4" />
          <AlertTitle>No se pudo completar la operación</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {!analysis || !gate ? (
        <Card>
          <CardContent>
            <EmptyState
              icon={Scale}
              title={`Sin análisis legal de este producto en ${marketLabel(market)}`}
              description="Elige el mercado y pulsa «Ejecutar análisis» para ver aquí los requisitos, riesgos y el estado del Legal Gate."
            />
          </CardContent>
        </Card>
      ) : (
        <>
          <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6" aria-label="Indicadores legales">
            <KpiCard
              label="Cumplimiento general"
              value="—"
              icon={Gauge}
              caption="El agente no puntúa el cumplimiento"
              provenance="pending"
              provenanceTooltip="El backend no calcula un porcentaje de cumplimiento; solo devuelve una recomendación."
            />
            <KpiCard
              label="Riesgo legal"
              value={`${risks.length} riesgo${risks.length === 1 ? "" : "s"}`}
              icon={ShieldAlert}
              caption="Sin nivel ni probabilidad × impacto"
              provenance="estimated"
              provenanceTooltip="Riesgos del dataset regulatorio simulado; el agente no los puntúa."
            />
            <KpiCard
              label="Certificaciones"
              value={`${requirements.length} requerida${requirements.length === 1 ? "" : "s"}`}
              icon={Award}
              caption={
                requirements.length === 0
                  ? "No se exige ninguna"
                  : declared
                    ? "Declaradas como disponibles"
                    : "Sin acreditar"
              }
              provenance="estimated"
              provenanceTooltip="Certificaciones exigidas según el dataset regulatorio simulado."
            />
            <KpiCard
              label="Evidencias documentales"
              value="—"
              icon={Layers}
              caption="AMAZONA aún no guarda documentos"
              provenance="pending"
              provenanceTooltip="No existe almacén de documentos ni evidencias en el backend."
            />
            <KpiCard
              label="Cambios regulatorios"
              value={changes.length}
              icon={Bell}
              caption={changes.length > 0 ? `Último: ${changes[0].date}` : "Sin cambios registrados"}
              provenance="estimated"
              provenanceTooltip="Cambios del dataset regulatorio simulado."
            />
            <KpiCard
              label="Legal Gate"
              value={gate.title}
              icon={Gavel}
              tone={GATE_KPI_TONE[gate.tone]}
              caption={`Recomendación del agente · confianza ${formatPercent(analysis.confidence, 0)}`}
              provenance="estimated"
              provenanceTooltip="Recomendación del agente legal sobre un dataset simulado. No es asesoría legal."
            />
          </section>

          <SectionNav
            label="Secciones del análisis legal"
            items={[
              { label: "Requisitos y certificaciones", href: "#requisitos", icon: ScrollText },
              { label: "Riesgos legales", href: "#riesgos", icon: ShieldAlert },
              { label: "Cambios normativos", href: "#cambios", icon: Bell },
              { label: "Resumen y decisión", href: "#decision", icon: Gavel },
              ...PENDING_NAV.map((item) => ({
                ...item,
                pendingReason: "Pendiente: el backend aún no lo proporciona",
              })),
            ]}
          />

          <section className="grid gap-4 xl:grid-cols-12">
            <Card id="requisitos" className="scroll-mt-4 xl:col-span-8">
              <CardHeader>
                <CardTitle>Matriz de requisitos legales</CardTitle>
                <CardAction>
                  <DataProvenanceBadge
                    status="estimated"
                    tooltip="Requisitos del dataset regulatorio simulado por categoría y mercado; no proceden de fuentes oficiales."
                  />
                </CardAction>
              </CardHeader>
              <CardContent className="space-y-4">
                <p className="text-xs text-muted-foreground">
                  Requisitos aplicables a este producto en {marketLabel(analysis.market)}.
                  {analysis.restricted === null
                    ? " El dataset no modela esta categoría en este mercado."
                    : analysis.restricted
                      ? " La categoría está restringida en este mercado."
                      : " La categoría no está restringida en este mercado."}
                </p>
                <DataTable
                  columns={REQUIREMENT_COLUMNS}
                  rows={requirements}
                  getRowId={(row) => row.id}
                  emptyMessage={
                    analysis.restricted === null
                      ? "Sin datos regulatorios para esta categoría y mercado."
                      : "No se exige ninguna certificación para esta categoría y mercado."
                  }
                />
              </CardContent>
            </Card>

            <Card id="decision" className="scroll-mt-4 xl:col-span-4">
              <CardHeader>
                <CardTitle>Legal Gate y decisión</CardTitle>
                <CardAction>
                  <DataProvenanceBadge
                    status="estimated"
                    tooltip="Recomendación del agente legal sobre un dataset simulado. No es asesoría legal."
                  />
                </CardAction>
              </CardHeader>
              <CardContent className="space-y-4">
                <VerdictBanner tone={gate.tone} title={gate.title} detail={gate.detail} />

                {reasons.length > 0 ? (
                  <div>
                    <p className="mb-1.5 text-xs font-medium text-muted-foreground">A resolver antes de continuar</p>
                    <ol className="list-inside list-decimal space-y-1 text-sm">
                      {reasons.map((reason) => (
                        <li key={reason}>{reason}</li>
                      ))}
                    </ol>
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground">Sin requisitos críticos pendientes en el análisis.</p>
                )}

                <dl className="space-y-1.5 border-t pt-3 text-xs">
                  <div className="flex justify-between gap-2">
                    <dt className="text-muted-foreground">Mercado</dt>
                    <dd className="font-medium">{marketLabel(analysis.market)}</dd>
                  </div>
                  <div className="flex justify-between gap-2">
                    <dt className="text-muted-foreground">Certificaciones requeridas</dt>
                    <dd className="font-medium">{requirements.length}</dd>
                  </div>
                  <div className="flex justify-between gap-2">
                    <dt className="text-muted-foreground">Riesgos identificados</dt>
                    <dd className="font-medium">{risks.length}</dd>
                  </div>
                  <div className="flex justify-between gap-2">
                    <dt className="text-muted-foreground">Cambios regulatorios</dt>
                    <dd className="font-medium">{changes.length}</dd>
                  </div>
                </dl>

                <Button type="button" variant="outline" className="w-full" onClick={validateWithCeo}>
                  <Brain />
                  Validar con el Director ejecutivo
                </Button>
              </CardContent>
            </Card>
          </section>

          <section className="grid gap-4 xl:grid-cols-12">
            <Card id="riesgos" className="scroll-mt-4 xl:col-span-6">
              <CardHeader>
                <CardTitle>Riesgos legales</CardTitle>
                <CardAction>
                  <DataProvenanceBadge
                    status="estimated"
                    tooltip="Riesgos conocidos del dataset simulado más los que el agente deduce del proveedor y de los cambios recientes."
                  />
                </CardAction>
              </CardHeader>
              <CardContent className="space-y-4">
                {risks.length > 0 ? (
                  <RiskList risks={risks} />
                ) : (
                  <p className="text-sm text-muted-foreground">
                    El análisis no registra riesgos para esta categoría y mercado.
                  </p>
                )}
                <div className="flex flex-wrap items-center gap-2 rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
                  <DataProvenanceBadge
                    status="pending"
                    tooltip="El agente no puntúa probabilidad ni impacto, así que no hay matriz de riesgos."
                  />
                  Matriz probabilidad × impacto: el agente no puntúa el riesgo. Los textos vienen del dataset simulado
                  (en inglés).
                </div>
              </CardContent>
            </Card>

            <Card id="cambios" className="scroll-mt-4 xl:col-span-6">
              <CardHeader>
                <CardTitle>Inteligencia regulatoria</CardTitle>
                <CardAction>
                  <DataProvenanceBadge
                    status="estimated"
                    tooltip="Cambios normativos del dataset regulatorio simulado, sin clasificar por criticidad."
                  />
                </CardAction>
              </CardHeader>
              <CardContent>
                {changes.length > 0 ? (
                  <ol className="space-y-3 border-l pl-4">
                    {changes.map((change) => (
                      <li key={`${change.date}-${change.description}`} className="relative">
                        <span className="absolute top-1.5 -left-[21px] size-2 rounded-full bg-primary" aria-hidden />
                        <p className="text-xs font-medium tabular-nums text-muted-foreground">{change.date}</p>
                        <p className="text-sm">{change.description}</p>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p className="text-sm text-muted-foreground">
                    Sin cambios normativos registrados para esta categoría y mercado.
                  </p>
                )}
                <p className="mt-3 text-[11px] text-muted-foreground">
                  Sin clasificación crítico / relevante / informativo: el dataset no la incluye.
                </p>
              </CardContent>
            </Card>
          </section>

          {terms ? (
            <Card>
              <CardHeader>
                <CardTitle>Borrador de términos y condiciones</CardTitle>
                <CardAction>
                  <DataProvenanceBadge
                    status="estimated"
                    tooltip="Plantilla generada por el agente. No es texto legal revisado."
                  />
                </CardAction>
              </CardHeader>
              <CardContent>
                <pre className="max-h-72 overflow-auto rounded-md border bg-muted/30 p-3 text-xs whitespace-pre-wrap">
                  {terms}
                </pre>
              </CardContent>
            </Card>
          ) : null}

          <PendingFeatures
            title="Pendiente de backend"
            tooltip="Requieren fuentes oficiales, un almacén de documentos y un modelo de responsabilidades que el backend aún no tiene."
            items={PENDING_SECTIONS}
            columns={4}
            note="Hoy el agente legal solo consulta un dataset regulatorio simulado (certificaciones, riesgos conocidos y cambios recientes por categoría y mercado). No hay integración con fuentes oficiales ni almacén de evidencias."
          />
        </>
      )}

      <NextStepBar
        steps={[
          { label: "Economía validada", icon: Calculator, state: "done" },
          {
            label: "Revisión legal",
            icon: Scale,
            state: analysis && gate?.tone === "ok" ? "done" : "current",
          },
          {
            label: "Tienda y canales",
            icon: Store,
            state: analysis && gate?.tone === "ok" ? "current" : "todo",
          },
          { label: "Marketing", icon: Megaphone, state: "todo" },
        ]}
        action={
          <Button
            type="button"
            disabled={!analysis || analysis.recommendation === "NO_GO"}
            title={analysis?.recommendation === "NO_GO" ? "El Legal Gate está bloqueado" : undefined}
            onClick={generateStorefront}
          >
            Generar tienda
            <ArrowRight />
          </Button>
        }
      />
    </div>
  );
}
