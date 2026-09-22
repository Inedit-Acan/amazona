import { redirect } from "next/navigation";

/** La cartera y el detalle viven en la misma pantalla: los enlaces antiguos
 * (Auditoría, Aprobaciones, Director ejecutivo) abren el proyecto seleccionado. */
export default async function ProjectDetailPage({ params }: PageProps<"/projects/[id]">) {
  const { id } = await params;
  redirect(`/projects?proyecto=${encodeURIComponent(id)}`);
}
