import { api } from "@/lib/api-server";
import { type Product, type SupplierQuote } from "@/lib/api";
import { DEFAULT_SEARCH, type SearchParams } from "@/lib/sourcing-view";
import { PageHeader } from "@/components/page-header";
import { ApiErrorAlert } from "@/components/api-error";
import { SOURCING_DESCRIPTION, SOURCING_TITLE } from "./copy";
import { SourcingWorkspace } from "./sourcing-workspace";

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function SourcingPage({ searchParams }: PageProps<"/sourcing">) {
  const params = await searchParams;
  const requestedProductId = first(params.product_id);
  // «Guardar búsqueda» deja los parámetros en la URL.
  const search: SearchParams = {
    destination: first(params.dest) ?? DEFAULT_SEARCH.destination,
    origin: first(params.origin) ?? DEFAULT_SEARCH.origin,
    logistics: first(params.logistics) ?? DEFAULT_SEARCH.logistics,
    minPrice: first(params.pmin) ?? "",
    maxPrice: first(params.pmax) ?? "",
    maxLeadTime: first(params.lead) ?? "",
    maxMoq: first(params.moq) ?? "",
    requireCertification: first(params.cert) === "1",
    verifiedOnly: first(params.verified) === "1",
    maxResults: Number(first(params.max)) || DEFAULT_SEARCH.maxResults,
  };

  let products: Product[] = [];
  let quotes: SupplierQuote[] = [];
  let productId: string | undefined;
  let error: string | null = null;
  try {
    products = await api.listProducts();
    productId = products.find((p) => p.id === requestedProductId)?.id ?? products[0]?.id;
    if (productId) quotes = await api.listProductSuppliers(productId).catch(() => [] as SupplierQuote[]);
  } catch (err) {
    error = err instanceof Error ? err.message : "Error desconocido";
  }

  if (error) {
    return (
      <div>
        <PageHeader title={SOURCING_TITLE} description={SOURCING_DESCRIPTION} />
        <ApiErrorAlert message={error} />
      </div>
    );
  }

  return <SourcingWorkspace key={productId} products={products} productId={productId} quotes={quotes} initialSearch={search} />;
}
