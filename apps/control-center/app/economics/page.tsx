import { api, type EconomicAnalysis, type Product, type SupplierQuote } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { ApiErrorAlert } from "@/components/api-error";
import { EconomicsWorkspace } from "./economics-workspace";
import { ECONOMICS_DESCRIPTION, ECONOMICS_TITLE } from "./copy";

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function EconomicsPage({ searchParams }: PageProps<"/economics">) {
  const params = await searchParams;
  const requestedProductId = first(params.product_id);
  const requestedQuoteId = first(params.supplier_quote_id);

  let products: Product[] = [];
  let quotes: SupplierQuote[] = [];
  let analyses: EconomicAnalysis[] = [];
  let productId: string | undefined;
  let error: string | null = null;

  try {
    products = await api.listProducts();
    productId = products.find((p) => p.id === requestedProductId)?.id ?? products[0]?.id;
    if (productId) {
      // Sin cotizaciones o sin análisis la pantalla sigue funcionando (con datos de demostración).
      [quotes, analyses] = await Promise.all([
        api.listProductSuppliers(productId).catch(() => [] as SupplierQuote[]),
        api.listProductEconomics(productId).catch(() => [] as EconomicAnalysis[]),
      ]);
    }
  } catch (err) {
    error = err instanceof Error ? err.message : "Error desconocido";
  }

  if (error) {
    return (
      <div>
        <PageHeader title={ECONOMICS_TITLE} description={ECONOMICS_DESCRIPTION} />
        <ApiErrorAlert message={error} />
      </div>
    );
  }

  return (
    <EconomicsWorkspace
      key={productId}
      products={products}
      productId={productId}
      quotes={quotes}
      // El backend los devuelve del más reciente al más antiguo.
      latestAnalysis={analyses[0]}
      requestedQuoteId={requestedQuoteId}
    />
  );
}
