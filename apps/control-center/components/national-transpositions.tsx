"use client";

import { useState } from "react";
import { OPERATIONS } from "@/lib/intent-operations";
import { useIntent } from "@/lib/use-intent";
import { useRouter } from "next/navigation";
import { Loader2, Plus, RefreshCw } from "lucide-react";
import { ApiError, api, type RegulatoryRequirement } from "@/lib/api";
import {
  BOE_ATTRIBUTION,
  BOE_SITE,
  corroborationLabel,
  eliOf,
  nationalIdPayload,
  nationalIdProblems,
  nationalStateInfo,
  nationalStateNote,
  noticesOf,
  publicationLabel,
  relationText,
  sourceDatesText,
  titleOf,
  transpositionRule,
} from "@/lib/national-transposition";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

const FIELD_CLASS =
  "w-full min-w-0 rounded-md border bg-background/60 px-2.5 py-1.5 text-sm outline-none focus-visible:border-ring";

/** Transposición nacional de una directiva (Milestone 43, ADR 0021).
 *
 * La norma española la **declara una persona**: esta pantalla no la propone ni la busca.
 * El BOE solo la verifica y la ancla. Y todo dato suyo lleva, siempre, el aviso de que la
 * consolidación y el análisis son meramente informativos, y su atribución. */
export function NationalTranspositions({ requirement }: { requirement: RegulatoryRequirement }) {
  const router = useRouter();
  const items = requirement.national_transpositions ?? [];
  const [open, setOpen] = useState(false);
  const [nationalId, setNationalId] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const intent = useIntent("transposition");
  const [error, setError] = useState<string | null>(null);
  const problems = nationalIdProblems(nationalId);

  async function act(key: string, work: () => Promise<unknown>, failure: string) {
    setBusy(key);
    setError(null);
    try {
      await work();
      router.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : failure);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-2 rounded-md border border-dashed p-2">
      <p className="text-[11px] uppercase text-muted-foreground">Transposición nacional (BOE)</p>
      <p className="text-xs text-warning">{transpositionRule(items)}</p>
      {requirement.transposition_reference ? (
        <p className="text-xs text-muted-foreground">
          Declaración humana en texto libre: «{requirement.transposition_reference}». Se conserva como pista de
          auditoría; no basta para PASS.
        </p>
      ) : null}

      {items.map((item) => {
        const assessment = item.assessment;
        const state = assessment ? nationalStateInfo(assessment.state) : null;
        const stateNote = assessment ? nationalStateNote(assessment.state) : null;
        const anchor = item.anchor;
        const eli = eliOf(anchor);
        const { notice, attribution } = noticesOf(item);
        return (
          <div key={item.id} className="space-y-1.5 rounded-md bg-muted/40 p-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-medium">
                <span className="font-mono text-xs">{item.national_id}</span>
                {titleOf(anchor) ? <span className="ml-2 text-muted-foreground">{titleOf(anchor)}</span> : null}
              </span>
              <Badge variant="outline">Informativo</Badge>
            </div>
            <dl className="grid gap-1.5 sm:grid-cols-3">
              <div>
                <dt className="text-[11px] uppercase text-muted-foreground">Norma declarada</dt>
                <dd>Declarada por {item.declared_by}</dd>
              </div>
              <div>
                <dt className="text-[11px] uppercase text-muted-foreground">Estado según el BOE</dt>
                <dd>{state ? state.label : "Sin evaluar"}</dd>
              </div>
              <div>
                <dt className="text-[11px] uppercase text-muted-foreground">Relación con la norma UE</dt>
                <dd>{assessment ? corroborationLabel(assessment.corroboration) : "Sin evaluar"}</dd>
              </div>
            </dl>
            {assessment?.matching_relations.map((relation) => (
              <p key={relation.id_norma + relation.relation_code} className="text-xs text-muted-foreground">
                El BOE dice: {relationText(relation)}
              </p>
            ))}
            {assessment?.flagged_relations.map((relation) => (
              <p key={relation.id_norma + relation.relation_code} className="text-xs text-warning">
                Relación a revisar, tal como la da el BOE: {relationText(relation)}
              </p>
            ))}
            {anchor ? (
              <p className="text-xs text-muted-foreground">
                {sourceDatesText(anchor)} · publicación oficial: {publicationLabel(anchor.publication_state)} ·
                comprobada el {anchor.verified_at.slice(0, 10)}, volver a comprobar tras el{" "}
                {anchor.recheck_after.slice(0, 10)}
              </p>
            ) : null}
            {stateNote ? <p className="text-xs text-muted-foreground">{stateNote}</p> : null}
            {assessment && assessment.reasons.length > 0 ? (
              <ul className="list-disc space-y-0.5 pl-4 text-xs text-warning">
                {assessment.reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            ) : null}
            <p className="text-[11px] text-muted-foreground">
              {notice}{" "}
              <a className="underline" href={item.official_url} target="_blank" rel="noreferrer">
                Publicación oficial
              </a>
              {eli ? (
                <>
                  {" · "}
                  <a className="underline" href={eli} target="_blank" rel="noreferrer">
                    ELI
                  </a>
                </>
              ) : null}
              {" · "}
              {attribution === BOE_ATTRIBUTION ? (
                <a className="underline" href={BOE_SITE} target="_blank" rel="noreferrer">
                  {attribution}
                </a>
              ) : (
                attribution
              )}
            </p>
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={busy !== null}
                onClick={() =>
                  void act(`verify:${item.id}`, () =>
                      intent.run(
                        { operation: OPERATIONS.transpositionVerify, target: item.id, params: {} },
                        (key) => api.verifyNationalTransposition(item.id, { idempotencyKey: key }),
                      ), "No se pudo comprobar en el BOE.")
                }
              >
                {busy === `verify:${item.id}` ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
                Comprobar en el BOE
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={busy !== null}
                onClick={() =>
                  void act(`withdraw:${item.id}`, () => api.withdrawNationalTransposition(item.id), "No se pudo retirar.")
                }
              >
                Retirar
              </Button>
            </div>
          </div>
        );
      })}

      {!open ? (
        <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
          <Plus className="size-3.5" />
          Declarar una norma nacional
        </Button>
      ) : (
        <div className="grid gap-2 sm:grid-cols-2">
          <label className="space-y-1">
            <span className="text-[11px] text-muted-foreground">Identificador en el BOE</span>
            <input
              className={FIELD_CLASS}
              placeholder="BOE-A-2011-14252"
              value={nationalId}
              onChange={(e) => setNationalId(e.target.value)}
            />
          </label>
          <label className="space-y-1">
            <span className="text-[11px] text-muted-foreground">Nota (opcional)</span>
            <input className={FIELD_CLASS} value={note} onChange={(e) => setNote(e.target.value)} />
          </label>
          {nationalId !== "" && problems.map((message) => (
            <p key={message} className="text-xs text-warning sm:col-span-2">
              {message}
            </p>
          ))}
          <p className="text-[11px] text-muted-foreground sm:col-span-2">
            Lo declara una persona: el sistema no busca ni propone qué norma española traspone la directiva. El BOE solo
            la verifica.
          </p>
          <div className="sm:col-span-2">
            <Button
              size="sm"
              disabled={busy !== null || problems.length > 0}
              onClick={() =>
                void act(
                  `declare:${requirement.id}`,
                  async () => {
                    await api.declareNationalTransposition(requirement.id, nationalIdPayload(nationalId, note));
                    setNationalId("");
                    setNote("");
                    setOpen(false);
                  },
                  "No se pudo declarar la norma.",
                )
              }
            >
              Declarar
            </Button>
          </div>
        </div>
      )}

      {error ? (
        <Alert variant="destructive">
          <AlertTitle>No se pudo completar</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
    </div>
  );
}
