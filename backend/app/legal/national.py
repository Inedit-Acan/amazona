"""Transposiciones nacionales declaradas, ancladas en el BOE
(Milestone 43, ADR 0021). Dominio puro, sin base de datos ni red.

## La regla que lo gobierna

**El sistema no infiere qué norma española traspone una directiva ni qué norma se
aplica a un producto.** Una persona declara la relación —«el Real Decreto 1205/2011
traspone la Directiva 2009/48/CE»— y la fuente solo la **verifica y la ancla**:
¿existe esa norma consolidada?, ¿está en vigor según la fuente?, ¿el análisis del
BOE dice él mismo que la traspone?

## Cuatro capas que no se rellenan una con otra

| Capa | Quién la sostiene | Valor |
|---|---|---|
| Norma declarada | Una persona | `declared` |
| Publicación oficial | El sumario del diario del BOE | Oficial; comprobación **auxiliar** |
| Texto consolidado, análisis y metadatos | La AEBOE | **Meramente informativos**, sin valor oficial |
| Evidencia de cumplimiento del producto | Una persona o el emisor | `compliance_evidence` (M41) |

Y `PASS` no depende nunca solo del texto consolidado: exige además evidencia de
cumplimiento, y la corroboración de la transposición es de un análisis que la
propia fuente califica de informativo (techo de confianza 0,7).

## Corroboración: comparación determinista o nada

La relación `426 TRANSPONE` (o `427 TRANSPONE parcialmente`) de una norma del BOE
nombra la directiva en texto: «la Directiva 2009/48/CE, de 18 de junio de 2009». La
comparación con el CELEX declarado (`32009L0048`) solo se hace si **año y número**
se leen sin ambigüedad. Si no, es `not_assessable`. **Nada de similitud textual,
nada de fuzzy matching, nada de un LLM.**

## Lo que NO se interpreta

Las fechas de la fuente (`fecha_vigencia`, `fecha_derogacion`…) se conservan como
cadenas `AAAAMMDD` y **no se comparan con hoy**. Las banderas `S`/`N` de derogación,
anulación y vigencia agotada se leen tal cual. Las relaciones de anulación o
suspensión se muestran y piden revisión, **sin decidir su efecto jurídico**.
"""

import datetime
import re
from dataclasses import dataclass, field
from enum import StrEnum

from app.core.errors import ValidationError

PROVIDER_NAME = "boe-open-data"

#: Lo que la licencia y las FAQ de la AEBOE exigen mostrar junto a cualquier dato
#: de legislación consolidada o de su análisis (aviso legal, condiciones de
#: reutilización 4.ª.3 y 4.ª.2.b; FAQ de la API consolidada; leídos el 29-09-2026).
NOTICE = (
    "Texto consolidado de carácter meramente informativo. Para fines jurídicos debe "
    "consultarse la publicación oficial."
)
ATTRIBUTION = "Basado en datos de la Agencia Estatal Boletín Oficial del Estado"
OFFICIAL_SITE = "https://www.boe.es"

#: Techo de confianza de lo que descansa en datos informativos del BOE. **Regla
#: interna, no calibrada**: entre EUR-Lex (0,8) y lo declarado (0,6), porque la
#: propia fuente dice que la consolidación y el análisis son informativos y pueden
#: ir con retraso.
INFORMATIONAL_CONFIDENCE_CEILING = 0.7

CODE_TRANSPOSES = 426
CODE_TRANSPOSES_PARTIALLY = 427
#: ANULA, ANULA las ediciones anteriores, DEJA SIN EFECTO y SUSPENDE. Se muestran y
#: piden revisión; **su efecto jurídico no se interpreta**.
FLAGGED_RELATION_CODES = frozenset({220, 221, 230, 231})

NATIONAL_ID_PATTERN = re.compile(r"^BOE-[A-Z]-\d{4}-\d{1,6}$")
_CELEX_DIRECTIVE = re.compile(r"^3(\d{4})L(\d{4})$")
#: `Directiva 2009/48/CE`, `Directiva (UE) 2015/1535`, `Directiva 73/23/CEE`. El año
#: va primero en las directivas; con dos cifras solo hay una lectura posible.
_DESIGNATION = re.compile(
    r"\bDirectiva\b(?:\s*\((?:UE|CE|CEE|EU|Euratom)\))?\s+(?:n\.?\s?º\s*)?(\d{2,4})\s*/\s*(\d{1,4})",
    re.IGNORECASE,
)
#: Cualquier número de acto de la UE con su sufijo, esté o no precedido de la palabra
#: «Directiva»: `2014/35/UE`, `(UE) 2015/1535`, `(CE) 765/2008`. Sirve para detectar que
#: un texto nombra **más** actos de los que se atribuyeron a una directiva, en cuyo caso
#: no se compara.
_ANY_EU_NUMBER = re.compile(
    r"(?<!\d)(\d{2,4})\s*/\s*(\d{1,4})\s*/\s*(?:CE|CEE|UE|EU|CEEA|Euratom)(?![A-Za-z])"
    r"|\((?:UE|CE|CEE|EU|Euratom)\)\s*(?:n\.?\s?º\s*)?(\d{2,4})\s*/\s*(\d{1,4})",
    re.IGNORECASE,
)
#: El Tratado de Roma es de 1957: una directiva con año de dos cifras menor que 57
#: no tiene lectura inequívoca, y no se adivina.
_FIRST_TWO_DIGIT_YEAR = 57


class NationalState(StrEnum):
    """Lo que la fuente dice de la norma nacional. Independiente de la
    aplicabilidad y de la corroboración."""

    VERIFIED_IN_FORCE = "verified_in_force"
    NOT_IN_FORCE = "not_in_force"
    #: La fuente respondió que no la tiene **consolidada**. No dice que no exista.
    NOT_CONSOLIDATED = "not_consolidated"
    OUTDATED_CONSOLIDATION = "outdated_consolidation"
    #: La fuente no dio banderas o estado de consolidación legibles.
    UNVERIFIED = "unverified"
    RELATION_FLAGGED = "relation_flagged"
    #: Los metadatos dan una fecha de publicación y el sumario de ese día, leído
    #: bien, no lista la norma. Es la única respuesta negativa sobre publicación.
    PUBLICATION_INCONSISTENT = "publication_inconsistent"
    #: Hubo comprobación, pero venció **nuestra** política de recomprobación. No
    #: dice que la norma haya dejado de estar en vigor.
    STALE = "stale"
    NEVER_CHECKED = "never_checked"


class Corroboration(StrEnum):
    #: El análisis del BOE dice `426 TRANSPONE` a esa directiva, y año y número se
    #: leyeron sin ambigüedad.
    CORROBORATED = "corroborated"
    #: Dice `427 TRANSPONE parcialmente`: no basta.
    PARTIAL = "partial"
    #: El análisis se leyó y no dice que traspone esa directiva.
    UNCORROBORATED = "uncorroborated"
    #: Hay relaciones de transposición cuyo texto no se puede leer sin ambigüedad, o
    #: no hay análisis con el que comparar. **No es una contradicción.**
    NOT_ASSESSABLE = "not_assessable"


def validate_national_id(national_id: str) -> str:
    """Un identificador del BOE, o falla **antes** de llamar a nadie. Se declara,
    no se busca: no hay búsqueda por título ni por materia."""
    cleaned = national_id.strip().upper()
    if not NATIONAL_ID_PATTERN.fullmatch(cleaned):
        raise ValidationError(
            f"{national_id!r} is not a BOE identifier (expected like BOE-A-2011-14252)"
        )
    return cleaned


def official_url(national_id: str) -> str:
    """El enlace oficial estable a la disposición, construido del identificador."""
    return f"{OFFICIAL_SITE}/buscar/doc.php?id={national_id}"


def directive_key(celex: str) -> tuple[int, int] | None:
    """Año y número de una directiva a partir de su CELEX (`32009L0048` → 2009, 48).

    `None` si no es una directiva: solo se traspone una directiva.
    """
    match = _CELEX_DIRECTIVE.fullmatch(celex.strip().upper())
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def _normalise_year(year_raw: str) -> int | None:
    year = int(year_raw)
    if len(year_raw) == 2:
        return year + 1900 if year >= _FIRST_TWO_DIGIT_YEAR else None
    return year


def designations_in(text: str) -> tuple[frozenset[tuple[int, int]], bool]:
    """Las directivas que nombra un texto, como `(año, número)`, y si el texto es
    ambiguo: alguna no se pudo leer sin ambigüedad, o el texto nombra **otros** actos
    de la UE que no se atribuyeron a una directiva.

    Determinista: expresiones regulares sobre la forma en que la UE numera sus actos.
    No compara títulos ni palabras.
    """
    found: set[tuple[int, int]] = set()
    ambiguous = False
    for year_raw, number_raw in _DESIGNATION.findall(text or ""):
        year = _normalise_year(year_raw)
        if year is None:
            ambiguous = True
            continue
        found.add((year, int(number_raw)))
    for groups in _ANY_EU_NUMBER.findall(text or ""):
        year_raw = groups[0] or groups[2]
        number_raw = groups[1] or groups[3]
        year = _normalise_year(year_raw)
        if year is None or (year, int(number_raw)) not in found:
            ambiguous = True
    return frozenset(found), ambiguous


@dataclass(frozen=True)
class CorroborationResult:
    state: Corroboration
    #: Las relaciones de la fuente que coinciden, **tal como la fuente las dio**.
    matching: tuple[dict[str, object], ...] = ()
    reason: str = ""


def corroborate(previous: list[dict[str, object]], celex: str) -> CorroborationResult:
    """¿Dice el análisis del BOE que esta norma traspone la directiva declarada?"""
    key = directive_key(celex)
    if key is None:
        return CorroborationResult(
            Corroboration.NOT_ASSESSABLE,
            reason="the declared EU act is not a directive, so there is nothing to transpose",
        )
    full: list[dict[str, object]] = []
    partial: list[dict[str, object]] = []
    unreadable = 0
    for relation in previous:
        code = relation.get("relation_code")
        if code not in (CODE_TRANSPOSES, CODE_TRANSPOSES_PARTIALLY):
            continue
        designations, ambiguous = designations_in(str(relation.get("text") or ""))
        if ambiguous or len(designations) != 1:
            unreadable += 1
            continue
        if key in designations:
            (full if code == CODE_TRANSPOSES else partial).append(relation)
    if partial:
        return CorroborationResult(
            Corroboration.PARTIAL,
            tuple(partial),
            "the source says the norm partially transposes this directive",
        )
    if full:
        return CorroborationResult(Corroboration.CORROBORATED, tuple(full))
    if unreadable:
        return CorroborationResult(
            Corroboration.NOT_ASSESSABLE,
            reason=(
                "the source lists a transposition relation whose text cannot be read "
                "unambiguously as a directive year and number: it is not compared"
            ),
        )
    return CorroborationResult(
        Corroboration.UNCORROBORATED,
        reason="the source's analysis does not say this norm transposes the declared directive",
    )


@dataclass(frozen=True)
class NationalAnchorState:
    """Lo que la fuente dijo de una norma nacional en una comprobación concreta."""

    national_id: str
    verified_at: datetime.datetime
    #: Política operativa nuestra, no un plazo jurídico.
    recheck_after: datetime.datetime
    consolidated: bool
    metadata: dict[str, object]
    relations: dict[str, list[dict[str, object]]]
    publication_state: str
    provider: str = PROVIDER_NAME
    source_urls: tuple[str, ...] = ()


@dataclass(frozen=True)
class TranspositionAssessment:
    """Una transposición declarada, evaluada. Las capas salen separadas."""

    national_id: str
    state: NationalState
    corroboration: Corroboration
    reasons: tuple[str, ...]
    anchor: NationalAnchorState | None = None
    corroboration_reason: str = ""
    matching_relations: tuple[dict[str, object], ...] = ()
    flagged_relations: tuple[dict[str, object], ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        """Solo esta combinación deja pasar a la evidencia de cumplimiento."""
        return (
            self.state is NationalState.VERIFIED_IN_FORCE
            and self.corroboration is Corroboration.CORROBORATED
        )


def _flag(metadata: dict[str, object], key: str) -> str | None:
    value = metadata.get(key)
    return value if value in ("S", "N") else None


def _consolidation_code(metadata: dict[str, object]) -> str | None:
    raw = metadata.get("estado_consolidacion")
    if isinstance(raw, dict):
        code = raw.get("codigo")
        return str(code) if code is not None else None
    return None


def assess_transposition(
    national_id: str,
    anchor: NationalAnchorState | None,
    celex: str,
    now: datetime.datetime,
) -> TranspositionAssessment:
    if anchor is None:
        return TranspositionAssessment(
            national_id,
            NationalState.NEVER_CHECKED,
            Corroboration.NOT_ASSESSABLE,
            ("the national norm has never been checked against the source",),
        )
    if now > anchor.recheck_after:
        return TranspositionAssessment(
            national_id,
            NationalState.STALE,
            Corroboration.NOT_ASSESSABLE,
            (
                "the last check is older than the internal recheck policy; this is not a "
                "statement that the norm stopped being in force",
            ),
            anchor,
        )
    if not anchor.consolidated:
        return TranspositionAssessment(
            national_id,
            NationalState.NOT_CONSOLIDATED,
            Corroboration.NOT_ASSESSABLE,
            (
                "the source has no consolidated version of this identifier. That does not "
                "say the norm does not exist: it may simply not be in the collection",
            ),
            anchor,
        )

    corroboration = corroborate(anchor.relations.get("previous", []), celex)
    flagged = tuple(
        relation
        for relation in anchor.relations.get("next", [])
        if relation.get("relation_code") in FLAGGED_RELATION_CODES
    )
    common = {
        "corroboration": corroboration.state,
        "corroboration_reason": corroboration.reason,
        "matching_relations": corroboration.matching,
        "flagged_relations": flagged,
        "anchor": anchor,
    }

    def result(state: NationalState, *reasons: str) -> TranspositionAssessment:
        return TranspositionAssessment(national_id, state, reasons=tuple(reasons), **common)  # type: ignore[arg-type]

    flags = {
        key: _flag(anchor.metadata, key)
        for key in ("estatus_derogacion", "estatus_anulacion", "vigencia_agotada")
    }
    if any(value == "S" for value in flags.values()):
        return result(
            NationalState.NOT_IN_FORCE,
            "the source flags this norm as repealed, annulled or with its validity exhausted: "
            "the declaration may be outdated",
        )
    consolidation = _consolidation_code(anchor.metadata)
    if any(value is None for value in flags.values()) or consolidation not in ("3", "4"):
        return result(
            NationalState.UNVERIFIED,
            "the source did not give readable status flags or consolidation state",
        )
    if consolidation == "4":
        return result(
            NationalState.OUTDATED_CONSOLIDATION,
            "the consolidated version is marked outdated: a later amendment is not yet "
            "incorporated, so its status may lag by a few days",
        )
    if flagged:
        return result(
            NationalState.RELATION_FLAGGED,
            "the source lists annulment or suspension relations for this norm. Their legal "
            "effect is not interpreted here: a person must read them",
        )
    if anchor.publication_state == "absent_from_summary":
        return result(
            NationalState.PUBLICATION_INCONSISTENT,
            "the metadata give a publication date but that day's official summary, read "
            "correctly, does not list this identifier",
        )
    return result(NationalState.VERIFIED_IN_FORCE)
