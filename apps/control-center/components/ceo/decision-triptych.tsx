import { Suspense } from "react";
import { BlockFooter, BlockRows } from "@/components/ceo/block-rows";
import { BlockCard } from "@/components/ceo/block-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api-server";
import { blockStateOf, type BlockView } from "@/lib/ceo-block-view";
import { readBlocksNow, type BlocksView } from "@/lib/ceo-block-reads";
import { DECISIONS_BLOCK } from "@/lib/ceo-decisions";
import { CANDIDATES_BLOCK } from "@/lib/ceo-opportunities";
import { INCIDENTS_BLOCK } from "@/lib/ceo-risks";

/** Decisiones pendientes / Candidatos detectados / Incidencias activas (M47, Commit 3B). Cada bloque lee su fuente REAL (aprobaciones y
 * revisiones; el catálogo de productos; incidencias y kill switch) y dice su estado de lectura: cargado, vacío, error o sin leer. Ni
 * demostración ni ejemplos del mockup. Lo que cada bloque significa lo decide su módulo (`lib/ceo-decisions`, `ceo-opportunities`,
 * `ceo-risks`); aquí solo se pinta. Ninguno depende del periodo: el selector 7 / 14 / 30 días gobierna solo Ingresos.
 *
 * La lectura se hace UNA vez, en el servidor, y el mismo resultado alimenta la rejilla y las pestañas (si cada una leyera por su cuenta
 * serían diez peticiones en vez de cinco). Desde `xl` (1280 px) son tres tarjetas, como el mockup; por debajo, pestañas: a menos ancho
 * tres columnas no se leen. Las dos presentaciones se resuelven por CSS (sin medir el ancho en JavaScript), así que no hay parpadeo al
 * hidratar. */
interface Entry {
  key: string;
  title: string;
  /** El nombre corto de la pestaña (en 496 px no caben los tres nombres completos). */
  tab: string;
  seeAll: { href: string; label: string };
  view: BlockView;
}

function entriesOf(views: BlocksView): Entry[] {
  return [
    { ...DECISIONS_BLOCK, view: views.decisions },
    { ...CANDIDATES_BLOCK, view: views.candidates },
    { ...INCIDENTS_BLOCK, view: views.incidents },
  ];
}

function Block({ entry, hideTitle = false }: { entry: Entry; hideTitle?: boolean }) {
  const { view, title, seeAll } = entry;
  return (
    <BlockCard
      title={title}
      state={blockStateOf(view)}
      seeAll={seeAll}
      hideTitle={hideTitle}
      count={view.kind === "loaded" ? { text: view.countText, label: view.countLabel } : undefined}
      emptyNotice={view.kind === "empty" ? { label: view.text, detail: "El backend respondió y no hay nada que contar." } : undefined}
      footer={view.kind === "loaded" || view.kind === "empty" ? <BlockFooter footnote={view.footnote} /> : undefined}
    >
      {view.kind === "loaded" ? <BlockRows view={view} href={seeAll.href} /> : null}
    </BlockCard>
  );
}

export function Triptych({ views }: { views: BlocksView }) {
  const entries = entriesOf(views);
  return (
    <section aria-label="Decisiones, candidatos e incidencias">
      <div className="hidden gap-4 xl:grid xl:grid-cols-3">
        {entries.map((entry) => (
          <Block key={entry.key} entry={entry} />
        ))}
      </div>

      <Tabs defaultValue={entries[0].key} className="xl:hidden">
        <TabsList className="h-auto w-full flex-wrap justify-start">
          {entries.map((entry) => (
            <TabsTrigger key={entry.key} value={entry.key} className="min-w-0 flex-1">
              {entry.tab}
            </TabsTrigger>
          ))}
        </TabsList>
        {entries.map((entry) => (
          <TabsContent key={entry.key} value={entry.key}>
            <Block entry={entry} hideTitle />
          </TabsContent>
        ))}
      </Tabs>
    </section>
  );
}

/** Mientras el servidor lee: ninguna cifra, ningún cero, ningún «Sin leer». */
function TriptychSkeleton() {
  return (
    <section aria-label="Decisiones, candidatos e incidencias" aria-busy="true">
      <div className="grid gap-4 xl:grid-cols-3">
        {[DECISIONS_BLOCK, CANDIDATES_BLOCK, INCIDENTS_BLOCK].map((block) => (
          <Card key={block.key} data-block={block.title} data-block-state="reading" className="min-w-0">
            <CardHeader>
              <CardTitle className="text-sm font-semibold">{block.title}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              <p className="text-sm text-muted-foreground">Leyendo…</p>
              <div aria-hidden className="h-6 w-2/3 animate-pulse rounded bg-muted" />
            </CardContent>
          </Card>
        ))}
      </div>
    </section>
  );
}

async function TriptychBlocks() {
  return <Triptych views={await readBlocksNow(api)} />;
}

export function DecisionTriptych() {
  return (
    <Suspense fallback={<TriptychSkeleton />}>
      <TriptychBlocks />
    </Suspense>
  );
}
