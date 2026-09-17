// Orden y etiquetas: "Orden final del menú principal" en
// docs/design/AMAZONA_especificacion_paneles_aprobados_parte2.md (§2).
//
// /marketplace se fusionó en "Tienda y canales de venta" como pestaña de
// canal (Milestone 16), y /pipeline se fusionó en "Aprobaciones" — las
// revisiones de riesgo del PipelineOrchestrator entran en la misma
// bandeja que Approval, y el kill switch vive como control fijo en la
// cabecera de esa página (Milestone 17, adenda a ADR-0006). Ninguna de
// las dos rutas es ya un ítem de menú aparte.
export const NAV_ITEMS = [
  { href: "/dashboard", label: "Panel" },
  { href: "/ceo", label: "Director ejecutivo" },
  { href: "/research", label: "Investigación" },
  { href: "/sourcing", label: "Proveedores y abastecimiento" },
  { href: "/economics", label: "Economía y rentabilidad" },
  { href: "/legal", label: "Legal y cumplimiento" },
  { href: "/ecommerce", label: "Tienda y canales de venta" },
  { href: "/marketing", label: "Marketing y adquisición" },
  { href: "/operations", label: "Operaciones" },
  { href: "/cfo", label: "Finanzas y control" },
  { href: "/projects", label: "Proyectos" },
  { href: "/agents", label: "Agentes" },
  { href: "/approvals", label: "Aprobaciones" },
  { href: "/audit", label: "Auditoría" },
  { href: "/status", label: "Estado" },
] as const;
