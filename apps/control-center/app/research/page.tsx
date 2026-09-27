import { api } from "@/lib/api-server";
import { type Product, type ResearchCandidate, type ResearchComparison } from "@/lib/api";
import { ApiErrorAlert } from "@/components/api-error";
import { PageHeader } from "@/components/page-header";
import { RESEARCH_DESCRIPTION, RESEARCH_TITLE } from "./copy";
import { ResearchWorkspace } from "./research-workspace";

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function ResearchPage({ searchParams }: PageProps<"/research">) {
  const params = await searchParams;
  // Investigaciones lanzadas desde esta pantalla: se guardan en la URL para que
  // sus señales reales sobrevivan a una recarga (el backend no lista las pasadas).
  const runIds = (first(params.runs) ?? "").split(",").filter(Boolean).slice(0, 5);

  let products: Product[] = [];
  let candidates: ResearchCandidate[] = [];
  // Informes de «qué dice cada proveedor» (Milestone 35). Si falla, no se
  // enseña ninguno: es un informe, no un dato que se pueda estimar.
  let comparisons: ResearchComparison[] = [];
  let error: string | null = null;
  try {
    const [list, runs, reports] = await Promise.all([
      api.listProducts(),
      Promise.all(runIds.map((id) => api.getResearchRun(id).catch(() => null))),
      api.listResearchComparisons().catch((): ResearchComparison[] => []),
    ]);
    products = list;
    candidates = runs.flatMap((run) => run?.candidates ?? []);
    comparisons = reports;
  } catch (err) {
    error = err instanceof Error ? err.message : "Error desconocido";
  }

  if (error) {
    return (
      <div>
        <PageHeader title={RESEARCH_TITLE} description={RESEARCH_DESCRIPTION} />
        <ApiErrorAlert message={error} />
      </div>
    );
  }

  return (
    <ResearchWorkspace
      key={runIds.join(",")}
      products={products}
      candidates={candidates}
      comparisons={comparisons}
      runIds={runIds}
    />
  );
}
