import { api, type LegalAnalysis, type Product, type SupplierQuote } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { ApiErrorAlert } from "@/components/api-error";
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
      [analyses, quotes] = await Promise.all([api.listProductLegal(productId), api.listProductSuppliers(productId)]);
    }
  } catch (err) {
    error = err instanceof Error ? err.message : "Error desconocido";
  }

  return (
    <div>
      <PageHeader
        title="Legal y cumplimiento"
        description="Analiza los requisitos regulatorios, certificaciones y riesgos legales para vender un producto en el mercado elegido — Fase 3, Agente 4. El dataset regulatorio es simulado: no es asesoría ni investigación legal real."
      />

      {error ? (
        <ApiErrorAlert message={error} />
      ) : (
        <LegalWorkspace
          products={products}
          initialProductId={productId}
          initialAnalyses={analyses}
          initialQuotes={quotes}
        />
      )}
    </div>
  );
}
