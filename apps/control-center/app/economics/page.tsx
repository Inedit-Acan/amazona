import { api, type Product, type SupplierQuote } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { ApiErrorAlert } from "@/components/api-error";
import { EconomicsWorkspace } from "./economics-workspace";

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function EconomicsPage({ searchParams }: PageProps<"/economics">) {
  const params = await searchParams;
  const requestedProductId = first(params.product_id);
  const requestedQuoteId = first(params.supplier_quote_id);

  let products: Product[] = [];
  let quotes: SupplierQuote[] = [];
  let productId: string | undefined;
  let error: string | null = null;

  try {
    products = await api.listProducts();
    productId = products.find((p) => p.id === requestedProductId)?.id ?? products[0]?.id;
    quotes = productId ? await api.listProductSuppliers(productId) : [];
  } catch (err) {
    error = err instanceof Error ? err.message : "Error desconocido";
  }

  return (
    <div>
      <PageHeader
        title="Economía y rentabilidad"
        description="Analiza la viabilidad económica de un producto con escenarios y costes de entrega. Fase 3, Agente 3 — la conversión de demanda a ventas y los factores de escenario son valores de simulación."
      />

      {error ? (
        <ApiErrorAlert message={error} />
      ) : (
        <EconomicsWorkspace
          products={products}
          initialProductId={productId}
          initialQuotes={quotes}
          initialQuoteId={requestedQuoteId}
        />
      )}
    </div>
  );
}
