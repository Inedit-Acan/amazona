"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  ArrowRight,
  Ban,
  Bell,
  Building2,
  CircleCheck,
  Clock3,
  Download,
  Eye,
  Factory,
  FileCheck2,
  FileText,
  Gavel,
  History,
  Landmark,
  Layers,
  Loader2,
  PackageSearch,
  RefreshCw,
  ScrollText,
  ShieldAlert,
  ShoppingCart,
  Store,
  Truck,
  User,
  Users,
  XCircle,
} from "lucide-react";
import { ApiError, api, type LegalAnalysis, type Product, type SupplierQuote } from "@/lib/api";
import {
  DEMO_CONTEXT,
  DEMO_DOCUMENTS,
  DEMO_RESPONSIBILITIES,
  DEMO_ROLES,
  DEMO_SOURCES,
  type Criticality,
  type RequirementStatus,
  type RoleAnswer,
} from "@/lib/demo/legal";
import { demoQuotes, demoSupplierProfile } from "@/lib/demo/sourcing";
import { dedupeQuotesBySupplier } from "@/lib/economics";
import { formatPercent } from "@/lib/format";
import { certificationsDeclared } from "@/lib/legal";
import { buildLegalView, isRequirementOk, type RequirementRow, type RiskLevel } from "@/lib/legal-view";
import { rankSuppliers } from "@/lib/sourcing-view";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { Flag } from "@/components/flag";
import { HeaderClock } from "@/components/header-clock";
import { HeaderTile } from "@/components/header-tile";
import { InfoTile } from "@/components/info-tile";
import { KpiCard } from "@/components/kpi-card";
import { LevelChip, type LevelTone } from "@/components/level-chip";
import { PageHeader } from "@/components/page-header";
import { ProductSummary } from "@/components/product-summary";
import { RingGauge } from "@/components/ring-gauge";
import { RiskMatrix } from "@/components/risk-matrix";
import { SectionNav } from "@/components/section-nav";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { LEGAL_DESCRIPTION, LEGAL_TITLE } from "./copy";

const MARKETS = [
  { value: "eu", label: "España + UE", short: "UE", flags: ["es", "eu"] as const },
  { value: "us", label: "Estados Unidos", short: "EE. UU.", flags: [] as const },
  { value: "mx", label: "México", short: "MX", flags: ["mx"] as const },
];

const STATUS_TONE: Record<RequirementStatus, LevelTone> = {
  Verificado: "ok",
  Revisar: "warn",
  Incompleto: "warn",
  Pendiente: "bad",
  "No aplica": "neutral",
};
const CRITICALITY_TONE: Record<Criticality, LevelTone> = { Crítico: "bad", Alto: "warn", Medio: "warn", Bajo: "ok" };
const RISK_TEXT: Record<RiskLevel, string> = {
  Crítico: "text-destructive",
  Alto: "text-[#f8925c]",
  Medio: "text-warning",
  Bajo: "text-primary",
};
const ROLE_TEXT: Record<RoleAnswer, string> = { Sí: "text-primary", No: "text-destructive", Posible: "text-warning" };
const DOC_TONE = { Verificado: "text-primary", "Requiere revisión": "text-destructive", Pendiente: "text-destructive" } as const;

type Filter = "all" | "open" | Criticality;

function quoteName(quote: SupplierQuote): string {
  return quote.data?.name ?? quote.supplier_id;
}

function scrollTo(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

export function LegalWorkspace({
  products,
  productId,
  analyses,
  quotes,
  initialMarket,
}: {
  products: Product[];
  productId?: string;
  analyses: LegalAnalysis[];
  quotes: SupplierQuote[];
  initialMarket: string;
}) {
  const router = useRouter();
  const product = products.find((p) => p.id === productId);

  const [market, setMarket] = useState(MARKETS.some((m) => m.value === initialMarket) ? initialMarket : "eu");
  const [filter, setFilter] = useState<Filter>("all");
  const [allSources, setAllSources] = useState(false);
  const [allChanges, setAllChanges] = useState(false);
  const [allDocs, setAllDocs] = useState(false);
  const analysis = analyses.find((a) => a.market === market);
  const [certificationAvailable, setCertificationAvailable] = useState(analysis ? certificationsDeclared(analysis) : false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const view = useMemo(() => buildLegalView(market, analysis), [market, analysis]);

  if (products.length === 0 || !product) {
    return (
      <div>
        <PageHeader title={LEGAL_TITLE} description={LEGAL_DESCRIPTION} />
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
      </div>
    );
  }

  const marketInfo = MARKETS.find((m) => m.value === market) ?? MARKETS[0];
  // Proveedor: el del análisis; si no, el que recomienda Proveedores (real o de ejemplo).
  const supplierQuote =
    (analysis?.supplier_quote_id ? quotes.find((q) => q.id === analysis.supplier_quote_id) : undefined) ??
    rankSuppliers(quotes.length ? dedupeQuotesBySupplier(quotes) : demoQuotes(product.id))[0]?.quote;
  const supplierProfile = supplierQuote ? demoSupplierProfile(supplierQuote) : undefined;

  const counts: Record<Filter, number> = {
    all: view.requirements.length,
    open: view.requirements.filter((r) => !isRequirementOk(r.status)).length,
    Crítico: view.requirements.filter((r) => r.criticality === "Crítico").length,
    Alto: view.requirements.filter((r) => r.criticality === "Alto").length,
    Medio: view.requirements.filter((r) => r.criticality === "Medio").length,
    Bajo: view.requirements.filter((r) => r.criticality === "Bajo").length,
  };
  const shownRequirements = view.requirements.filter((r) =>
    filter === "all" ? true : filter === "open" ? !isRequirementOk(r.status) : r.criticality === filter,
  );
  const sources = (DEMO_SOURCES[market] ?? DEMO_SOURCES.eu).map((s) => ({
    ...s,
    status: s.status.replace("{n}", String(view.requirements.length)),
  }));
  const documents = DEMO_DOCUMENTS[market] ?? DEMO_DOCUMENTS.eu;
  const gate = {
    blocked: { title: "BLOQUEADO", banner: "NO APTO PARA LANZAMIENTO", tone: "danger" as const },
    review: { title: "REVISIÓN HUMANA", banner: "REQUIERE REVISIÓN HUMANA", tone: "warning" as const },
    ready: { title: "PREPARADO", banner: "PREPARADO PARA LANZAMIENTO", tone: "success" as const },
  }[view.gate.state];
  const importerPossible = supplierQuote?.data?.region !== market;

  function changeProduct(id: string) {
    router.push(`/legal?${new URLSearchParams({ product_id: id, market }).toString()}`);
  }

  async function runAnalysis() {
    setError(null);
    setRunning(true);
    try {
      await api.createLegalAnalysisRun({ product_id: product!.id, market, certification_available: certificationAvailable });
      router.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "El análisis legal falló.");
    } finally {
      setRunning(false);
    }
  }

  function sendToHumanReview() {
    const params = new URLSearchParams({
      title: `Validar cumplimiento legal de ${product!.name} en ${marketInfo.label}`,
      restricted_category: String(analysis?.restricted ?? false),
      requires_certification: String(view.certifications.pending + view.certifications.verified > 0),
      certification_available: String(view.certifications.pending === 0),
    });
    router.push(`/ceo?${params.toString()}`);
  }

  function showActions() {
    setFilter("open");
    scrollTo("requisitos");
  }

  const columns: DataTableColumn<RequirementRow>[] = [
    {
      key: "name",
      header: "Requisito",
      cell: (r) => (
        <span className="flex items-center gap-1.5 font-medium">
          {r.name}
          {r.fromAgent ? <span title="Exigida por el agente legal" className="size-1.5 rounded-full bg-cyan-accent" /> : null}
        </span>
      ),
      sortValue: (r) => r.name,
      exportValue: (r) => r.name,
    },
    { key: "market", header: "Mercado", cell: () => marketInfo.short, exportValue: () => marketInfo.short },
    {
      key: "status",
      header: "Estado",
      cell: (r) => <LevelChip tone={STATUS_TONE[r.status]}>{r.status}</LevelChip>,
      sortValue: (r) => r.status,
      exportValue: (r) => r.status,
    },
    {
      key: "evidence",
      header: "Evidencia",
      cell: (r) => (r.evidence > 0 ? `${r.evidence} documento${r.evidence === 1 ? "" : "s"}` : "—"),
      sortValue: (r) => r.evidence,
      exportValue: (r) => r.evidence,
    },
    { key: "source", header: "Fuente", cell: (r) => <span className="text-xs">{r.source}</span>, exportValue: (r) => r.source },
    {
      key: "criticality",
      header: "Criticidad",
      cell: (r) => <LevelChip tone={CRITICALITY_TONE[r.criticality]}>{r.criticality}</LevelChip>,
      sortValue: (r) => ["Crítico", "Alto", "Medio", "Bajo"].indexOf(r.criticality),
      exportValue: (r) => r.criticality,
    },
    {
      key: "actions",
      header: "Acciones",
      cell: (r) => (
        <span className="flex items-center gap-0.5">
          <Button size="icon-sm" variant="ghost" title="Ver documentos" aria-label={`Ver documentos de ${r.name}`} onClick={() => scrollTo("documentacion")}>
            <Eye />
          </Button>
          <Button size="icon-sm" variant="ghost" disabled title="Descarga pendiente: el backend aún no guarda documentos" aria-label={`Descargar evidencia de ${r.name}`}>
            <Download />
          </Button>
        </span>
      ),
    },
  ];

  return (
    <div className="space-y-5">
      <PageHeader
        title={LEGAL_TITLE}
        description={LEGAL_DESCRIPTION}
        actions={
          <>
            <DataProvenanceBadge
              status="demo"
              tooltip="Incluye datos de demostración, no asesoría legal: la matriz de requisitos con estados y evidencias, fuentes, roles, responsabilidades, riesgos con probabilidad × impacto, documentos y parte de los cambios. Del agente legal (dataset simulado del backend) salen las certificaciones exigidas, los riesgos conocidos, los cambios recientes y su recomendación."
            />
            <HeaderClock />
            <HeaderTile
              label="Producto activo"
              value={product.id}
              options={products.map((p) => ({ value: p.id, label: p.name }))}
              onChange={changeProduct}
            />
          </>
        }
      />

      {/* Producto y contexto */}
      <Card>
        <CardContent className="grid gap-3 lg:grid-cols-2 2xl:grid-cols-[minmax(0,1.9fr)_repeat(4,minmax(0,1fr))]">
          <div className="lg:col-span-2 2xl:col-span-1">
            <ProductSummary product={product} />
          </div>
          <InfoTile label="Proveedor">
            <p className="truncate text-sm font-medium">{supplierQuote ? quoteName(supplierQuote) : "—"}</p>
            {supplierProfile ? (
              <p className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
                <Flag code={supplierProfile.flag} /> {supplierProfile.country}
              </p>
            ) : null}
          </InfoTile>
          <InfoTile label="Mercados objetivo">
            <label className="flex items-center gap-2">
              <select
                value={market}
                onChange={(e) => {
                  setMarket(e.target.value);
                  setFilter("all");
                }}
                aria-label="Mercado objetivo"
                className="min-w-0 appearance-none truncate bg-transparent text-lg font-semibold text-primary outline-none"
              >
                {MARKETS.map((m) => (
                  <option key={m.value} value={m.value} className="bg-popover text-base text-foreground">
                    {m.label}
                  </option>
                ))}
              </select>
              {marketInfo.flags.map((f) => (
                <Flag key={f} code={f} />
              ))}
            </label>
          </InfoTile>
          <InfoTile label="Modelo logístico">
            <p className="flex items-center gap-2 text-sm font-medium">
              <Truck className="size-5 shrink-0 text-primary" />
              <span>
                {DEMO_CONTEXT.logisticsModel}
                <span className="block text-xs font-normal text-muted-foreground">{DEMO_CONTEXT.logisticsDetail}</span>
              </span>
            </p>
          </InfoTile>
          <InfoTile label="Canal previsto">
            <p className="flex items-center gap-2 text-sm font-medium">
              <ShoppingCart className="size-5 shrink-0 text-primary" /> {DEMO_CONTEXT.channel}
            </p>
          </InfoTile>
        </CardContent>
      </Card>

      {/* KPIs */}
      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-6" aria-label="Indicadores legales">
        <KpiCard
          label="Cumplimiento general"
          leading={<RingGauge value={view.compliance.ratio} />}
          value={`${view.compliance.ok}/${view.compliance.total}`}
          caption="requisitos cumplidos"
        />
        <KpiCard
          label="Riesgo legal"
          leading={<ShieldAlert className="size-9 shrink-0 text-warning" />}
          value={view.risk.level}
          tone={view.risk.level === "Alto" ? "danger" : "default"}
          accent={view.risk.level === "Bajo"}
          caption={`${view.risk.critical} crítico${view.risk.critical === 1 ? "" : "s"} · ${view.risk.high} alto${view.risk.high === 1 ? "" : "s"}`}
        />
        <KpiCard
          label="Certificaciones"
          leading={<FileCheck2 className="size-9 shrink-0 text-primary" />}
          value={`${view.certifications.verified} verificada${view.certifications.verified === 1 ? "" : "s"}`}
          caption={`${view.certifications.pending} pendiente${view.certifications.pending === 1 ? "" : "s"}`}
        />
        <KpiCard
          label="Evidencias documentales"
          leading={<Layers className="size-9 shrink-0 text-primary" />}
          value={`${view.documents.verified} / ${view.documents.required}`}
          caption={`${view.documents.pending} pendiente${view.documents.pending === 1 ? "" : "s"}`}
        />
        <KpiCard
          label="Cambios regulatorios"
          leading={<Bell className="size-9 shrink-0 text-primary" />}
          value={`${view.relevantChanges} relevante${view.relevantChanges === 1 ? "" : "s"}`}
          caption="últimos 30 días"
        />
        <KpiCard
          label="Legal Gate"
          leading={
            view.gate.state === "blocked" ? (
              <Ban className="size-9 shrink-0 text-destructive" />
            ) : view.gate.state === "review" ? (
              <AlertTriangle className="size-9 shrink-0 text-warning" />
            ) : (
              <CircleCheck className="size-9 shrink-0 text-primary" />
            )
          }
          value={gate.title}
          tone={gate.tone}
          caption={
            view.gate.criticalOpen > 0
              ? `${view.gate.criticalOpen} requisito${view.gate.criticalOpen === 1 ? "" : "s"} crítico${view.gate.criticalOpen === 1 ? "" : "s"}`
              : `${counts.open} requisito${counts.open === 1 ? "" : "s"} abierto${counts.open === 1 ? "" : "s"}`
          }
        />
      </section>

      <SectionNav
        label="Secciones del análisis legal"
        items={[
          { label: "Requisitos y certificaciones", href: "#requisitos", icon: ScrollText },
          { label: "Riesgos legales", href: "#riesgos", icon: ShieldAlert },
          { label: "Documentación", href: "#documentacion", icon: FileText },
          { label: "Fuentes regulatorias", href: "#fuentes", icon: Landmark },
          { label: "Responsabilidades", href: "#responsabilidades", icon: Users },
          { label: "Cambios normativos", href: "#cambios", icon: History },
          { label: "Resumen y decisión", href: "#decision", icon: Clock3 },
        ]}
      />

      {error ? (
        <Alert variant="destructive">
          <AlertTriangle className="size-4" />
          <AlertTitle>El análisis legal falló</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {/* Requisitos · Fuentes · Rol */}
      <section className="grid gap-4 xl:grid-cols-2 min-[106.25rem]:grid-cols-[minmax(0,1.65fr)_minmax(0,1fr)_minmax(0,0.95fr)]">
        <Card id="requisitos" className="scroll-mt-4 xl:col-span-2 min-[106.25rem]:col-span-1">
          <CardHeader>
            <CardTitle>Matriz de requisitos legales</CardTitle>
            <CardDescription>Requisitos aplicables según el producto y el mercado seleccionado.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-wrap gap-1.5">
              {(
                [
                  ["all", "Todos"],
                  ["open", "Abiertos"],
                  ["Crítico", "Críticos"],
                  ["Alto", "Altos"],
                  ["Medio", "Medios"],
                  ["Bajo", "Bajos"],
                ] as [Filter, string][]
              ).map(([key, label]) => (
                <Button
                  key={key}
                  size="xs"
                  variant={filter === key ? "default" : "outline"}
                  aria-pressed={filter === key}
                  onClick={() => setFilter(key)}
                >
                  {label} ({counts[key]})
                </Button>
              ))}
            </div>
            <div className="overflow-x-auto">
              <DataTable
                columns={columns}
                rows={shownRequirements}
                getRowId={(r) => r.id}
                exportFileName={`requisitos-legales-${market}`}
                emptyMessage="Ningún requisito en este filtro."
              />
            </div>
          </CardContent>
        </Card>

        <Card id="fuentes" className="scroll-mt-4">
          <CardHeader>
            <CardTitle>Fuentes regulatorias</CardTitle>
            <CardDescription>Consulta automática de fuentes oficiales.</CardDescription>
            <CardAction>
              <Button size="xs" variant="outline" onClick={() => setAllSources((v) => !v)}>
                {allSources ? "Ver menos" : "Ver todas"}
              </Button>
            </CardAction>
          </CardHeader>
          <CardContent>
            <ul className="divide-y">
              {(allSources ? sources : sources.slice(0, 4)).map((s) => (
                <li key={s.name} className="flex items-start gap-3 py-2.5 text-sm">
                  {s.flag ? (
                    <Flag code={s.flag} className="mt-0.5 h-5 w-7 shrink-0 rounded-[3px]" />
                  ) : (
                    <Building2 className="mt-0.5 size-5 shrink-0 text-muted-foreground" />
                  )}
                  <span className="min-w-0 flex-1 font-medium">{s.name}</span>
                  <span className="shrink-0 text-right text-xs">
                    <span className="flex items-center justify-end gap-1.5">
                      <span className={cn("size-2 rounded-full", s.ok ? "bg-primary" : "bg-warning")} />
                      <span className={s.ok ? "text-primary" : "text-warning"}>{s.status}</span>
                    </span>
                    <span className="text-[11px] text-muted-foreground">Última consulta: {s.lastCheck}</span>
                  </span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Rol en la operación</CardTitle>
            <CardDescription>Según el modelo de negocio y la cadena de suministro.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <ul className="space-y-2 text-sm">
              {DEMO_ROLES.map(({ role, answer }) => {
                const value = role === "Importador" && !importerPossible ? "No" : answer;
                return (
                  <li key={role} className="flex items-center justify-between gap-2">
                    <span className="flex items-center gap-2 text-muted-foreground">
                      <User className="size-4" /> {role}
                    </span>
                    <span className={cn("font-semibold", ROLE_TEXT[value])}>{value}</span>
                  </li>
                );
              })}
            </ul>
            {importerPossible ? (
              <div className="flex gap-2.5 rounded-lg border border-warning/40 bg-warning/10 p-3 text-xs">
                <AlertTriangle className="size-4 shrink-0 text-warning" />
                <p>
                  AMAZONA podría asumir obligaciones adicionales por introducir el producto en el mercado de{" "}
                  {marketInfo.value === "eu" ? "la UE" : marketInfo.label}.
                </p>
              </div>
            ) : null}
            <Button variant="outline" className="w-full text-primary" onClick={() => scrollTo("responsabilidades")}>
              Ver análisis de responsabilidades <ArrowRight />
            </Button>
          </CardContent>
        </Card>
      </section>

      {/* Responsabilidades · Riesgos · Inteligencia regulatoria */}
      <section className="grid gap-4 xl:grid-cols-2 2xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1.15fr)_minmax(0,0.95fr)]">
        <Card id="responsabilidades" className="scroll-mt-4 xl:col-span-2 2xl:col-span-1">
          <CardHeader>
            <CardTitle>Mapa de responsabilidades</CardTitle>
            <CardDescription>Cadena de suministro y obligaciones principales.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid items-center gap-2 md:grid-cols-[minmax(0,1fr)_auto_minmax(0,1.1fr)_auto_minmax(0,1fr)]">
              {[
                { icon: Factory, title: "Proveedor", subtitle: supplierProfile?.country ?? "—", items: DEMO_RESPONSIBILITIES.supplier, highlight: false },
                { icon: Store, title: "AMAZONA", subtitle: "Vendedor", items: DEMO_RESPONSIBILITIES.amazona, highlight: true },
                { icon: User, title: "Cliente", subtitle: marketInfo.short, items: DEMO_RESPONSIBILITIES.customer, highlight: false },
              ].map((box, k) => (
                <div key={box.title} className="contents">
                  {k > 0 ? <ArrowRight className="mx-auto hidden size-5 text-primary md:block" /> : null}
                  <div className={cn("flex min-w-0 gap-3 rounded-lg border p-3", box.highlight ? "border-primary/50 bg-primary/10" : "bg-background/40")}>
                    <box.icon className={cn("size-8 shrink-0", box.highlight ? "text-primary" : "text-muted-foreground")} />
                    <div className="min-w-0">
                      <p className="text-sm font-semibold">{box.title}</p>
                      <p className="text-xs text-muted-foreground">({box.subtitle})</p>
                      <ul className="mt-1.5 space-y-0.5 text-[11px] text-muted-foreground">
                        {box.items.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card id="riesgos" className="scroll-mt-4">
          <CardHeader>
            <CardTitle>Riesgos legales</CardTitle>
            <CardDescription>Evaluación de probabilidad e impacto.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
            <RiskMatrix risks={view.risks} />
            <div>
              <p className="mb-2 text-sm font-medium">Riesgos prioritarios</p>
              <ul className="space-y-2 text-xs">
                {view.risks.slice(0, 5).map((r) => (
                  <li key={r.name} className="flex items-start gap-2">
                    <span
                      className={cn(
                        "mt-1 size-2 shrink-0 rounded-full",
                        r.level === "Crítico" ? "bg-destructive" : r.level === "Alto" ? "bg-[#f8925c]" : r.level === "Medio" ? "bg-warning" : "bg-primary",
                      )}
                    />
                    <span className="min-w-0 flex-1">
                      {r.name}
                      {r.fromAgent ? <span className="ml-1 text-[10px] text-cyan-accent">· agente</span> : null}
                    </span>
                    <span className={cn("shrink-0 font-medium", RISK_TEXT[r.level])}>{r.level}</span>
                  </li>
                ))}
              </ul>
            </div>
          </CardContent>
        </Card>

        <Card id="cambios" className="scroll-mt-4">
          <CardHeader>
            <CardTitle>Inteligencia regulatoria</CardTitle>
            <CardDescription>Cambios recientes que pueden afectar.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <ol className="space-y-2.5 text-xs">
              {(allChanges ? view.changes : view.changes.slice(0, 3)).map((c) => (
                <li key={`${c.date}-${c.description}`} className="grid grid-cols-[5.5rem_auto_1fr] items-start gap-2">
                  <span className="font-medium tabular-nums">
                    {new Date(`${c.date}T12:00:00`).toLocaleDateString("es-ES", { day: "2-digit", month: "short", year: "numeric" }).toUpperCase()}
                  </span>
                  <span className={cn("mt-1 size-2 rounded-full", c.relevance === "informativo" ? "bg-primary" : c.relevance === "relevante" ? "bg-warning" : "bg-destructive")} />
                  <span className="text-muted-foreground">
                    {c.description}
                    {c.fromAgent ? <span className="ml-1 text-[10px] text-cyan-accent">· agente</span> : null}
                  </span>
                </li>
              ))}
            </ol>
            {view.changes.length > 3 || allChanges ? (
              <Button size="sm" variant="outline" className="w-full text-primary" onClick={() => setAllChanges((v) => !v)}>
                {allChanges ? "Ver menos" : `Ver todos los cambios (${view.changes.length})`} <ArrowRight />
              </Button>
            ) : null}
          </CardContent>
        </Card>
      </section>

      {/* Documentos · Evaluación · Decisión */}
      <section className="grid gap-4 xl:grid-cols-2 2xl:grid-cols-[minmax(0,1.65fr)_minmax(0,1fr)_minmax(0,1fr)]">
        <Card id="documentacion" className="scroll-mt-4 xl:col-span-2 2xl:col-span-1">
          <CardHeader>
            <CardTitle>Documentos del producto</CardTitle>
            <CardDescription>Gestión centralizada de evidencias y certificaciones.</CardDescription>
            <CardAction>
              <Button size="xs" variant="outline" className="text-primary" onClick={() => setAllDocs((v) => !v)}>
                {allDocs ? "Ver menos" : `Ver todos (${documents.length})`}
              </Button>
            </CardAction>
          </CardHeader>
          <CardContent>
            <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-5">
              {(allDocs ? documents : documents.slice(0, 5)).map((d) => (
                <li key={d.name} className="flex min-w-0 items-start gap-2 rounded-lg border bg-background/40 p-2.5">
                  <FileText className={cn("size-5 shrink-0", DOC_TONE[d.status])} />
                  <span className="min-w-0">
                    <span className="block truncate text-xs font-medium" title={d.name}>
                      {d.name}
                    </span>
                    <span className={cn("text-[11px]", DOC_TONE[d.status])}>
                      {d.status}
                      {d.date ? ` · ${d.date}` : ""}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Evaluación legal</CardTitle>
            <CardDescription>
              {analysis
                ? `Agente legal: ${analysis.recommendation === "GO" ? "favorable" : analysis.recommendation === "REVIEW" ? "a revisar" : "no viable"} · confianza ${formatPercent(analysis.confidence, 0)}`
                : `Sin análisis del agente en ${marketInfo.label}`}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <dl className="space-y-1.5 text-sm">
              {[
                ["Cumplimiento general", formatPercent(view.compliance.ratio, 0), "text-primary"],
                ["Riesgo residual", view.risk.level, view.risk.level === "Bajo" ? "text-primary" : view.risk.level === "Medio" ? "text-warning" : "text-destructive"],
                ["Requisitos críticos", String(view.gate.criticalOpen), view.gate.criticalOpen ? "text-destructive" : "text-primary"],
                ["Documentos pendientes", String(view.documents.pending), view.documents.pending ? "text-warning" : "text-primary"],
                ["Cambios regulatorios", String(view.relevantChanges), "text-foreground"],
              ].map(([label, value, tone]) => (
                <div key={label} className="flex justify-between gap-2">
                  <dt className="text-muted-foreground">{label}</dt>
                  <dd className={cn("font-semibold tabular-nums", tone)}>{value}</dd>
                </div>
              ))}
            </dl>
            <div className="space-y-2 border-t pt-3">
              <label className="flex items-center gap-2 text-xs text-muted-foreground">
                <input
                  type="checkbox"
                  checked={certificationAvailable}
                  onChange={(e) => setCertificationAvailable(e.target.checked)}
                  className="accent-primary"
                />
                Ya se cuenta con las certificaciones exigidas
              </label>
              <Button size="sm" variant="outline" className="w-full" onClick={() => void runAnalysis()} disabled={running}>
                {running ? <Loader2 className="animate-spin" /> : <RefreshCw />}
                {analysis ? "Reanalizar con el agente legal" : "Ejecutar análisis legal"}
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card
          id="decision"
          className={cn(
            "scroll-mt-4",
            view.gate.state === "blocked" && "bg-destructive/10 ring-destructive/40",
            view.gate.state === "review" && "bg-warning/10 ring-warning/40",
            view.gate.state === "ready" && "bg-primary/10 ring-primary/40",
          )}
        >
          <CardContent className="space-y-3">
            <p
              className={cn(
                "flex items-center gap-2 text-sm font-bold",
                view.gate.state === "blocked" ? "text-destructive" : view.gate.state === "review" ? "text-warning" : "text-primary",
              )}
            >
              {view.gate.state === "blocked" ? <XCircle className="size-5" /> : view.gate.state === "review" ? <AlertTriangle className="size-5" /> : <CircleCheck className="size-5" />}
              {gate.banner}
            </p>
            {view.actions.length > 0 ? (
              <div className="text-sm">
                <p className="font-medium">Resolver antes de continuar:</p>
                <ol className="mt-1 list-inside list-decimal space-y-0.5 text-muted-foreground">
                  {view.actions.map((a) => (
                    <li key={a}>{a}</li>
                  ))}
                </ol>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                Sin requisitos abiertos en este análisis. No es asesoría legal: valida con un profesional.
              </p>
            )}
            <div className="grid grid-cols-2 gap-2">
              <Button variant="outline" onClick={showActions} disabled={counts.open === 0}>
                <Gavel /> Ver acciones
              </Button>
              {view.gate.state === "ready" ? (
                <Button onClick={() => router.push(`/ecommerce?${new URLSearchParams({ product_id: product.id }).toString()}`)}>
                  Generar tienda <ArrowRight />
                </Button>
              ) : (
                <Button onClick={sendToHumanReview}>
                  Revisión humana <ArrowRight />
                </Button>
              )}
            </div>
          </CardContent>
        </Card>
      </section>

      <p className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <Gavel className="size-3.5" /> La información legal de esta pantalla es orientativa y no sustituye el asesoramiento de un profesional.
      </p>
    </div>
  );
}
