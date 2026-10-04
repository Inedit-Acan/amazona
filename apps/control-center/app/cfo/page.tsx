import { api } from "@/lib/api-server";
import {
  type CFOReport,
  type EconomicAnalysis,
  type Order,
  type Product,
  type RevenueEntry,
  type RevenueSummary,
} from "@/lib/api";
import { parseRevenueDays, revenueWindow, type RevenueWindow } from "@/lib/revenue-query";
import { settle } from "@/lib/revenue-view";
import { PageHeader } from "@/components/page-header";
import { ApiErrorAlert } from "@/components/api-error";
import { CFO_DESCRIPTION, CFO_TITLE } from "./copy";
import { CfoWorkspace } from "./cfo-workspace";

/** Tope de productos de los que se lee el análisis económico: no hay endpoint agregado y cada producto cuesta una
 * petición. */
const PRODUCT_LIMIT = 20;

/** El margen necesita TODAS las entradas del periodo: con una lista truncada el ingreso por pedido estaría incompleto,
 * y entonces no se calcula (y se dice por qué). 200 es el máximo que admite `GET /api/revenue/entries`. */
const ENTRY_PAGE_SIZE = 200;
const ENTRY_PAGES = 5;

/** Pedidos que se leen para conocer el coste declarado. Un pedido que no se lee es coste **desconocido**, no cero. */
const ORDER_PAGE_SIZE = 100;
const ORDER_PAGES = 3;

export interface EntriesRead {
  entries: RevenueEntry[];
  /** Son todas las del periodo: el backend no dijo que hubiera más al agotar el tope. */
  complete: boolean;
}

export interface OrdersRead {
  orders: Order[];
  complete: boolean;
}

async function readEntries(window: RevenueWindow): Promise<EntriesRead> {
  const entries: RevenueEntry[] = [];
  let cursor: string | undefined;
  for (let page = 0; page < ENTRY_PAGES; page += 1) {
    const result = await api.revenueEntries({ window, cursor, limit: ENTRY_PAGE_SIZE });
    entries.push(...result.items);
    if (!result.has_more || result.next_cursor === null) return { entries, complete: true };
    cursor = result.next_cursor;
  }
  return { entries, complete: false };
}

async function readOrders(): Promise<OrdersRead> {
  const orders: Order[] = [];
  let cursor: string | undefined;
  for (let page = 0; page < ORDER_PAGES; page += 1) {
    const result = await api.listOrders({ limit: ORDER_PAGE_SIZE, cursor });
    orders.push(...result.items);
    if (!result.has_more || result.next_cursor === null) return { orders, complete: true };
    cursor = result.next_cursor;
  }
  return { orders, complete: false };
}

export default async function CFOPage({ searchParams }: PageProps<"/cfo">) {
  const params = await searchParams;
  let products: Product[] = [];
  let error: string | null = null;

  try {
    products = await api.listProducts();
  } catch (err) {
    error = err instanceof Error ? err.message : "Error desconocido";
  }

  // Los hechos del registro y el coste declarado de los pedidos. Cada lectura devuelve su dato o su error: un fallo se
  // enseña como fallo y NUNCA se sustituye por datos de demostración.
  const days = parseRevenueDays(params.dias);
  // Igual que el Panel: el instante se fija aquí, en el servidor, y la ventana sale de él.
  const span = revenueWindow(new Date().getTime(), days);
  const [summary, entries, orders] = await Promise.all([
    settle<RevenueSummary>(() => api.revenueSummary(span)),
    settle<EntriesRead>(() => readEntries(span)),
    settle<OrdersRead>(() => readOrders()),
  ]);

  // La proyección (PLAN) sale de los análisis económicos y el veredicto del agente CFO. Ambos son opcionales: sin
  // ellos la pantalla sigue en pie y lo dice.
  // Un error de lectura NO es «sin análisis» ni «sin evaluación»: se cuenta y se dice que no se pudo leer.
  const analysisReads = await Promise.all(
    products.slice(0, PRODUCT_LIMIT).map(async (product) => ({
      product,
      read: await settle<EconomicAnalysis[]>(() => api.listProductEconomics(product.id)),
    })),
  );
  const analyses = analysisReads.flatMap(({ product, read }): [string, EconomicAnalysis][] =>
    read.ok && read.data[0] !== undefined ? [[product.id, read.data[0]]] : [],
  );
  const planUnread = analysisReads.filter(({ read }) => !read.ok).length;
  const reportsRead = await settle<CFOReport[]>(() => api.listCFORuns());
  const reports = reportsRead.ok ? reportsRead.data : [];
  const verdictUnread = !reportsRead.ok;

  if (error) {
    return (
      <div>
        <PageHeader title={CFO_TITLE} description={CFO_DESCRIPTION} />
        <ApiErrorAlert message={error} />
      </div>
    );
  }

  return (
    <CfoWorkspace
      days={days}
      summary={summary}
      entries={entries}
      orders={orders}
      products={products.slice(0, PRODUCT_LIMIT)}
      analyses={analyses}
      planUnread={planUnread}
      report={reports[0]}
      verdictUnread={verdictUnread}
    />
  );
}
