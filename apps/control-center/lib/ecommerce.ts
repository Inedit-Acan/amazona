import type { EconomicAnalysis, LegalAnalysis, Storefront } from "./api.ts";
import { MARKET_LABELS } from "./markets.ts";

// La tienda la genera el agente de e-commerce a partir de los análisis previos
// (economía, legal, proveedor). Este módulo NO decide si algo está listo: solo
// pone en orden lo que esos análisis y el borrador de tienda ya dicen.

export type ChecklistState = "done" | "todo" | "pending";

export interface ReadinessItem {
  key: string;
  label: string;
  state: ChecklistState;
  detail: string;
}

/** Launch Readiness de la spec §9.10. done = ya cumplido con datos reales; todo =
 * falta o hay que resolverlo; pending = ni existe en el backend todavía. */
export function launchReadiness(input: {
  economic?: Pick<EconomicAnalysis, "recommendation">;
  storefront?: Pick<Storefront, "launch_status">;
  legal?: Pick<LegalAnalysis, "recommendation">;
}): ReadinessItem[] {
  const { economic, storefront, legal } = input;

  const legalItem: ReadinessItem = !legal
    ? { key: "legal", label: "Legal", state: "todo", detail: "Falta el análisis legal de este mercado" }
    : legal.recommendation === "GO"
      ? { key: "legal", label: "Legal", state: "done", detail: "Legal Gate: preparado" }
      : {
          key: "legal",
          label: "Legal",
          state: "todo",
          detail: legal.recommendation === "NO_GO" ? "Legal Gate bloqueado" : "Legal Gate: requiere revisión humana",
        };

  const priceItem: ReadinessItem = !economic
    ? { key: "price", label: "Precio", state: "todo", detail: "Falta el análisis económico" }
    : economic.recommendation === "NO_GO"
      ? { key: "price", label: "Precio", state: "todo", detail: "El análisis económico no es viable" }
      : { key: "price", label: "Precio", state: "done", detail: "Precio de venta del análisis económico" };

  return [
    { key: "product", label: "Producto", state: "done", detail: "Producto investigado" },
    priceItem,
    {
      key: "page",
      label: "Página",
      state: storefront ? "done" : "todo",
      detail: storefront ? "Borrador de tienda generado" : "Aún no se ha generado la tienda",
    },
    {
      key: "checkout",
      label: "Checkout",
      state: "todo",
      detail: "Plan de pasarela solo en modo prueba; salir en vivo requiere aprobación humana",
    },
    legalItem,
    { key: "analytics", label: "Analytics", state: "pending", detail: "Sin integración de analítica" },
    { key: "tracking", label: "Tracking", state: "pending", detail: "Sin integración de seguimiento" },
    { key: "domain", label: "Dominio", state: "pending", detail: "Sin dominio ni hosting" },
    { key: "emails", label: "Emails", state: "pending", detail: "Sin plantillas de email transaccional" },
  ];
}

export interface ContentItem {
  label: string;
  generated: boolean;
}

/** Qué piezas de contenido trae realmente el borrador de tienda. Las que el
 * generador no produce (FAQ, multimedia, SEO, datos estructurados) salen sin
 * generar en lugar de aparentar estar hechas. */
export function contentChecklist(storefront: Pick<Storefront, "data">): ContentItem[] {
  const copy = storefront.data?.landing_page_copy;
  return [
    { label: "Título y propuesta de valor", generated: Boolean(copy?.headline) },
    { label: "Descripción del producto", generated: Boolean(copy?.subheadline) },
    { label: "Beneficios y características", generated: (copy?.bullets?.length ?? 0) > 0 },
    { label: "Llamada a la acción (CTA)", generated: Boolean(copy?.cta) },
    { label: "FAQ (preguntas frecuentes)", generated: false },
    { label: "Imágenes y multimedia", generated: false },
    { label: "Meta title y meta description", generated: false },
    { label: "Datos estructurados (schema.org)", generated: false },
  ];
}

export interface MarketRow {
  market: string;
  price: number | null;
  launchStatus: Storefront["launch_status"];
  slug: string;
}

/** Una fila por mercado con el borrador de tienda más reciente (la API los
 * devuelve del más reciente al más antiguo). Primero los mercados conocidos, en
 * su orden habitual, y luego el resto. */
export function marketRows(storefronts: Pick<Storefront, "market" | "launch_status" | "store_slug" | "data">[]): MarketRow[] {
  const seen = new Map<string, MarketRow>();
  for (const storefront of storefronts) {
    if (seen.has(storefront.market)) continue;
    seen.set(storefront.market, {
      market: storefront.market,
      price: storefront.data?.catalog_entry?.price ?? null,
      launchStatus: storefront.launch_status,
      slug: storefront.store_slug,
    });
  }
  const known = Object.keys(MARKET_LABELS);
  const rank = (market: string) => {
    const index = known.indexOf(market);
    return index === -1 ? known.length : index;
  };
  return [...seen.values()].sort((a, b) => rank(a.market) - rank(b.market) || a.market.localeCompare(b.market));
}
