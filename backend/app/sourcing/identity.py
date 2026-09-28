"""Cuándo dos fichas son el mismo proveedor (Milestone 39, ADR 0017).

El Milestone 36 estableció la regla para productos y la ADR 0014 la escribió:
identidad **determinista o declarada, nunca por parecido**. Aquí se aplica igual
a las empresas, por el mismo motivo y con una consecuencia más cara: dos fichas
del mismo fabricante parecen dos proveedores alternativos, y una decisión que
creía tener dos opciones tenía una.

Hasta aquí `SourcingService` buscaba por `(name, region)` **exactos**. Eso deja
`Shenzhen Volta Electronics` y `shenzhen volta electronics ` como dos empresas, y
con la entrada manual del Milestone 39 —donde el nombre lo teclea una persona—
eso deja de ser una posibilidad teórica.

## La regla

La clave de un proveedor es su nombre normalizado más **dónde está**. El sitio
forma parte de la identidad a propósito: dos fabricantes con el mismo nombre
comercial en China y en Polonia no son la misma empresa, y unirlos mezclaría un
plazo de tres días con uno de veinticinco.

El sitio es el **país** cuando se conoce y la región cuando no. No son
intercambiables, y por eso la clave dice cuál se usó: una ficha con país y otra
sin él no se funden solas, porque afirmar que la de región `eu` es la misma
empresa que la de país `PL` es exactamente la inferencia por parecido que la
ADR 0014 prohíbe.
"""

from dataclasses import dataclass

from app.core.text import fold
from app.sourcing.supplier_aliases import CATALOGUE_VERSION, SUPPLIER_ALIASES

#: Resuelto por la transformación determinista sobre el nombre y el sitio.
NORMALISED = "normalised"

#: Resuelto porque alguien escribió la equivalencia en el catálogo.
ALIAS = f"alias:{CATALOGUE_VERSION}"

#: Qué clase de sitio entró en la clave. Va dentro de la clave, no al lado:
#: si no, dos claves iguales significarían cosas distintas.
_COUNTRY = "country"
_REGION = "region"
_NOWHERE = "nowhere"


@dataclass(frozen=True)
class SupplierIdentity:
    """Quién es un proveedor, y cómo se supo."""

    #: Con qué se compara. Dos fichas son la misma empresa si comparten clave.
    key: str
    #: La forma del nombre con la que se habla de él: la canónica del catálogo
    #: cuando la hay, y si no la que llegó, limpia de espacios de sobra.
    name: str
    #: `normalised` o `alias:<versión>`. Es la respuesta a «¿por qué estas dos
    #: fichas son una?», contestable desde la base de datos meses después.
    method: str


def _place(country: str | None, region: str | None) -> tuple[str, str]:
    """Dónde está, y de qué clase es ese dónde."""
    if (country or "").strip():
        return _COUNTRY, fold(country or "")
    if (region or "").strip():
        return _REGION, fold(region or "")
    return _NOWHERE, ""


def resolve(
    name: str, *, country: str | None = None, region: str | None = None
) -> SupplierIdentity:
    """La identidad de un proveedor. Función pura: mismos datos, misma respuesta."""
    folded = fold(name)
    canonical = SUPPLIER_ALIASES.get(folded)
    method = NORMALISED
    display = " ".join(name.split())
    if canonical is not None:
        folded = fold(canonical)
        display = canonical
        method = ALIAS
    kind, place = _place(country, region)
    return SupplierIdentity(key=f"{folded}|{kind}:{place}", name=display, method=method)


def same_entity(
    left: SupplierIdentity | str,
    right: SupplierIdentity | str,
    **place: str | None,
) -> bool:
    """Si dos fichas son el mismo proveedor **según lo que se sabe hoy**.

    Un `False` no dice que sean empresas distintas: dice que nadie ha
    establecido que sean la misma. Es la misma distinción que entre un hecho
    ausente y un hecho negado.
    """
    a = left if isinstance(left, SupplierIdentity) else resolve(left, **place)
    b = right if isinstance(right, SupplierIdentity) else resolve(right, **place)
    return a.key == b.key
