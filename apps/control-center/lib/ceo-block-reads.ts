import type { Approval, Incident, PipelineKillSwitchState, PipelineReview, Product } from "./api.ts";
import { approvalsContract, incidentsContract, killSwitchContract, productsContract, reviewsContract } from "./ceo-block-contracts.ts";
import { decisionsBlock } from "./ceo-decisions.ts";
import { candidatesBlock } from "./ceo-opportunities.ts";
import { incidentsBlock } from "./ceo-risks.ts";
import type { BlockView } from "./ceo-block-view.ts";
import { readList, readOne } from "./read-state.ts";

// LAS LECTURAS de los tres bloques ejecutivos del Director ejecutivo (M47, Commit 3B): CINCO peticiones, cada una UNA vez, en paralelo.
// Ninguna lleva ventana temporal: aprobaciones, revisiones, catálogo, incidencias y kill switch son el ESTADO ACTUAL, y el selector
// 7 / 14 / 30 días gobierna solo Ingresos. Cada lectura se clasifica (`loaded` / `empty` / `error`), cada fila se comprueba contra su
// contrato, y un fallo o un contrato roto es `error` del bloque que lo sufre: nunca una lista vacía ni datos de demostración.

/** Lo que hace falta del cliente de la API; así las pruebas leen con una fuente que cuenta sus llamadas. */
export interface BlocksSource {
  listApprovals(): Promise<Approval[]>;
  listPipelineReviews(): Promise<PipelineReview[]>;
  listProducts(): Promise<Product[]>;
  listIncidents(): Promise<Incident[]>;
  getPipelineKillSwitch(): Promise<PipelineKillSwitchState>;
}

export interface BlocksView {
  decisions: BlockView;
  candidates: BlockView;
  incidents: BlockView;
}

/** `now` decide qué aprobación está vencida; lo fija quien llama (el servidor, una vez por petición). */
export async function readBlocks(source: BlocksSource, now: number): Promise<BlocksView> {
  const [approvals, reviews, products, incidents, killSwitch] = await Promise.all([
    readList(() => source.listApprovals(), "las aprobaciones"),
    readList(() => source.listPipelineReviews(), "las revisiones de pipeline"),
    readList(() => source.listProducts(), "el catálogo de productos"),
    readList(() => source.listIncidents(), "las incidencias"),
    readOne(() => source.getPipelineKillSwitch(), "el estado del pipeline"),
  ]);
  return {
    decisions: decisionsBlock({ approvals: approvalsContract(approvals), reviews: reviewsContract(reviews), now }),
    candidates: candidatesBlock({ products: productsContract(products) }),
    incidents: incidentsBlock({ incidents: incidentsContract(incidents), killSwitch: killSwitchContract(killSwitch) }),
  };
}

export function readBlocksNow(source: BlocksSource): Promise<BlocksView> {
  return readBlocks(source, Date.now());
}
