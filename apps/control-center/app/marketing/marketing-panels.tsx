"use client";

import { useState } from "react";
import {
  Bookmark,
  CircleCheck,
  FlaskConical,
  Heart,
  MessageCircle,
  MoreHorizontal,
  Play,
  Rocket,
  Search,
  Send,
  ShoppingBag,
  SlidersHorizontal,
  Sparkles,
  TrendingDown,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { ATTRIBUTION_MODELS, DEMO_PERIOD, type AttributionModel, type BucketKey } from "@/lib/demo/marketing";
import { formatEuro, formatInteger, formatPercent } from "@/lib/format";
import {
  attribution,
  funnelFor,
  metricSeries,
  type BucketPerformance,
  type CreativeRow,
  type CreativeStatus,
  type Recommendation,
  type SeriesMetric,
} from "@/lib/marketing-view";
import { DonutChart } from "@/components/donut-chart";
import { LevelChip, type LevelTone } from "@/components/level-chip";
import { LineChart } from "@/components/line-chart";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

const STATUS_CHIP: Record<CreativeStatus, { tone: LevelTone; icon: LucideIcon }> = {
  Aprobado: { tone: "ok", icon: CircleCheck },
  "En revisión": { tone: "warn", icon: FlaskConical },
  Ajustar: { tone: "bad", icon: Wrench },
};

function scoreColor(score: number): string {
  return score >= 85 ? "text-primary" : score >= 80 ? "text-warning" : "text-destructive";
}

function creativeBackground(hue: number): string {
  return `radial-gradient(circle at 70% 25%, hsl(${hue} 45% 42% / 0.9), transparent 55%), linear-gradient(165deg, hsl(${hue} 30% 24%), hsl(${hue} 35% 8%))`;
}

function SegmentTabs<T extends string>({
  value,
  onChange,
  items,
  label,
}: {
  value: T;
  onChange: (value: T) => void;
  items: readonly { key: T; label: string }[];
  label: string;
}) {
  return (
    <Tabs value={value} onValueChange={(v) => onChange(v as T)}>
      <TabsList aria-label={label} className="flex w-full justify-start group-data-horizontal/tabs:h-auto">
        {items.map((item) => (
          <TabsTrigger key={item.key} value={item.key} className="min-w-0 flex-1 basis-0 px-2 text-xs">
            {item.label}
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  );
}

// --- Creatividades ---------------------------------------------------------------

export function CreativesCard({
  creatives,
  selected,
  onSelect,
}: {
  creatives: CreativeRow[];
  selected: number;
  onSelect: (index: number) => void;
}) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Creatividades generadas por IA</CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {creatives.map((c, k) => {
          const chip = STATUS_CHIP[c.status];
          return (
            <div key={c.name} className="min-w-0 space-y-1.5">
              <button
                type="button"
                onClick={() => onSelect(k)}
                aria-pressed={selected === k}
                aria-label={`Ver ${c.name} en la vista previa`}
                className={cn(
                  "relative flex aspect-[4/5] w-full flex-col justify-end overflow-hidden rounded-xl border p-2.5 text-left transition",
                  selected === k ? "border-primary ring-2 ring-primary/50" : "hover:border-primary/50",
                )}
                style={{ background: creativeBackground(c.hue) }}
              >
                <Play className="absolute top-1/2 left-1/2 size-9 -translate-x-1/2 -translate-y-1/2 rounded-full bg-black/35 p-2 text-white/85" />
                <span className="text-[13px] leading-[1.15] font-bold text-white drop-shadow 2xl:text-[15px]">{c.headline}</span>
                <span className="absolute top-2 right-2 rounded bg-black/60 px-1 text-[10px] font-medium text-white tabular-nums">
                  0:{String(c.seconds).padStart(2, "0")}
                </span>
              </button>
              <p className="text-xs">{c.name}</p>
              <p className="text-xs text-muted-foreground">
                Creative Score <span className={cn("font-semibold", scoreColor(c.score))}>{c.score}</span>
              </p>
              <LevelChip tone={chip.tone} className="gap-1">
                <chip.icon className="size-3" /> {c.status}
              </LevelChip>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

// --- Vista previa ------------------------------------------------------------------

type PreviewTab = "meta" | "instagram" | "tiktok" | "google";

const PREVIEW_TABS: { key: PreviewTab; label: string }[] = [
  { key: "meta", label: "Meta" },
  { key: "instagram", label: "Instagram" },
  { key: "tiktok", label: "TikTok" },
  { key: "google", label: "Google" },
];

export function PreviewCard({
  creative,
  productName,
  text,
  social,
}: {
  creative: CreativeRow;
  productName: string;
  text: string;
  social: { likes: number; comments: number; shares: number };
}) {
  const [tab, setTab] = useState<PreviewTab>("meta");
  const image = (className: string) => (
    <div className={cn("relative flex flex-col justify-end p-3", className)} style={{ background: creativeBackground(creative.hue) }}>
      <p className="text-xl leading-[1.05] font-bold text-white drop-shadow">{creative.headline}</p>
      <p className="mt-1 text-[10px] text-white/80">{productName}</p>
    </div>
  );
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Vista previa en plataformas</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <SegmentTabs value={tab} onChange={setTab} items={PREVIEW_TABS} label="Plataforma de la vista previa" />
        <div
          data-testid="ad-preview"
          data-platform={tab}
          className="mx-auto w-full max-w-60 overflow-hidden rounded-[1.75rem] border-4 border-zinc-700 bg-white text-zinc-900 shadow-lg"
        >
          {tab === "google" ? (
            <div className="space-y-3 p-3 text-left">
              <div className="flex items-center gap-2 rounded-full border px-3 py-1.5 text-[11px] text-zinc-500">
                <Search className="size-3.5" /> {productName.toLowerCase()}
              </div>
              <div className="space-y-1">
                <p className="text-[10px] font-semibold">Patrocinado</p>
                <p className="text-[10px] text-zinc-500">amazona.es › productos</p>
                <p className="text-sm leading-snug font-medium text-blue-700">
                  {creative.headline} | {productName}
                </p>
                <p className="text-[11px] leading-snug text-zinc-600">{text}</p>
              </div>
              <div className="flex gap-2 text-[10px] text-blue-700">
                <span>Envío gratis</span>·<span>Devolución 30 días</span>
              </div>
            </div>
          ) : tab === "tiktok" ? (
            <div className="relative aspect-[9/15] text-white" style={{ background: creativeBackground(creative.hue) }}>
              <div className="absolute inset-x-3 bottom-3 space-y-1.5">
                <p className="text-xs font-semibold">@amazona · Patrocinado</p>
                <p className="text-lg leading-tight font-bold drop-shadow">{creative.headline}</p>
                <p className="line-clamp-2 text-[10px] text-white/85">{text}</p>
                <span className="block rounded bg-[#fe2c55] py-1 text-center text-[11px] font-semibold">{creative.cta}</span>
              </div>
              <div className="absolute top-1/3 right-2 flex flex-col items-center gap-3 text-[9px]">
                <Heart className="size-5" /> {formatInteger(social.likes)}
                <MessageCircle className="size-5" /> {social.comments}
                <Send className="size-5" /> {social.shares}
              </div>
            </div>
          ) : (
            <div>
              <div className="flex items-center gap-2 px-3 py-2">
                <span className="flex size-6 items-center justify-center rounded-full bg-zinc-900 text-[10px] font-bold text-white">A</span>
                <span className="min-w-0 flex-1 leading-tight">
                  <span className="block text-[11px] font-semibold">{tab === "instagram" ? "amazona" : "Amazona"}</span>
                  <span className="block text-[9px] text-zinc-500">{tab === "instagram" ? "Patrocinado" : "Publicidad"}</span>
                </span>
                <MoreHorizontal className="size-4 text-zinc-500" />
              </div>
              {tab === "meta" ? <p className="line-clamp-2 px-3 pb-2 text-[10px] leading-snug">{text}</p> : null}
              {image(tab === "instagram" ? "aspect-square" : "aspect-[4/3.4]")}
              <div className="flex items-center justify-between gap-2 bg-zinc-100 px-3 py-1.5">
                <span className="min-w-0 truncate text-[10px] font-medium">{tab === "instagram" ? creative.cta : productName}</span>
                <span className="shrink-0 rounded bg-blue-600 px-2 py-0.5 text-[10px] font-semibold text-white">{creative.cta}</span>
              </div>
              <div className="flex items-center gap-3 px-3 py-2 text-[10px] text-zinc-600">
                <span className="flex items-center gap-1">
                  <Heart className="size-3.5" /> {formatInteger(social.likes)}
                </span>
                <span className="flex items-center gap-1">
                  <MessageCircle className="size-3.5" /> {social.comments}
                </span>
                <span className="flex items-center gap-1">
                  <Send className="size-3.5" /> {social.shares}
                </span>
                {tab === "instagram" ? <Bookmark className="ml-auto size-3.5" /> : null}
              </div>
              {tab === "instagram" ? <p className="line-clamp-2 px-3 pb-3 text-[10px] leading-snug">{text}</p> : null}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

// --- Funnel ------------------------------------------------------------------------

const FUNNEL_FILTERS: { value: BucketKey | "all"; label: string }[] = [
  { value: "all", label: "Todos los canales" },
  { value: "meta", label: "Meta" },
  { value: "google", label: "Google" },
  { value: "tiktok", label: "TikTok" },
  { value: "other", label: "Otros" },
];

/** Anchura en escala logarítmica: con las impresiones tan por encima del resto,
 * una escala lineal dejaría todos los pasos siguientes en una raya. */
function logWidth(value: number, max: number, min: number): number {
  const floor = Math.max(1, min / 4);
  if (value <= 0 || max <= floor) return 0;
  return Math.max(4, ((Math.log(value) - Math.log(floor)) / (Math.log(max) - Math.log(floor))) * 100);
}

export function FunnelCard({ performance }: { performance: BucketPerformance[] }) {
  const [filter, setFilter] = useState<BucketKey | "all">("all");
  const steps = funnelFor(performance, filter);
  const max = steps[0]?.value ?? 0;
  const min = Math.min(...steps.map((s) => s.value).filter((v) => v > 0));
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Funnel de conversión</CardTitle>
        <CardAction>
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value as BucketKey | "all")}
            aria-label="Canal del funnel"
            className="rounded-md border bg-background px-2 py-1 text-xs"
          >
            {FUNNEL_FILTERS.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
        </CardAction>
      </CardHeader>
      <CardContent>
        <ul className="space-y-3.5 text-sm">
          {steps.map((s, k) => (
            <li key={s.label} className="grid grid-cols-[6.5rem_minmax(0,1fr)_4.5rem_4.5rem] items-center gap-2">
              <span className="text-muted-foreground">{s.label}</span>
              <span className="h-3.5 rounded-sm bg-muted/60">
                <span className="block h-full rounded-sm bg-cyan-400/85" style={{ width: `${logWidth(s.value, max, min)}%` }} />
              </span>
              <span className="text-right font-medium tabular-nums">{formatInteger(s.value)}</span>
              <span className="text-right text-xs text-muted-foreground tabular-nums">
                {s.rate === null ? "" : k === 1 ? `CTR ${formatPercent(s.rate)}` : formatPercent(s.rate)}
              </span>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-[11px] text-muted-foreground">
          {DEMO_PERIOD.label}. Cada % es sobre el paso anterior; barras en escala logarítmica.
        </p>
      </CardContent>
    </Card>
  );
}

// --- Rendimiento por canal ---------------------------------------------------------

const METRICS: { key: SeriesMetric; label: string }[] = [
  { key: "spend", label: "Inversión" },
  { key: "revenue", label: "Ingresos" },
  { key: "roas", label: "ROAS" },
  { key: "cac", label: "CAC" },
];

function formatMetric(metric: SeriesMetric, value: number): string {
  if (metric === "roas") return `${value.toLocaleString("es-ES", { maximumFractionDigits: 1 })} x`;
  return formatEuro(value, metric === "cac" ? 2 : 0);
}

export function PerformanceCard({ performance }: { performance: BucketPerformance[] }) {
  const [metric, setMetric] = useState<SeriesMetric>("spend");
  const month = DEMO_PERIOD.month;
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Rendimiento por canal</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <SegmentTabs value={metric} onChange={setMetric} items={METRICS} label="Métrica del gráfico" />
        <LineChart
          ariaLabel={`${METRICS.find((m) => m.key === metric)!.label} diaria por canal`}
          series={performance.map((b) => ({ key: b.key, label: b.label, color: b.color, points: metricSeries(b, metric) }))}
          formatY={(v) => formatMetric(metric, v)}
          formatX={(x) => `${x} ${month}`}
          xTicks={[1, 8, 15, 22, 30]}
          hoverTitle={(x) => `${x} ${month} 2026`}
          defaultHoverX={16}
          dots={false}
          height={250}
        />
      </CardContent>
    </Card>
  );
}

// --- Atribución --------------------------------------------------------------------

export function AttributionCard({ performance, total }: { performance: BucketPerformance[]; total: number }) {
  const [model, setModel] = useState<AttributionModel>("last_click");
  const slices = attribution(performance, model, total);
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Atribución de ingresos</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <SegmentTabs value={model} onChange={setModel} items={ATTRIBUTION_MODELS} label="Modelo de atribución" />
        <div className="flex flex-wrap items-center justify-center gap-4">
          <DonutChart
            ariaLabel="Ingresos atribuidos por canal"
            segments={slices.map((s) => ({ key: s.key, value: s.share, color: s.color }))}
            centerLabel={formatEuro(total, 0)}
            centerCaption="Ingresos atribuidos"
          />
          <ul className="min-w-44 flex-1 space-y-2.5 text-sm">
            {slices.map((s) => (
              <li key={s.key} className="grid grid-cols-[minmax(0,1fr)_3rem_4.5rem] items-center gap-2">
                <span className="flex min-w-0 items-center gap-2">
                  <span className="size-2.5 shrink-0 rounded-sm" style={{ background: s.color }} aria-hidden />
                  {s.label}
                </span>
                <span className="text-right text-muted-foreground tabular-nums">{formatPercent(s.share, 0)}</span>
                <span className="text-right font-medium tabular-nums">{formatEuro(s.revenue, 0)}</span>
              </li>
            ))}
          </ul>
        </div>
      </CardContent>
    </Card>
  );
}

// --- Recomendaciones ---------------------------------------------------------------

const RECOMMENDATION_ICON: Record<Recommendation["kind"], LucideIcon> = {
  agent: Sparkles,
  scale: Rocket,
  reduce: TrendingDown,
  abtest: SlidersHorizontal,
  shopping: ShoppingBag,
  segment: Search,
};

export function RecommendationsCard({ items }: { items: Recommendation[] }) {
  const [showAll, setShowAll] = useState(false);
  const visible = showAll ? items : items.slice(0, 4);
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          Recomendaciones de la IA
          <span className="flex size-5 items-center justify-center rounded-full bg-primary/15 text-[11px] text-primary">{items.length}</span>
        </CardTitle>
        {items.length > 4 ? (
          <CardAction>
            <Button size="xs" variant="outline" className="text-primary" onClick={() => setShowAll((v) => !v)}>
              {showAll ? "Ver menos" : "Ver todas"}
            </Button>
          </CardAction>
        ) : null}
      </CardHeader>
      <CardContent>
        <ul className="divide-y">
          {visible.map((r) => {
            const Icon = RECOMMENDATION_ICON[r.kind];
            return (
              <li key={`${r.kind}-${r.title}`} className="flex gap-3 py-2.5 first:pt-0">
                <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-primary/30 bg-primary/10 text-primary">
                  <Icon className="size-4" />
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-medium">{r.title}</span>
                  <span className="block text-xs text-muted-foreground">{r.detail}</span>
                </span>
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}
