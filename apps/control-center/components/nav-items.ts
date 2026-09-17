// Orden y etiquetas: "Orden final del menú principal" en
// docs/design/AMAZONA_especificacion_paneles_aprobados_parte2.md (§2).
//
// /marketplace se fusionó en "Tienda y canales de venta" como pestaña de
// canal (Milestone 16) — ya no es ruta ni ítem de menú aparte.
//
// Una ruta existente queda deliberadamente fuera de este menú, sin
// borrarla, hasta que se fusione su contenido:
//   - /pipeline: revisiones y kill switch del PipelineOrchestrator
//     (ADR-0006) no están en la especificación de paneles aprobada; por
//     el mapeo "Decisión humana → Aprobaciones" (parte2 §10) y por ser el
//     mismo patrón aprobar/rechazar que api/approvals.py, deberían vivir
//     como pestaña dentro de "Aprobaciones", no como ítem propio.
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
