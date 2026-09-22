"use client";

import { useState } from "react";
import {
  BatteryFull,
  Droplets,
  Headphones,
  Lock,
  Monitor,
  Package,
  RotateCcw,
  Search,
  Settings,
  ShoppingCart,
  Smartphone,
  Sparkles,
  Star,
  Truck,
  Volume2,
  type LucideIcon,
} from "lucide-react";
import { DEMO_AB_TESTS, DEMO_PAGES, DEMO_REVIEWS, DEMO_TRUST_BADGES, THEMES } from "@/lib/demo/storefront";
import { formatEuro, formatInteger } from "@/lib/format";
import { LevelChip } from "@/components/level-chip";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

export interface StoreContent {
  title: string;
  subtitle: string;
  features: string[];
  cta: string;
}

export type BuilderTab = "preview" | "content" | "seo" | "design" | "pages" | "ab";

const FEATURE_ICONS: LucideIcon[] = [Volume2, Droplets, BatteryFull, Headphones];
const TRUST_ICONS: LucideIcon[] = [Truck, Lock, RotateCcw];
const INPUT = "w-full rounded-md border bg-background/60 px-3 py-2 text-sm outline-none focus-visible:border-ring";

function StorePreview({
  content,
  price,
  compareAt,
  slug,
  accent,
  device,
}: {
  content: StoreContent;
  price: number;
  compareAt: number;
  slug: string;
  accent: string;
  device: "desktop" | "mobile";
}) {
  const discount = Math.round((1 - price / compareAt) * 100);
  const mobile = device === "mobile";
  return (
    <div className={cn("mx-auto overflow-hidden rounded-xl bg-white text-zinc-900 shadow-lg", mobile ? "max-w-sm" : "w-full")}>
      <div className="flex items-center gap-4 border-b border-zinc-200 px-4 py-3">
        <span className="flex items-center gap-1.5 text-base font-bold tracking-tight">
          <span className="text-lg" style={{ color: accent }}>
            ▲
          </span>
          AMAZONA
        </span>
        {!mobile ? (
          <nav className="hidden gap-5 text-xs text-zinc-600 md:flex">
            {["Inicio", "Productos", "Ofertas", "Ayuda"].map((item) => (
              <span key={item}>{item}</span>
            ))}
          </nav>
        ) : null}
        <span className="ml-auto flex items-center gap-3 text-zinc-700">
          <Search className="size-4" />
          <ShoppingCart className="size-4" />
        </span>
      </div>
      <div className={cn("grid gap-4 p-4", mobile ? "grid-cols-1" : "grid-cols-1 md:grid-cols-[3rem_minmax(0,1fr)_minmax(0,1.15fr)]")}>
        {!mobile ? (
          <div className="hidden flex-col gap-2 md:flex">
            {[0, 1, 2, 3, 4].map((k) => (
              <span key={k} className={cn("flex aspect-square items-center justify-center rounded-md border bg-zinc-100", k === 0 && "border-zinc-900")}>
                <Package className="size-5 text-zinc-700" />
              </span>
            ))}
          </div>
        ) : null}
        <div className="relative flex aspect-square items-center justify-center rounded-lg bg-zinc-100">
          <span className="absolute top-2 left-2 rounded px-1.5 py-0.5 text-[10px] font-bold text-white" style={{ background: accent }}>
            MÁS VENDIDO
          </span>
          <Package className="size-1/2 text-zinc-800" strokeWidth={1.2} />
        </div>
        <div className="min-w-0 space-y-3">
          <div>
            <p className="text-xl leading-tight font-bold">{content.title}</p>
            <p className="mt-1 text-xs text-zinc-600">{content.subtitle}</p>
            <p className="mt-1.5 flex items-center gap-1 text-xs text-zinc-600">
              {[0, 1, 2, 3, 4].map((k) => (
                <Star key={k} className="size-3.5 fill-amber-400 text-amber-400" />
              ))}
              <span className="ml-1">
                {DEMO_REVIEWS.rating.toLocaleString("es-ES")} ({formatInteger(DEMO_REVIEWS.count)} reseñas)
              </span>
            </p>
          </div>
          <ul className="grid grid-cols-2 gap-2 text-[11px] text-zinc-700">
            {content.features.slice(0, 4).map((feature, k) => {
              const Icon = FEATURE_ICONS[k % FEATURE_ICONS.length];
              return (
                <li key={k} className="flex items-start gap-1.5">
                  <Icon className="size-4 shrink-0 text-zinc-800" />
                  <span className="min-w-0">{feature}</span>
                </li>
              );
            })}
          </ul>
          <p className="flex flex-wrap items-baseline gap-2">
            <span className="text-2xl font-bold">{formatEuro(price)}</span>
            <span className="text-sm text-zinc-500 line-through">{formatEuro(compareAt)}</span>
            {discount > 0 ? (
              <span className="rounded px-1.5 py-0.5 text-xs font-semibold" style={{ background: `${accent}33`, color: accent }}>
                -{discount}%
              </span>
            ) : null}
          </p>
          <button type="button" className="flex w-full items-center justify-center gap-2 rounded-md py-2.5 text-sm font-semibold text-zinc-900" style={{ background: accent }}>
            <ShoppingCart className="size-4" /> {content.cta}
          </button>
          <ul className="flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-zinc-600">
            {DEMO_TRUST_BADGES.map((badge, k) => {
              const Icon = TRUST_ICONS[k];
              return (
                <li key={badge} className="flex items-center gap-1">
                  <Icon className="size-3.5" /> {badge}
                </li>
              );
            })}
          </ul>
        </div>
      </div>
      <p className="border-t border-zinc-200 px-4 py-1.5 text-[10px] text-zinc-500">amazona.es/productos/{slug}</p>
    </div>
  );
}

export function StoreBuilder({
  tab,
  onTabChange,
  content,
  onContentChange,
  price,
  compareAt,
  slug,
  generating,
  onGenerate,
}: {
  tab: BuilderTab;
  onTabChange: (tab: BuilderTab) => void;
  content: StoreContent;
  onContentChange: (content: StoreContent) => void;
  price: number;
  compareAt: number;
  slug: string;
  generating: boolean;
  onGenerate: () => void;
}) {
  const [device, setDevice] = useState<"desktop" | "mobile">("desktop");
  const [theme, setTheme] = useState(THEMES[0].key);
  const accent = THEMES.find((t) => t.key === theme)?.color ?? THEMES[0].color;
  const metaTitle = `${content.title} | AMAZONA`;
  const metaDescription = `${content.subtitle} ${content.features.join(". ")}`.slice(0, 155);

  return (
    <Card id="constructor" className="scroll-mt-4">
      <CardHeader>
        <CardTitle>Constructor de página (Tienda propia)</CardTitle>
        <CardDescription>Genera y personaliza la página del producto con IA. Contenido basado en datos verificados.</CardDescription>
        <CardAction>
          <Button size="sm" variant="outline" className="border-primary/50 text-primary" onClick={onGenerate} disabled={generating}>
            <Sparkles /> {generating ? "Generando…" : "Generar con IA"}
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent>
        <Tabs value={tab} onValueChange={(value) => onTabChange(value as BuilderTab)}>
          <TabsList className="mb-3 flex h-auto w-full flex-wrap justify-start">
            {[
              ["preview", "Vista previa"],
              ["content", "Editar contenido"],
              ["seo", "SEO"],
              ["design", "Diseño"],
              ["pages", "Páginas"],
              ["ab", "A/B Testing"],
            ].map(([value, label]) => (
              <TabsTrigger key={value} value={value} className="flex-none px-3">
                {label}
              </TabsTrigger>
            ))}
          </TabsList>

          <TabsContent value="preview">
            <div className="overflow-hidden rounded-xl border bg-background/60">
              <div className="flex items-center gap-2 border-b px-3 py-2">
                <span className="flex gap-1.5" aria-hidden>
                  <span className="size-2.5 rounded-full bg-destructive" />
                  <span className="size-2.5 rounded-full bg-warning" />
                  <span className="size-2.5 rounded-full bg-primary" />
                </span>
                <span className="min-w-0 flex-1 truncate rounded-md border bg-background px-2.5 py-1 text-[11px] text-muted-foreground">
                  https://amazona.es/productos/{slug}
                </span>
                <Button size="xs" variant={device === "desktop" ? "secondary" : "ghost"} onClick={() => setDevice("desktop")} aria-pressed={device === "desktop"}>
                  <Monitor /> Desktop
                </Button>
                <Button size="xs" variant={device === "mobile" ? "secondary" : "ghost"} onClick={() => setDevice("mobile")} aria-pressed={device === "mobile"}>
                  <Smartphone /> Mobile
                </Button>
                <Button size="icon-xs" variant="ghost" aria-label="Diseño" onClick={() => onTabChange("design")}>
                  <Settings />
                </Button>
              </div>
              <div className="p-3">
                <StorePreview content={content} price={price} compareAt={compareAt} slug={slug} accent={accent} device={device} />
              </div>
            </div>
          </TabsContent>

          <TabsContent value="content" className="space-y-3">
            <label className="block space-y-1 text-xs text-muted-foreground">
              Título
              <input className={INPUT} value={content.title} onChange={(e) => onContentChange({ ...content, title: e.target.value })} />
            </label>
            <label className="block space-y-1 text-xs text-muted-foreground">
              Propuesta de valor
              <textarea
                rows={2}
                className={INPUT}
                value={content.subtitle}
                onChange={(e) => onContentChange({ ...content, subtitle: e.target.value })}
              />
            </label>
            <div className="grid gap-2 sm:grid-cols-2">
              {content.features.slice(0, 4).map((feature, k) => (
                <label key={k} className="block space-y-1 text-xs text-muted-foreground">
                  Característica {k + 1}
                  <input
                    className={INPUT}
                    value={feature}
                    onChange={(e) => {
                      const features = [...content.features];
                      features[k] = e.target.value;
                      onContentChange({ ...content, features });
                    }}
                  />
                </label>
              ))}
            </div>
            <label className="block space-y-1 text-xs text-muted-foreground">
              Botón de compra (CTA)
              <input className={INPUT} value={content.cta} onChange={(e) => onContentChange({ ...content, cta: e.target.value })} />
            </label>
            <p className="text-[11px] text-muted-foreground">Los cambios se ven al instante en la vista previa; «Generar con IA» crea un borrador nuevo.</p>
          </TabsContent>

          <TabsContent value="seo" className="space-y-3">
            <div className="rounded-lg border bg-background/40 p-3">
              <p className="text-xs text-muted-foreground">Así aparecería en Google</p>
              <p className="mt-1 text-[11px] text-primary">amazona.es › productos › {slug}</p>
              <p className="text-base text-sky-400">{metaTitle}</p>
              <p className="text-xs text-muted-foreground">{metaDescription}</p>
            </div>
            <dl className="grid gap-2 text-sm sm:grid-cols-2">
              <div className="rounded-lg border bg-background/40 p-3">
                <dt className="text-xs text-muted-foreground">Meta title</dt>
                <dd className={cn("font-medium", metaTitle.length > 60 && "text-warning")}>{metaTitle.length} / 60 caracteres</dd>
              </div>
              <div className="rounded-lg border bg-background/40 p-3">
                <dt className="text-xs text-muted-foreground">Meta description</dt>
                <dd className="font-medium">{metaDescription.length} / 155 caracteres</dd>
              </div>
            </dl>
          </TabsContent>

          <TabsContent value="design" className="space-y-3">
            <p className="text-sm text-muted-foreground">Color principal del escaparate</p>
            <div className="flex flex-wrap gap-2">
              {THEMES.map((t) => (
                <Button key={t.key} variant={theme === t.key ? "secondary" : "outline"} onClick={() => setTheme(t.key)} aria-pressed={theme === t.key}>
                  <span className="size-3.5 rounded-full" style={{ background: t.color }} /> {t.label}
                </Button>
              ))}
            </div>
            <Button variant="outline" onClick={() => onTabChange("preview")}>
              Ver en la vista previa
            </Button>
          </TabsContent>

          <TabsContent value="pages">
            <ul className="divide-y rounded-lg border">
              {DEMO_PAGES.map((page) => (
                <li key={page.name} className="flex items-center justify-between gap-2 px-3 py-2 text-sm">
                  {page.name}
                  <LevelChip tone={page.status === "Publicada" ? "ok" : "warn"}>{page.status}</LevelChip>
                </li>
              ))}
            </ul>
          </TabsContent>

          <TabsContent value="ab">
            <ul className="space-y-2">
              {DEMO_AB_TESTS.map((t) => (
                <li key={t.name} className="rounded-lg border bg-background/40 p-3 text-sm">
                  <p className="flex items-center justify-between gap-2 font-medium">
                    {t.name}
                    <LevelChip tone={t.status === "En curso" ? "warn" : "neutral"}>{t.status}</LevelChip>
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Conversión A: {t.variantA} · B: {t.variantB}
                  </p>
                </li>
              ))}
            </ul>
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}
