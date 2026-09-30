import type {
  Corroboration,
  NationalAnchor,
  NationalAssessment,
  NationalRelation,
  NationalState,
  NationalTransposition,
  PublicationState,
} from "./api.ts";

/** La lógica de la pantalla de transposiciones nacionales (Milestone 43, ADR 0021).
 *
 * Vive aquí y no en el componente porque es la regla del proyecto y porque es lo que
 * hay que poder probar. Lo que esta capa protege:
 *
 * - la norma la **declara una persona**; el BOE solo la verifica y la ancla;
 * - la consolidación y el análisis del BOE son **meramente informativos**: el aviso y
 *   la atribución que exige la licencia salen siempre junto a cualquier dato suyo;
 * - las fechas de la fuente se enseñan **tal cual**, sin interpretarlas;
 * - un fallo de la comprobación de publicación **no** es «no existe».
 */

/** Lo que exige la licencia de la AEBOE junto a cualquier dato de legislación
 * consolidada. La API los devuelve con cada norma; esto es el respaldo. */
export const BOE_NOTICE =
  "Texto consolidado de carácter meramente informativo. Para fines jurídicos debe consultarse la publicación oficial.";
export const BOE_ATTRIBUTION = "Basado en datos de la Agencia Estatal Boletín Oficial del Estado";
export const BOE_SITE = "https://www.boe.es";

/** `BOE-A-2011-14252`. Se declara, no se busca. */
export const BOE_ID_PATTERN = /^BOE-[A-Z]-\d{4}-\d{1,6}$/;

/** Solo una directiva se traspone. Se decide por el CELEX (`3AAAALNNNN`: `L` es directiva),
 * que es determinista, y no por lo que EUR-Lex haya dicho: así se puede declarar la norma
 * antes de la primera comprobación contra EUR-Lex. */
export function isDirectiveCelex(celex: string): boolean {
  return /^3\d{4}L\d{4}$/.test(celex.trim().toUpperCase());
}

export function nationalIdProblems(input: string): string[] {
  const value = input.trim();
  if (value === "") return ["Falta el identificador de la norma en el BOE (por ejemplo BOE-A-2011-14252)."];
  if (!BOE_ID_PATTERN.test(value.toUpperCase())) {
    return ["No es un identificador del BOE. Tiene la forma BOE-A-2011-14252, no el nombre de la norma."];
  }
  return [];
}

export function nationalIdPayload(input: string, note: string): { national_id: string; note: string | null } {
  return { national_id: input.trim().toUpperCase(), note: note.trim() === "" ? null : note.trim() };
}

export interface StateInfo {
  label: string;
  tone: "ok" | "warn" | "muted";
}

const STATE_INFO: Record<NationalState, StateInfo> = {
  verified_in_force: { label: "En vigor según el BOE", tone: "ok" },
  not_in_force: { label: "Derogada, anulada o con la vigencia agotada según el BOE", tone: "warn" },
  not_consolidated: { label: "El BOE no la tiene consolidada", tone: "warn" },
  outdated_consolidation: { label: "Consolidación desactualizada", tone: "warn" },
  unverified: { label: "El BOE no dio un estado legible", tone: "warn" },
  relation_flagged: { label: "Relaciones de anulación o suspensión: revisar", tone: "warn" },
  publication_inconsistent: { label: "Metadatos y sumario oficial no coinciden", tone: "warn" },
  stale: { label: "Comprobación vencida", tone: "muted" },
  never_checked: { label: "Nunca comprobada", tone: "muted" },
};

export function nationalStateInfo(state: NationalState): StateInfo {
  return STATE_INFO[state];
}

/** `not_consolidated`, `stale` y `never_checked` no dicen nada de si la norma existe o
 * está en vigor: se aclara en pantalla. */
export function nationalStateNote(state: NationalState): string | null {
  switch (state) {
    case "not_consolidated":
      return "Un 404 del BOE significa «no consolidada o inexistente»: no dice que la norma no exista.";
    case "stale":
      return "Ha vencido la política interna de recomprobación. No significa que la norma haya dejado de estar en vigor.";
    case "never_checked":
      return "Nadie ha preguntado todavía al BOE por esta norma.";
    case "outdated_consolidation":
      return "El BOE tarda de 1 a 3 días en incorporar una modificación al texto consolidado.";
    case "relation_flagged":
      return "Se muestran las relaciones tal como las da el BOE. Su efecto jurídico no se interpreta aquí: lo decide una persona.";
    default:
      return null;
  }
}

const CORROBORATION_LABEL: Record<Corroboration, string> = {
  corroborated: "El análisis del BOE dice que traspone la directiva (426 TRANSPONE)",
  partial: "El análisis del BOE dice que la traspone solo parcialmente (427)",
  uncorroborated: "El análisis del BOE no dice que traspone esta directiva",
  not_assessable: "No evaluable: sin análisis del BOE o sin una lectura inequívoca del texto",
};

export function corroborationLabel(value: Corroboration): string {
  return CORROBORATION_LABEL[value];
}

const PUBLICATION_LABEL: Record<PublicationState, string> = {
  confirmed: "Consta en el sumario del diario oficial",
  absent_from_summary: "El sumario del día, leído bien, no la lista",
  check_failed: "No se pudo comprobar en el sumario (no significa que no esté publicada)",
  not_checked: "Sin comprobar (sin fecha de publicación, o anterior a 2009: solo es oficial el papel)",
};

export function publicationLabel(state: PublicationState): string {
  return PUBLICATION_LABEL[state];
}

function text(metadata: Record<string, unknown> | null | undefined, key: string): string | null {
  const value = metadata?.[key];
  return typeof value === "string" && value !== "" ? value : null;
}

/** Las fechas de la fuente **tal cual**, en su formato `AAAAMMDD`. Se enseñan, no se
 * interpretan ni se comparan con hoy. */
export function sourceDatesText(anchor: NationalAnchor | null): string {
  const meta = anchor?.source_metadata;
  const parts = [
    ["publicación", text(meta, "fecha_publicacion")],
    ["entrada en vigor", text(meta, "fecha_vigencia")],
    ["derogación", text(meta, "fecha_derogacion")],
    ["anulación", text(meta, "fecha_anulacion")],
    ["actualización de la fuente", anchor?.source_updated_at ?? null],
  ] as const;
  const shown = parts.filter(([, value]) => value !== null).map(([label, value]) => `${label}: ${value}`);
  return `Fechas de la fuente, sin interpretar — ${shown.length > 0 ? shown.join("; ") : "sin datos"}`;
}

/** Una relación del análisis del BOE, verbatim. */
export function relationText(relation: NationalRelation): string {
  return `${relation.relation} ${relation.text} (${relation.id_norma})`.replace(/\s+/g, " ").trim();
}

export function titleOf(anchor: NationalAnchor | null): string | null {
  return text(anchor?.source_metadata, "titulo");
}

export function eliOf(anchor: NationalAnchor | null): string | null {
  return text(anchor?.source_metadata, "url_eli");
}

/** El aviso y la atribución de una norma: los de la API, o el respaldo. Siempre hay. */
export function noticesOf(item: Pick<NationalTransposition, "notice" | "attribution">): {
  notice: string;
  attribution: string;
} {
  return { notice: item.notice || BOE_NOTICE, attribution: item.attribution || BOE_ATTRIBUTION };
}

export function isOk(assessment: NationalAssessment | null): boolean {
  return assessment?.ok === true;
}

/** Cuántas de las normas declaradas de un requisito bloquean el `PASS` todavía. */
export function pendingCount(items: readonly NationalTransposition[]): number {
  return items.filter((item) => !isOk(item.assessment)).length;
}

/** La línea que dice qué falta para que una directiva pueda dar `PASS`. */
export function transpositionRule(items: readonly NationalTransposition[]): string {
  if (items.length === 0) {
    return "Es una directiva y no hay transposición nacional estructurada declarada y verificada: mientras falte, no se puede concluir PASS. El texto libre es solo una declaración humana.";
  }
  const pending = pendingCount(items);
  if (pending === 0) {
    return "La transposición está declarada, verificada en el BOE y corroborada por su análisis. Para PASS falta además la evidencia de cumplimiento del producto.";
  }
  return `${pending} de ${items.length} normas declaradas aún no están verificadas y corroboradas: mientras tanto, no se puede concluir PASS.`;
}
