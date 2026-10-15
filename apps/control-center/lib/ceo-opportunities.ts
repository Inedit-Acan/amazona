import type { Product } from "./api.ts";
import { emptyView, loadedView, plural, unusable, type BlockRow, type BlockView } from "./ceo-block-view.ts";
import { listOf, type ReadState } from "./read-state.ts";

// CANDIDATOS DETECTADOS (M47, Commit 3B, D-3B-2). El backend NO tiene hoy una entidad «oportunidad validada»: solo el CANDIDATO
// (`products`, estado CANDIDATE) que la investigación propone o que alguien da de alta a mano. Una «decisión GO» no está enlazada a un
// producto y la puntuación de investigación existe solo por ejecución y es una recomendación de un agente, no una validación.
//
// Por eso este bloque se llama «Candidatos detectados» y no «Oportunidades detectadas»: cada fila dice «Candidato · sin validar» y
// ninguna palabra afirma que algo esté validado o confirmado. El título «Oportunidades detectadas» volverá cuando exista una entidad
// real y un contrato que lo sostengan. La lista de productos no trae fecha, puntuación, prioridad, severidad ni confianza: no se enseña
// ninguna. El orden es el del backend.

export const CANDIDATES_BLOCK = {
  key: "candidatos",
  title: "Candidatos detectados",
  tab: "Candidatos",
  seeAll: { href: "/research", label: "Ver todos" },
} as const;

/** La línea secundaria fija: lo que este bloque NO puede decir todavía. */
export const CANDIDATES_FOOTNOTE = "Oportunidades validadas: no disponibles";

const CANDIDATE_TAG = "Candidato · sin validar";
const EMPTY_TEXT = "Sin candidatos en el catálogo.";

const ORIGIN_LABEL: Record<string, string> = {
  research: "Investigación",
  manual: "Manual",
};

function candidateRow(product: Product): BlockRow {
  const origin = ORIGIN_LABEL[product.source] ?? product.source;
  return {
    key: `product:${product.id}`,
    title: product.name,
    subtitle: product.category === "" ? origin : `${product.category} · ${origin}`,
    tag: { text: CANDIDATE_TAG },
    detail: [
      "Producto del catálogo en estado de candidato.",
      ...(product.also_known_as && product.also_known_as.length > 0 ? [`También conocido como: ${product.also_known_as.map((alias) => alias.alias).join(", ")}`] : []),
    ],
    provenance: {
      source: "products",
      entity: "product",
      id: product.id,
      status: product.status,
      areaLabel: origin,
      at: null,
      confidence: null,
      rationale: null,
    },
  };
}

export function candidatesBlock(input: { products: ReadState<Product[]> }): BlockView {
  const failed = unusable([input.products]);
  if (failed) return failed;

  const products = listOf(input.products) ?? [];
  if (products.length === 0) return emptyView(EMPTY_TEXT, CANDIDATES_FOOTNOTE);
  const countText = `${products.length} ${plural(products.length, "candidato", "candidatos")}`;
  return loadedView({ rows: products.map(candidateRow), countText, countLabel: countText, footnote: CANDIDATES_FOOTNOTE });
}
