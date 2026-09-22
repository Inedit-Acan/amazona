import {
  api,
  type Agent,
  type AuditEntry,
  type Decision,
  type Product,
  type Project,
  type Task,
} from "@/lib/api";
import { EMPTY_PRODUCT_OPERATIONS_DATA, loadProductOperationsData, type ProductOperationsData } from "@/lib/product-channels";
import { PageHeader } from "@/components/page-header";
import { ApiErrorAlert } from "@/components/api-error";
import { PROJECTS_DESCRIPTION, PROJECTS_TITLE } from "./copy";
import { ProjectsWorkspace } from "./projects-workspace";

/** Tope de productos que se convierten en proyectos: cada uno cuesta varias peticiones. */
const PRODUCT_LIMIT = 12;

export interface ProductProjectData {
  product: Product;
  data: ProductOperationsData;
}

export interface BackendProject {
  project: Project;
  tasks: Task[];
  decision: Decision | null;
}

export default async function ProjectsPage({ searchParams }: PageProps<"/projects">) {
  const params = await searchParams;
  const requested = Array.isArray(params.proyecto) ? params.proyecto[0] : params.proyecto;

  let products: Product[] = [];
  let error: string | null = null;
  try {
    products = await api.listProducts();
  } catch (err) {
    error = err instanceof Error ? err.message : "Error desconocido";
  }

  const productData: ProductProjectData[] = await Promise.all(
    products.slice(0, PRODUCT_LIMIT).map(async (product) => ({
      product,
      data: await loadProductOperationsData(product.id).catch(() => EMPTY_PRODUCT_OPERATIONS_DATA),
    })),
  );

  // Lo que el Director ejecutivo sí tiene en el backend: sus proyectos con tareas
  // y decisión. Hoy pueden ser cero; la cartera se apoya en los productos.
  const projects = await api.listProjects().catch(() => [] as Project[]);
  const backend: BackendProject[] = await Promise.all(
    projects.map(async (project) => ({
      project,
      tasks: await api.listTasks(project.id).catch(() => [] as Task[]),
      decision: (await api.listDecisionsForProject(project.id).catch(() => [] as Decision[]))[0] ?? null,
    })),
  );

  const audit: AuditEntry[] = await api.listAudit().catch(() => []);
  const agents: Agent[] = await api.listAgents().catch(() => []);

  if (error) {
    return (
      <div>
        <PageHeader title={PROJECTS_TITLE} description={PROJECTS_DESCRIPTION} />
        <ApiErrorAlert message={error} />
      </div>
    );
  }

  // El día se fija en el servidor: los proyectos de demostración y los pedidos son
  // deterministas a partir de él y el cliente hidrata lo mismo.
  const today = new Date().toISOString().slice(0, 10);

  return (
    <ProjectsWorkspace
      productData={productData}
      backend={backend}
      audit={audit}
      agents={agents}
      today={today}
      initialSelection={requested}
    />
  );
}
