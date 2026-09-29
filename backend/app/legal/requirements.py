"""Requisitos legales con procedencia, y cuándo se puede decir que no hay bloqueo
(Milestone 41, ADR 0019).

El plan maestro §12 pide que Legal deje de ser un fixture. La tentación es que
una fuente pública de normativa diga «este producto necesita CE». **Ninguna lo
dice**: EUR-Lex publica el texto y la vigencia de una norma; que esa norma se
aplique a *este* producto es un juicio jurídico que no está en ninguna base de
datos. Este módulo existe para no confundir tres cosas que suelen viajar juntas:

1. **Aplicabilidad** — «esta norma se aplica a esta clase de producto en esta
   jurisdicción». La **declara una persona**. Nadie más: ni la fuente, ni una
   heurística, ni un modelo de lenguaje.
2. **Existencia y vigencia** — «esta norma existe y, según la fuente, está en
   vigor». La **verifica un tercero** (EUR-Lex), sobre una norma que **nosotros
   hemos nombrado**.
3. **Evidencia de cumplimiento** — «este producto cumple: aquí está el
   certificado». La aporta una persona, con su emisor si lo emitió un tercero.

Cada una tiene su procedencia (`SupplierFactProvenance`, ADR 0017) y ninguna se
rellena con otra. Que falte una es un hueco visible, nunca un valor por defecto.

## Los cuatro estados, y lo que NO significan

- `PASS`: **dentro del alcance y de los requisitos declarados y comprobados,
  Legal no ha encontrado un bloqueo.** No significa «producto legal» ni
  «cumplimiento completo»: significa que lo que alguien declaró está comprobado
  y cubierto. Lo que nadie declaró, no se ha mirado.
- `REVIEW_REQUIRED`: hay algo que una persona debe resolver antes de concluir.
- `BLOCKED`: un requisito de tipo restricción, con norma verificada y vigente y
  sin evidencia de cumplimiento.
- `UNKNOWN`: no hay nada declarado para este alcance y jurisdicción. **Ausencia
  de requisitos declarados no es ausencia de requisitos**, así que `UNKNOWN`
  jamás asciende a `PASS`.

`UNKNOWN` y `REVIEW_REQUIRED` salen como `REVIEW` hacia el ActionGate, nunca como
`NO_GO`: el gate veta los `NO_GO` que gastan, y «no se pudo comprobar» no es un
resultado negativo (ADR 0018).

## La confianza

Cada eslabón tiene un **techo** según quién lo sostiene, y la confianza de un
resultado es el techo de su eslabón más débil. Son **reglas internas de AMAZONA,
no calibradas**: no salen de ninguna medición, solo impiden que un dato declarado
parezca tan sólido como uno emitido por un tercero. Construir una evaluación que
supere su techo falla. No hay ningún score adicional.
"""

import datetime
from dataclasses import dataclass, field
from enum import StrEnum

from app.core.errors import ValidationError
from app.sourcing.provenance import MissingVerifierError, SupplierFactProvenance

#: Quién puede sostener un hecho legal. `SIMULATED` es del mock y no pasa por
#: aquí; `AMAZONA_ESTIMATE` no tiene sentido: nadie estima una norma.
LEGAL_PROVENANCES = frozenset(
    {SupplierFactProvenance.DECLARED, SupplierFactProvenance.THIRD_PARTY_VERIFIED}
)

#: Techo de confianza por procedencia. **Regla interna, no calibrada.** 0,8 y no
#: 1,0 porque ni un tercero convierte un resultado legal en certeza; 0,6 para lo
#: declarado porque una persona puede equivocarse o estar desactualizada.
LEGAL_CONFIDENCE_CEILING: dict[SupplierFactProvenance, float] = {
    SupplierFactProvenance.THIRD_PARTY_VERIFIED: 0.8,
    SupplierFactProvenance.DECLARED: 0.6,
    SupplierFactProvenance.AMAZONA_ESTIMATE: 0.5,
    SupplierFactProvenance.SIMULATED: 0.4,
}

#: Lo que el agente simulado ya emitía cuando no tenía datos suficientes. Se
#: reutiliza para el mismo caso —`UNKNOWN`— en vez de inventar otro número: no es
#: una medición, es la constante con la que el sistema ya decía «no sé».
INSUFFICIENT_DATA_CONFIDENCE = 0.3

#: Jurisdicción que esta fuente puede anclar. EUR-Lex publica Derecho de la UE y
#: nada más: cualquier otra jurisdicción es `UNKNOWN`, no «sin requisitos».
SUPPORTED_JURISDICTION = "eu"


class LegalStatus(StrEnum):
    PASS = "PASS"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


#: Lo que entiende el ActionGate (`legal_recommendation`). `PASS` → `GO` no
#: levanta ningún otro gate: presupuesto, permisos y aprobación humana siguen.
RECOMMENDATION_FOR: dict[LegalStatus, str] = {
    LegalStatus.PASS: "GO",
    LegalStatus.REVIEW_REQUIRED: "REVIEW",
    LegalStatus.UNKNOWN: "REVIEW",
    LegalStatus.BLOCKED: "NO_GO",
}


class RequirementKind(StrEnum):
    #: Hay que demostrar el cumplimiento. Sin evidencia → revisar.
    OBLIGATION = "obligation"
    #: El producto no puede ponerse en el mercado sin evidencia. Sin ella y con
    #: la norma verificada → bloqueo.
    RESTRICTION = "restriction"


class ActType(StrEnum):
    """Tipo de acto, tal como lo clasifica la fuente."""

    REGULATION = "regulation"
    DIRECTIVE = "directive"
    #: Cualquier otro código de la fuente: no se sabe si es directamente
    #: aplicable, y no se supone.
    OTHER = "other"
    UNKNOWN = "unknown"


class Existence(StrEnum):
    """Lo que la fuente dice de la norma. Independiente de la aplicabilidad."""

    VERIFIED_IN_FORCE = "verified_in_force"
    VERIFIED_NOT_IN_FORCE = "verified_not_in_force"
    NOT_FOUND = "not_found"
    #: La fuente se contradice: dice «en vigor» y da un fin de validez ya pasado.
    SOURCE_INCONSISTENT = "source_inconsistent"
    #: La fuente no dijo si está en vigor.
    UNVERIFIED = "unverified"
    #: Hubo una comprobación, pero venció la política de recomprobación. **No
    #: significa que la norma haya dejado de estar en vigor**: significa que
    #: hace tiempo que nadie lo mira.
    STALE = "stale"
    #: Nunca se ha comprobado.
    NEVER_CHECKED = "never_checked"


class Compliance(StrEnum):
    NONE = "none"
    DECLARED = "declared"
    THIRD_PARTY_VERIFIED = "third_party_verified"
    #: Había evidencia, pero su vigencia terminó.
    EXPIRED = "expired"


@dataclass(frozen=True)
class DeclaredRequirement:
    """Una norma que una persona declara aplicable a un alcance de producto."""

    id: str
    product_scope: str
    jurisdiction: str
    celex: str
    regulation: str
    requirement: str
    kind: RequirementKind
    applicability_provenance: SupplierFactProvenance
    declared_by: str
    reference: str | None = None
    applicability_source: str | None = None
    #: Ley nacional que traspone una directiva. Declarada por una persona: no hay
    #: fuente de Derecho nacional en este milestone.
    transposition_reference: str | None = None
    transposition_provenance: SupplierFactProvenance | None = None
    transposition_source: str | None = None

    def __post_init__(self) -> None:
        check_provenance(self.applicability_provenance, self.applicability_source, "applicability")
        if not self.product_scope.strip():
            raise ValidationError("a regulatory requirement needs a declared product scope")
        if not self.declared_by.strip():
            raise ValidationError("a regulatory requirement needs to say who declared it")
        if self.transposition_reference:
            if self.transposition_provenance is None:
                raise ValidationError("a national transposition reference needs its provenance")
            check_provenance(
                self.transposition_provenance, self.transposition_source, "transposition"
            )


@dataclass(frozen=True)
class AnchorState:
    """Lo que la fuente dijo de una norma en una comprobación concreta."""

    found: bool
    in_force: bool | None
    act_type: ActType
    verified_at: datetime.datetime
    #: Política operativa nuestra, no un plazo jurídico de la norma.
    recheck_after: datetime.datetime
    source: str
    eli: str | None = None
    #: Fechas tal como las entrega la fuente. Se enseñan, **no se interpretan**:
    #: `entry_into_force` puede traer varias (entrada en vigor y aplicación) y
    #: elegir una sería una decisión jurídica.
    source_effective_from: tuple[str, ...] = ()
    source_effective_to: str | None = None


@dataclass(frozen=True)
class ComplianceEvidenceItem:
    provenance: SupplierFactProvenance
    declared_by: str
    source: str | None = None
    reference: str | None = None
    valid_until: datetime.date | None = None

    def __post_init__(self) -> None:
        check_provenance(self.provenance, self.source, "compliance evidence")


def check_provenance(
    provenance: SupplierFactProvenance, source: str | None, what: str
) -> None:
    """Quién sostiene un hecho legal, o falla al construirlo."""
    if provenance not in LEGAL_PROVENANCES:
        raise ValidationError(
            f"{what} can only be declared or third_party_verified, not {provenance.value}"
        )
    if provenance is SupplierFactProvenance.THIRD_PARTY_VERIFIED and not (source or "").strip():
        raise MissingVerifierError(
            f"{what} marked third_party_verified without saying who verified it"
        )


def existence_of(anchor: AnchorState | None, now: datetime.datetime) -> Existence:
    if anchor is None:
        return Existence.NEVER_CHECKED
    if now > anchor.recheck_after:
        return Existence.STALE
    if not anchor.found:
        return Existence.NOT_FOUND
    if anchor.in_force is None:
        return Existence.UNVERIFIED
    if anchor.in_force is False:
        return Existence.VERIFIED_NOT_IN_FORCE
    end = _parse_date(anchor.source_effective_to)
    if end is not None and end < now.date():
        return Existence.SOURCE_INCONSISTENT
    return Existence.VERIFIED_IN_FORCE


def _parse_date(raw: str | None) -> datetime.date | None:
    if not raw:
        return None
    try:
        return datetime.date.fromisoformat(raw[:10])
    except ValueError:
        return None


def compliance_of(
    evidence: list[ComplianceEvidenceItem], today: datetime.date
) -> tuple[Compliance, SupplierFactProvenance | None]:
    """La mejor evidencia vigente, y su procedencia."""
    valid = [e for e in evidence if e.valid_until is None or e.valid_until >= today]
    if not valid:
        return (Compliance.EXPIRED if evidence else Compliance.NONE), None
    if any(e.provenance is SupplierFactProvenance.THIRD_PARTY_VERIFIED for e in valid):
        return Compliance.THIRD_PARTY_VERIFIED, SupplierFactProvenance.THIRD_PARTY_VERIFIED
    return Compliance.DECLARED, SupplierFactProvenance.DECLARED


@dataclass(frozen=True)
class RequirementAssessment:
    """Un requisito evaluado, con las tres cuestiones **separadas**."""

    requirement: DeclaredRequirement
    status: LegalStatus
    reasons: tuple[str, ...]
    existence: Existence
    compliance: Compliance
    anchor: AnchorState | None
    confidence: float
    #: De qué eslabón sale el techo, para poder explicarlo.
    weakest_link: SupplierFactProvenance

    def __post_init__(self) -> None:
        ceiling = LEGAL_CONFIDENCE_CEILING[self.weakest_link]
        if self.confidence > ceiling:
            raise ValidationError(
                f"confidence {self.confidence} exceeds the ceiling {ceiling} for a result whose "
                f"weakest link is {self.weakest_link.value}"
            )


def _weakest_link(
    requirement: DeclaredRequirement,
    existence: Existence,
    compliance_provenance: SupplierFactProvenance | None,
) -> SupplierFactProvenance:
    links = [requirement.applicability_provenance]
    # Sin ancla verificada la existencia de la norma descansa en quien la
    # declaró: el eslabón es el de lo declarado.
    if existence is Existence.VERIFIED_IN_FORCE:
        links.append(SupplierFactProvenance.THIRD_PARTY_VERIFIED)
    else:
        links.append(SupplierFactProvenance.DECLARED)
    if compliance_provenance is not None:
        links.append(compliance_provenance)
    return min(links, key=lambda p: LEGAL_CONFIDENCE_CEILING[p])


_EXISTENCE_REASON = {
    Existence.NEVER_CHECKED: "the regulation has never been checked against the source",
    Existence.STALE: (
        "the last check is older than the internal recheck policy; this is not a statement "
        "that the regulation stopped being in force"
    ),
    Existence.NOT_FOUND: "the source has no act with this CELEX number: check the identifier",
    Existence.UNVERIFIED: "the source did not say whether the regulation is in force",
    Existence.VERIFIED_NOT_IN_FORCE: (
        "the source says the regulation is not in force: the declaration may be outdated"
    ),
    Existence.SOURCE_INCONSISTENT: (
        "the source says the regulation is in force but gives an end of validity already past"
    ),
}


def assess_requirement(
    requirement: DeclaredRequirement,
    anchor: AnchorState | None,
    evidence: list[ComplianceEvidenceItem],
    *,
    now: datetime.datetime,
) -> RequirementAssessment:
    existence = existence_of(anchor, now)
    compliance, compliance_provenance = compliance_of(evidence, now.date())
    weakest = _weakest_link(requirement, existence, compliance_provenance)
    ceiling = LEGAL_CONFIDENCE_CEILING[weakest]
    reasons: list[str] = []

    def result(status: LegalStatus) -> RequirementAssessment:
        return RequirementAssessment(
            requirement=requirement,
            status=status,
            reasons=tuple(reasons),
            existence=existence,
            compliance=compliance,
            anchor=anchor,
            confidence=ceiling,
            weakest_link=weakest,
        )

    if existence is not Existence.VERIFIED_IN_FORCE:
        reasons.append(_EXISTENCE_REASON[existence])
        return result(LegalStatus.REVIEW_REQUIRED)

    # Solo un acto directamente aplicable liga por sí mismo. Una directiva
    # verifica el acto de la UE, no la ley nacional que la traspone.
    assert anchor is not None
    if anchor.act_type is ActType.DIRECTIVE and not requirement.transposition_reference:
        reasons.append(
            "the act is a directive and no national transposition is declared: what binds is "
            "the national law, which this source does not cover, so PASS cannot be concluded"
        )
        return result(LegalStatus.REVIEW_REQUIRED)
    if anchor.act_type in (ActType.OTHER, ActType.UNKNOWN):
        reasons.append(
            "the source does not establish this act as directly applicable: a person must "
            "confirm how it binds"
        )
        return result(LegalStatus.REVIEW_REQUIRED)

    if compliance in (Compliance.NONE, Compliance.EXPIRED):
        what = "its evidence has expired" if compliance is Compliance.EXPIRED else "no compliance evidence"
        if requirement.kind is RequirementKind.RESTRICTION:
            reasons.append(f"restriction verified in force and {what}")
            return result(LegalStatus.BLOCKED)
        reasons.append(f"obligation verified in force and {what}")
        return result(LegalStatus.REVIEW_REQUIRED)

    return result(LegalStatus.PASS)


@dataclass(frozen=True)
class ScopeAssessment:
    """El resultado de Legal para un producto en una jurisdicción."""

    status: LegalStatus
    reasons: tuple[str, ...]
    confidence: float
    requirements: tuple[RequirementAssessment, ...] = field(default_factory=tuple)

    @property
    def recommendation(self) -> str:
        return RECOMMENDATION_FOR[self.status]


def assess_scope(
    *,
    jurisdiction: str,
    scope: str,
    assessments: list[RequirementAssessment],
) -> ScopeAssessment:
    """Une los requisitos declarados de un alcance en un único estado.

    Un `BLOCKED` gana a un `REVIEW_REQUIRED`, que gana a un `PASS`. `PASS` exige
    que **todos** los requisitos declarados pasen y que haya al menos uno.
    """
    if jurisdiction.strip().lower() != SUPPORTED_JURISDICTION:
        return ScopeAssessment(
            status=LegalStatus.UNKNOWN,
            reasons=(
                f"no regulatory source covers jurisdiction {jurisdiction!r}: EUR-Lex publishes "
                "EU law only, and national law is out of this milestone",
            ),
            confidence=INSUFFICIENT_DATA_CONFIDENCE,
        )
    if not assessments:
        return ScopeAssessment(
            status=LegalStatus.UNKNOWN,
            reasons=(
                f"no requirement is declared for scope {scope!r} in {jurisdiction!r}. That is not "
                "the same as there being none: nobody has said what applies",
            ),
            confidence=INSUFFICIENT_DATA_CONFIDENCE,
        )

    statuses = {a.status for a in assessments}
    if LegalStatus.BLOCKED in statuses:
        status = LegalStatus.BLOCKED
    elif LegalStatus.REVIEW_REQUIRED in statuses:
        status = LegalStatus.REVIEW_REQUIRED
    else:
        status = LegalStatus.PASS
    reasons = tuple(
        f"{a.requirement.regulation} ({a.requirement.celex}): {reason}"
        for a in assessments
        if a.status is not LegalStatus.PASS
        for reason in a.reasons
    )
    if status is LegalStatus.PASS:
        reasons = (
            "within the declared scope and the declared, checked requirements Legal found no "
            "blocker. This is not a statement that the product is legal",
        )
    return ScopeAssessment(
        status=status,
        reasons=reasons,
        confidence=min(a.confidence for a in assessments),
        requirements=tuple(assessments),
    )
