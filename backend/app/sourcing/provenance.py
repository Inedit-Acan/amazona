"""Quién afirma un hecho sobre un proveedor (Milestone 39, ADR 0017).

Hasta aquí un proveedor estaba `verified: bool`. Un booleano contesta «sí» a una
pregunta que nadie ha formulado: ¿verificado **por quién**, y contra **qué**? El
plan maestro §10 lo dice en una línea: «No marcar un proveedor como "verified"
sin explicar qué significa», y pide cuatro niveles donde había dos.

Es el mismo defecto que el Milestone 37 arregló para las señales. Allí un número
era «simulado o no» y se partió en `SignalBasis`, porque una medición y una
estimación no valen lo mismo aunque las dos vengan del mundo. Aquí el eje no es
de qué está hecho el número sino **quién lo sostiene**, que es la pregunta que
importa cuando el dato es un precio negociado o una promesa de envío directo.

## Los niveles

- `THIRD_PARTY_VERIFIED`: alguien independiente del proveedor lo comprobó. Una
  auditoría, un registro mercantil, un certificado emitido por un organismo.
  **Exige emisor**: construir uno sin decir quién verificó falla en voz alta.
- `SUPPLIER_CLAIM`: lo dice el proveedor. Es la procedencia normal de casi todo
  lo que hay en una cotización, y es información legítima — de parte interesada.
  Una ficha de catálogo y un correo del comercial son esto.
- `AMAZONA_ESTIMATE`: lo calculamos nosotros con un método propio. El coste
  logístico estimado es esto. No viene del proveedor ni de un tercero.
- `SIMULATED`: un fixture. No viene del mundo en absoluto.
- `UNKNOWN`: **nadie lo ha dicho**. No es un valor que se guarde: es lo que
  contesta el sistema cuando no hay declaración. Un hecho ausente se queda
  ausente, igual que una señal ausente no se convierte en cero.

`SIMULATED` no estaba en la lista de cuatro del plan §10 y se añade a propósito:
el mock afirma precios y MOQ, y llamarlos `AMAZONA_ESTIMATE` diría que alguien
los calculó. Nadie los calculó; están escritos en un fichero. Sin esta casilla el
mock tendría que mentir para caber en el enum.

## Lo que este módulo NO hace

No colapsa los niveles en una puntuación. Hay un orden de preferencia para
**elegir** entre dos declaraciones del mismo hecho y para **ordenar** una lista,
y ahí se acaba: el plan §11 pide que el riesgo siga siendo explicable por
dimensiones, y un número único es justo lo contrario.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, TypeVar

from app.core.errors import ValidationError


class SupplierFactProvenance(StrEnum):
    """Quién sostiene un hecho sobre un proveedor."""

    THIRD_PARTY_VERIFIED = "third_party_verified"
    SUPPLIER_CLAIM = "supplier_claim"
    AMAZONA_ESTIMATE = "amazona_estimate"
    SIMULATED = "simulated"
    UNKNOWN = "unknown"


#: En qué orden se prefiere una declaración cuando hay varias del mismo hecho.
#: Lo comprobado por un tercero antes que lo que dice el interesado, lo que dice
#: el interesado antes que lo que calculamos nosotros, y un fixture el último de
#: los que dicen algo. `UNKNOWN` cierra la lista porque no dice nada.
#:
#: **No es una puntuación de riesgo** y no se promedia: es un criterio de
#: desempate, y existe para que «hay dos precios para este proveedor» tenga una
#: respuesta estable en vez de depender del orden de inserción.
_PROVENANCE_RANK: dict[SupplierFactProvenance, int] = {
    SupplierFactProvenance.THIRD_PARTY_VERIFIED: 0,
    SupplierFactProvenance.SUPPLIER_CLAIM: 1,
    SupplierFactProvenance.AMAZONA_ESTIMATE: 2,
    SupplierFactProvenance.SIMULATED: 3,
    SupplierFactProvenance.UNKNOWN: 4,
}

#: Las procedencias que se pueden **guardar**. `UNKNOWN` no está: una fila que
#: dice «no se sabe» ocupa sitio para afirmar exactamente lo mismo que no tener
#: fila, y además es indistinguible de un error de carga.
STORABLE = frozenset(
    p for p in SupplierFactProvenance if p is not SupplierFactProvenance.UNKNOWN
)


def rank(provenance: SupplierFactProvenance) -> int:
    """Cuánto pesa una procedencia al desempatar. Más bajo, antes."""
    return _PROVENANCE_RANK[provenance]


def parse(value: str | None) -> SupplierFactProvenance:
    """La procedencia guardada en una columna, o `UNKNOWN` si no hay ninguna.

    Un valor que no está en el enum **no se acepta como desconocido**: sería
    convertir un error de datos en una respuesta tranquilizadora.
    """
    if value is None or value == "":
        return SupplierFactProvenance.UNKNOWN
    return SupplierFactProvenance(value)


class MissingVerifierError(ValidationError):
    """Se ha declarado algo verificado por un tercero sin decir por quién.

    Falla al construir, no al mostrarse, por el mismo motivo que el techo de
    confianza del Milestone 37 falla al construir la señal: un `verified` sin
    emisor es exactamente el dato que la ADR 0017 existe para impedir, y
    recortarlo en silencio escondería el problema en vez de enseñarlo.
    """


T = TypeVar("T")


@dataclass(frozen=True)
class Fact(Generic[T]):
    """Un valor y quién lo sostiene. `None` en `value` es «no se sabe».

    Va junto a propósito: un precio sin procedencia y una procedencia sin precio
    son las dos formas de perder la mitad del dato, y las dos ocurrían antes de
    este milestone.
    """

    value: T | None
    provenance: SupplierFactProvenance = SupplierFactProvenance.UNKNOWN
    #: De dónde salió: `manual:owner`, `fixtures:mock-supplier-directory`, una
    #: URL, el nombre del organismo que emitió un certificado. Obligatorio
    #: cuando la procedencia es `THIRD_PARTY_VERIFIED`.
    source: str | None = None

    def __post_init__(self) -> None:
        if self.value is None and self.provenance is not SupplierFactProvenance.UNKNOWN:
            raise ValidationError(
                f"a fact with no value cannot be {self.provenance}: "
                "an absent fact has no source to attribute it to"
            )
        if self.value is not None and self.provenance is SupplierFactProvenance.UNKNOWN:
            raise ValidationError(
                "a fact with a value must say who says so: "
                "an unattributed value is what Milestone 39 exists to remove"
            )
        if self.provenance is SupplierFactProvenance.THIRD_PARTY_VERIFIED and not (
            self.source or ""
        ).strip():
            raise MissingVerifierError(
                "third-party verification must name the verifier: "
                "'verified' without an issuer explains nothing (plan maestro §10)"
            )

    @property
    def known(self) -> bool:
        return self.value is not None

    @classmethod
    def unknown(cls) -> "Fact[T]":
        """Lo que se sabe de un hecho que nadie ha declarado: nada."""
        return cls(value=None, provenance=SupplierFactProvenance.UNKNOWN, source=None)


def best(facts: list["Fact[T]"]) -> "Fact[T]":
    """La declaración que más pesa de entre varias del mismo hecho.

    Estable: con dos declaraciones de la misma procedencia gana la primera, que
    es la que llegó antes. Sin declaraciones conocidas, devuelve desconocido —
    nunca la primera «por tener algo».
    """
    known = [f for f in facts if f.known]
    if not known:
        return Fact.unknown()
    return min(known, key=lambda f: rank(f.provenance))
