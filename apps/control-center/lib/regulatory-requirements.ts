import type {
  ComplianceState,
  ExistenceState,
  LegalAnalysis,
  LegalStatus,
  RegulatoryRequirement,
  SupplierProvenance,
} from "./api.ts";

/** La lógica de la pantalla de requisitos regulatorios (Milestone 41, ADR 0019).
 *
 * Vive aquí y no en el componente porque es la regla del proyecto y porque es lo
 * que hay que poder probar. Lo que esta capa protege es la **separación de tres
 * cuestiones** que suelen viajar mezcladas: la aplicabilidad (la declara una
 * persona), la existencia y vigencia (la comprueba la fuente) y la evidencia de
 * cumplimiento. Ninguna se rellena con otra, y `PASS` no se presenta nunca como
 * «producto legal».
 */

export type RealLegalAnalysis = LegalAnalysis & {
  data: NonNullable<LegalAnalysis["data"]> & { legal_status: LegalStatus };
};

/** Un análisis real lleva `legal_status`; el simulado (mock) no. */
export function isRealAnalysis(analysis: LegalAnalysis | undefined | null): analysis is RealLegalAnalysis {
  return Boolean(analysis?.data && typeof analysis.data.legal_status === "string");
}

export interface StatusInfo {
  title: string;
  detail: string;
  tone: "ok" | "warn" | "bad" | "muted";
}

/** Cómo se cuenta cada estado. `PASS` dice exactamente lo que significa y nada
 * más: sin «legal», sin «cumple» y sin «100 %». */
export function statusInfo(status: LegalStatus): StatusInfo {
  switch (status) {
    case "PASS":
      return {
        title: "Sin bloqueo en lo declarado",
        detail:
          "Dentro del alcance y de los requisitos declarados y comprobados, Legal no ha encontrado un bloqueo. Lo que nadie declaró no se ha mirado. No es una garantía de que el producto sea legal.",
        tone: "ok",
      };
    case "REVIEW_REQUIRED":
      return {
        title: "Requiere revisión humana",
        detail: "Hay algo que una persona debe resolver antes de concluir.",
        tone: "warn",
      };
    case "BLOCKED":
      return {
        title: "Bloqueado",
        detail:
          "Un requisito de tipo restricción, con la norma verificada y en vigor, no tiene evidencia de cumplimiento.",
        tone: "bad",
      };
    case "UNKNOWN":
      return {
        title: "Sin datos: desconocido",
        detail:
          "Nadie ha declarado requisitos para este alcance y jurisdicción. Que no haya nada declarado no significa que no haya requisitos.",
        tone: "muted",
      };
  }
}

const EXISTENCE_LABEL: Record<ExistenceState, string> = {
  verified_in_force: "En vigor según la fuente",
  verified_not_in_force: "No en vigor según la fuente",
  not_found: "La fuente no la conoce",
  source_inconsistent: "La fuente se contradice",
  unverified: "La fuente no indica vigencia",
  stale: "Comprobación vencida",
  never_checked: "Nunca comprobada",
};

export function existenceLabel(state: ExistenceState): string {
  return EXISTENCE_LABEL[state];
}

/** `stale` y `never_checked` son de **nuestra política de recomprobación**: no
 * dicen nada de si la norma sigue en vigor. La pantalla lo aclara. */
export function existenceNote(state: ExistenceState): string | null {
  if (state === "stale") {
    return "Ha vencido la política interna de recomprobación. No significa que la norma haya dejado de estar en vigor.";
  }
  if (state === "never_checked") return "Nadie ha preguntado todavía a la fuente por esta norma.";
  return null;
}

const COMPLIANCE_LABEL: Record<ComplianceState, string> = {
  none: "Sin evidencia",
  declared: "Evidencia declarada",
  third_party_verified: "Evidencia de un tercero",
  expired: "Evidencia caducada",
};

export function complianceLabel(state: ComplianceState): string {
  return COMPLIANCE_LABEL[state];
}

const PROVENANCE_LABEL: Partial<Record<SupplierProvenance, string>> = {
  declared: "Declarado por una persona",
  third_party_verified: "Verificado por un tercero",
};

export function provenanceLabel(provenance: SupplierProvenance): string {
  return PROVENANCE_LABEL[provenance] ?? provenance;
}

/** La línea de cabecera de la tarjeta de evaluación. Un análisis real nunca se
 * lee como «favorable»: dice el estado y la regla de confianza. */
export function analysisHeadline(analysis: LegalAnalysis | undefined, marketLabel: string): string {
  if (!analysis) return `Sin análisis en ${marketLabel}`;
  if (isRealAnalysis(analysis)) {
    const percent = Math.round(analysis.confidence * 100);
    return `${statusInfo(analysis.data.legal_status).title} · techo de confianza ${percent} % (regla interna, no calibrada)`;
  }
  const verdict =
    analysis.recommendation === "GO" ? "favorable" : analysis.recommendation === "REVIEW" ? "a revisar" : "no viable";
  return `Agente legal (simulado): ${verdict} · confianza ${Math.round(analysis.confidence * 100)} %`;
}

/** Fechas tal como las entrega la fuente. Se enseñan, no se interpretan: puede
 * haber varias, y un fin de validez que la fuente no documenta no se traduce. */
export function sourceDatesLine(from: string[] | null | undefined, to: string | null | undefined): string {
  const start = from && from.length > 0 ? from.join(" · ") : "sin fecha";
  const end = to ? to : "sin dato";
  return `Fechas de la fuente, sin interpretar — desde: ${start}; hasta: ${end}`;
}

// --- Formulario de alta --------------------------------------------------------

export interface RequirementForm {
  productScope: string;
  celex: string;
  regulation: string;
  reference: string;
  requirement: string;
  kind: "obligation" | "restriction";
  transposition: string;
  note: string;
}

export const EMPTY_REQUIREMENT: RequirementForm = {
  productScope: "",
  celex: "",
  regulation: "",
  reference: "",
  requirement: "",
  kind: "obligation",
  transposition: "",
  note: "",
};

export interface RequirementProblem {
  field: keyof RequirementForm;
  message: string;
}

/** La forma de un CELEX de acto legislativo del sector 3 (`32014L0035`). El
 * backend es quien decide; esto solo evita el viaje con un error evidente. */
export const CELEX_PATTERN = /^3\d{4}[A-Za-z]\d{4}$/;

export function requirementProblems(form: RequirementForm): RequirementProblem[] {
  const found: RequirementProblem[] = [];
  if (!form.productScope.trim()) {
    found.push({ field: "productScope", message: "Falta el alcance de producto al que declaras que se aplica." });
  }
  if (!CELEX_PATTERN.test(form.celex.trim())) {
    found.push({ field: "celex", message: "El CELEX debe tener la forma 32014L0035." });
  }
  if (!form.regulation.trim()) found.push({ field: "regulation", message: "Falta el nombre de la norma." });
  if (!form.requirement.trim()) found.push({ field: "requirement", message: "Falta el requisito." });
  return found;
}

export function requirementPayload(form: RequirementForm) {
  const transposition = form.transposition.trim();
  return {
    product_scope: form.productScope.trim(),
    // Solo la UE: es lo único que la fuente cubre.
    jurisdiction: "eu",
    celex: form.celex.trim().toUpperCase(),
    regulation: form.regulation.trim(),
    requirement: form.requirement.trim(),
    kind: form.kind,
    reference: form.reference.trim() || null,
    // La aplicabilidad la declara siempre una persona desde esta pantalla.
    applicability_provenance: "declared" as SupplierProvenance,
    transposition_reference: transposition || null,
    transposition_provenance: transposition ? ("declared" as SupplierProvenance) : null,
    note: form.note.trim() || null,
  };
}

export interface EvidenceForm {
  reference: string;
  provenance: SupplierProvenance;
  issuer: string;
  validUntil: string;
}

export const EMPTY_EVIDENCE: EvidenceForm = {
  reference: "",
  provenance: "declared",
  issuer: "",
  validUntil: "",
};

export function evidenceProblems(form: EvidenceForm): string[] {
  const found: string[] = [];
  if (form.provenance === "third_party_verified" && !form.issuer.trim()) {
    found.push("«Emitida por un tercero» exige decir quién la emitió.");
  }
  return found;
}

export function evidencePayload(requirementId: string, form: EvidenceForm) {
  return {
    requirement_id: requirementId,
    provenance: form.provenance,
    source: form.issuer.trim() || null,
    reference: form.reference.trim() || null,
    valid_until: form.validUntil || null,
  };
}

/** Los requisitos declarados para el alcance del producto: emparejamiento
 * exacto tras normalizar mayúsculas y espacios. El backend usa una clave más
 * estricta (sin tildes); aquí solo se ordena la lista para la vista. */
export function requirementsFor(requirements: RegulatoryRequirement[], scope: string): RegulatoryRequirement[] {
  const key = scope.trim().replace(/\s+/g, " ").toLocaleLowerCase();
  return requirements.filter((r) => r.product_scope.trim().replace(/\s+/g, " ").toLocaleLowerCase() === key);
}
