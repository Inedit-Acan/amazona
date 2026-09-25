import { api } from "@/lib/api-server";
import { type LegalAnalysis, type Product, type SupplierQuote } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { ApiErrorAlert } from "@/components/api-error";
import { LEGAL_DESCRIPTION, LEGAL_TITLE } from "./copy";
import { LegalWorkspace } from "./legal-workspace";

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function LegalPage({ searchParams }: PageProps<"/legal">) {
  const params = await searchParams;
  const requestedProductId = first(params.product_id);

  let products: Product[] = [];
  let analyses: LegalAnalysis[] = [];
  let quotes: SupplierQuote[] = [];
  let productId: string | undefined;
  let error: string | null = null;

  try {
    products = await api.listProducts();
    productId = products.find((p) => p.id === requestedProductId)?.id ?? products[0]?.id;
    if (productId) {
      [analyses, quotes] = await Promise.all([
        api.listProductLegal(productId).catch(() => [] as LegalAnalysis[]),
        api.listProductSuppliers(productId).catch(() => [] as SupplierQuote[]),
      ]);
    }
  } catch (err) {
    error = err instanceof Error ? err.message : "Error desconocido";
  }

  if (error) {
    return (
      <div>
        <PageHeader title={LEGAL_TITLE} description={LEGAL_DESCRIPTION} />
        <ApiErrorAlert message={error} />
      </div>
    );
  }

  return (
    <LegalWorkspace
      key={productId}
      products={products}
      productId={productId}
      // El backend los devuelve del más reciente al más antiguo.
      analyses={analyses}
      quotes={quotes}
      initialMarket={first(params.market) ?? analyses[0]?.market ?? "eu"}
    />
  );
}
