import { api, type CFOReport, type EconomicAnalysis, type Product, type SupplierQuote } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { ApiErrorAlert } from "@/components/api-error";
import { CFO_DESCRIPTION, CFO_TITLE } from "./copy";
import { CfoWorkspace } from "./cfo-workspace";

/** Tope de productos de los que se leen cotizaciones y decisiones económicas: no
 * hay un endpoint agregado y cada producto cuesta dos peticiones. */
const PORTFOLIO_PRODUCT_LIMIT = 20;

export interface ProductFinanceData {
  product: Product;
  economics: EconomicAnalysis[];
  quotes: SupplierQuote[];
}

export default async function CFOPage() {
  let products: Product[] = [];
  let reports: CFOReport[] = [];
  let error: string | null = null;

  try {
    products = await api.listProducts();
  } catch (err) {
    error = err instanceof Error ? err.message : "Error desconocido";
  }
  // El informe del agente es opcional: sin él la pantalla sigue en pie.
  reports = await api.listCFORuns().catch(() => []);

  const data: ProductFinanceData[] = await Promise.all(
    products.slice(0, PORTFOLIO_PRODUCT_LIMIT).map(async (product) => ({
      product,
      economics: await api.listProductEconomics(product.id).catch(() => []),
      quotes: await api.listProductSuppliers(product.id).catch(() => []),
    })),
  );

  if (error) {
    return (
      <div>
        <PageHeader title={CFO_TITLE} description={CFO_DESCRIPTION} />
        <ApiErrorAlert message={error} />
      </div>
    );
  }

  // El día se fija en el servidor: los pedidos y los meses de la demostración son
  // deterministas a partir de él y el cliente hidrata exactamente lo mismo.
  const today = new Date().toISOString().slice(0, 10);

  return <CfoWorkspace data={data} report={reports[0]} totalProducts={products.length} today={today} />;
}
