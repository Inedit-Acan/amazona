import assert from "node:assert/strict";
import { test } from "node:test";
import type { NationalAnchor, NationalTransposition } from "./api.ts";
import {
  BOE_ATTRIBUTION,
  BOE_NOTICE,
  corroborationLabel,
  isDirectiveCelex,
  eliOf,
  nationalIdPayload,
  nationalIdProblems,
  nationalStateInfo,
  nationalStateNote,
  noticesOf,
  pendingCount,
  publicationLabel,
  relationText,
  sourceDatesText,
  titleOf,
  transpositionRule,
} from "./national-transposition.ts";

function anchor(overrides: Partial<NationalAnchor> = {}): NationalAnchor {
  return {
    national_id: "BOE-A-2011-14252",
    provider: "boe-open-data",
    provenance: "third_party_verified",
    verified_at: "2026-09-30T10:00:00+00:00",
    recheck_after: "2026-10-30T10:00:00+00:00",
    consolidated: true,
    informational: true,
    notice: BOE_NOTICE,
    attribution: BOE_ATTRIBUTION,
    source_metadata: {
      titulo: "Real Decreto 1205/2011, de 26 de agosto, sobre la seguridad de los juguetes.",
      fecha_publicacion: "20110831",
      fecha_vigencia: "20110901",
      url_eli: "https://www.boe.es/eli/es/rd/2011/08/26/1205",
    },
    source_updated_at: "20260828T103540Z",
    relations: null,
    publication_state: "confirmed",
    publication_detail: null,
    publication_url: null,
    source_urls: null,
    ...overrides,
  };
}

function item(ok: boolean): NationalTransposition {
  return {
    id: "t-1",
    requirement_id: "r-1",
    national_id: "BOE-A-2011-14252",
    provenance: "declared",
    declared_by: "owner",
    note: null,
    created_at: "2026-09-30T10:00:00+00:00",
    official_url: "https://www.boe.es/buscar/doc.php?id=BOE-A-2011-14252",
    notice: BOE_NOTICE,
    attribution: BOE_ATTRIBUTION,
    anchor: null,
    assessment: {
      state: ok ? "verified_in_force" : "never_checked",
      corroboration: ok ? "corroborated" : "not_assessable",
      corroboration_reason: "",
      ok,
      reasons: [],
      matching_relations: [],
      flagged_relations: [],
    },
  };
}

test("un identificador del BOE se valida y se normaliza; el nombre de la norma no vale", () => {
  assert.deepEqual(nationalIdProblems("BOE-A-2011-14252"), []);
  assert.deepEqual(nationalIdProblems(" boe-a-2011-14252 "), []);
  assert.equal(nationalIdProblems("").length, 1);
  assert.equal(nationalIdProblems("Real Decreto 1205/2011").length, 1);
  assert.equal(nationalIdProblems("DOUE-L-2009-81173").length, 1);
  assert.deepEqual(nationalIdPayload(" boe-a-2011-14252 ", "  RD juguetes "), {
    national_id: "BOE-A-2011-14252",
    note: "RD juguetes",
  });
  assert.equal(nationalIdPayload("BOE-A-2011-14252", "  ").note, null);
});

test("solo una directiva se traspone, y se decide por el CELEX y no por lo que diga EUR-Lex", () => {
  assert.equal(isDirectiveCelex("32009L0048"), true);
  assert.equal(isDirectiveCelex(" 32014l0035 "), true);
  assert.equal(isDirectiveCelex("32023R0988"), false);
  assert.equal(isDirectiveCelex(""), false);
});

test("las fechas de la fuente se enseñan tal cual, en su formato, sin interpretarlas", () => {
  const line = sourceDatesText(anchor());
  assert.match(line, /sin interpretar/);
  assert.match(line, /publicación: 20110831/);
  assert.match(line, /entrada en vigor: 20110901/);
  assert.match(line, /actualización de la fuente: 20260828T103540Z/);
  assert.doesNotMatch(line, /derogación/);
});

test("una fecha de derogación de la fuente se conserva aunque sea futura: no se compara con hoy", () => {
  const line = sourceDatesText(anchor({ source_metadata: { fecha_derogacion: "29990101" } }));
  assert.match(line, /derogación: 29990101/);
});

test("sin comprobación no se inventan fechas", () => {
  assert.match(sourceDatesText(null), /sin datos/);
});

test("un 404 nunca se cuenta como «la norma no existe»", () => {
  assert.match(nationalStateInfo("not_consolidated").label, /no la tiene consolidada/);
  assert.match(nationalStateNote("not_consolidated") ?? "", /no dice que la norma no exista/);
});

test("comprobación vencida y nunca comprobada dejan claro que es política nuestra, no jurídica", () => {
  assert.match(nationalStateNote("stale") ?? "", /No significa que la norma haya dejado de estar en vigor/);
  assert.match(nationalStateNote("never_checked") ?? "", /Nadie ha preguntado/);
});

test("las relaciones de anulación o suspensión se muestran sin interpretar su efecto", () => {
  assert.match(nationalStateNote("relation_flagged") ?? "", /no se interpreta/);
  assert.equal(
    relationText({ id_norma: "BOE-A-2030-1", relation_code: 231, relation: "SUSPENDE", text: "el art. 3" }),
    "SUSPENDE el art. 3 (BOE-A-2030-1)",
  );
});

test("un fallo de la comprobación de publicación no se presenta como «no está publicada»", () => {
  assert.match(publicationLabel("check_failed"), /no significa que no esté publicada/);
  assert.match(publicationLabel("absent_from_summary"), /no la lista/);
  assert.match(publicationLabel("not_checked"), /solo es oficial el papel/);
});

test("la corroboración dice lo que el BOE dice y nada más", () => {
  assert.match(corroborationLabel("corroborated"), /426 TRANSPONE/);
  assert.match(corroborationLabel("partial"), /parcialmente/);
  assert.match(corroborationLabel("not_assessable"), /No evaluable/);
  assert.match(corroborationLabel("not_assessable"), /inequívoca/);
});

test("el aviso de texto informativo y la atribución están siempre, también si la API no los diera", () => {
  const empty = noticesOf({ notice: "", attribution: "" });
  assert.equal(empty.notice, BOE_NOTICE);
  assert.equal(empty.attribution, BOE_ATTRIBUTION);
  assert.match(BOE_NOTICE, /meramente informativo/);
  assert.match(BOE_NOTICE, /publicación oficial/);
  assert.equal(BOE_ATTRIBUTION, "Basado en datos de la Agencia Estatal Boletín Oficial del Estado");
});

test("título y ELI salen de los metadatos de la fuente, no se inventan", () => {
  assert.match(titleOf(anchor()) ?? "", /Real Decreto 1205\/2011/);
  assert.equal(eliOf(anchor()), "https://www.boe.es/eli/es/rd/2011/08/26/1205");
  assert.equal(titleOf(null), null);
  assert.equal(eliOf(anchor({ source_metadata: null })), null);
});

test("la regla de PASS dice qué falta: transposición estructurada, verificada y corroborada", () => {
  assert.match(transpositionRule([]), /no se puede concluir PASS/);
  assert.match(transpositionRule([]), /texto libre es solo una declaración humana/);
  assert.match(transpositionRule([item(false)]), /1 de 1 normas declaradas aún no están verificadas/);
  assert.match(transpositionRule([item(true)]), /Para PASS falta además la evidencia de cumplimiento/);
  assert.equal(pendingCount([item(true), item(false)]), 1);
});
