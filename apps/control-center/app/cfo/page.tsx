import { api, type CFOReport, type EconomicAnalysis, type Product } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { ApiErrorAlert } from "@/components/api-error";
import { CfoWorkspace } from "./cfo-workspace";

/** Tope de productos de los que se lee la última decisión económica: hoy no hay un
 * endpoint agregado y cada producto cuesta una petición. */
const PORTFOLIO_PRODUCT_LIMIT = 20;

export default async function CFOPage() {
  let reports: CFOReport[] = [];
  let products: Product[] = [];
  let analyses: Record<string, EconomicAnalysis[]> = {};
  let error: string | null = null;

  try {
    const [loadedReports, loadedProducts] = await Promise.all([api.listCFORuns(), api.listProducts()]);
    reports = loadedReports;
    products = loadedProducts;
    const entries = await Promise.all(
      products.slice(0, PORTFOLIO_PRODUCT_LIMIT).map(async (p) => [p.id, await api.listProductEconomics(p.id)] as const),
    );
    analyses = Object.fromEntries(entries);
  } catch (err) {
    error = err instanceof Error ? err.message : "Error desconocido";
  }

  return (
    <div>
      <PageHeader
        title="Finanzas y control"
        description="Consolida las decisiones económicas, las campañas y las reservas del BudgetEngine en un informe de salud financiera de todo el catálogo — no por producto. Es un informe agregado: este agente nunca emite facturas (la facturación real debe pasar por un sistema certificado Verifactu de terceros) y todavía no hay contabilidad, tesorería ni caja reales."
      />

      {error ? (
        <ApiErrorAlert message={error} />
      ) : (
        <CfoWorkspace
          initialReports={reports}
          products={products.slice(0, PORTFOLIO_PRODUCT_LIMIT)}
          totalProducts={products.length}
          analysesByProduct={analyses}
        />
      )}
    </div>
  );
}
