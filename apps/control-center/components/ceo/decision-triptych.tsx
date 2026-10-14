import { BlockCard } from "@/components/ceo/block-card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { NOT_CONNECTED_YET, type BlockState } from "@/lib/ceo-blocks";

/** Decisiones pendientes / Oportunidades detectadas / Riesgos activos (M47, Commit 2): solo estructura y estados de lectura.
 * Cada bloque tiene su fuente (aprobaciones y revisiones, catálogo de productos, incidencias y evidencias) y todavía no la ha
 * leído → `unread`. Se conectan en el Commit 4. Sin contadores ni filas: no hay nada leído que contar. */
interface Block {
  key: string;
  title: string;
  /** El nombre corto de la pestaña (en 496 px no caben los tres nombres completos). */
  tab: string;
  state: BlockState<unknown>;
  seeAll: { href: string; label: string };
}

const BLOCKS: Block[] = [
  { key: "decisiones", title: "Decisiones pendientes", tab: "Decisiones", state: NOT_CONNECTED_YET, seeAll: { href: "/approvals", label: "Ver todas" } },
  { key: "oportunidades", title: "Oportunidades detectadas", tab: "Oportunidades", state: NOT_CONNECTED_YET, seeAll: { href: "/research", label: "Ver todas" } },
  { key: "riesgos", title: "Riesgos activos", tab: "Riesgos", state: NOT_CONNECTED_YET, seeAll: { href: "/status", label: "Ver todos" } },
];

/** Desde `xl` (1280 px) son tres tarjetas, como el mockup; por debajo, pestañas: a menos ancho tres columnas no se leen. Las dos
 * presentaciones se resuelven por CSS (sin medir el ancho en JavaScript), así que no hay parpadeo al hidratar. */
export function DecisionTriptych() {
  return (
    <section aria-label="Decisiones, oportunidades y riesgos">
      <div className="hidden gap-4 xl:grid xl:grid-cols-3">
        {BLOCKS.map((block) => (
          <BlockCard key={block.key} title={block.title} state={block.state} seeAll={block.seeAll} />
        ))}
      </div>

      <Tabs defaultValue={BLOCKS[0].key} className="xl:hidden">
        <TabsList className="h-auto w-full flex-wrap justify-start">
          {BLOCKS.map((block) => (
            <TabsTrigger key={block.key} value={block.key} className="min-w-0 flex-1">
              {block.tab}
            </TabsTrigger>
          ))}
        </TabsList>
        {BLOCKS.map((block) => (
          <TabsContent key={block.key} value={block.key}>
            <BlockCard title={block.title} state={block.state} seeAll={block.seeAll} hideTitle />
          </TabsContent>
        ))}
      </Tabs>
    </section>
  );
}
