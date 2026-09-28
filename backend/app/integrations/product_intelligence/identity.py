"""Cuándo dos nombres son el mismo producto candidato (Milestone 36, ADR 0014).

Hasta aquí la identidad de un candidato era su nombre en minúsculas. Eso bastaba
para un mock y una fuente, y **no basta ni para una**. Medido el 27-09-2026 contra
la API real: preguntar por el keyword `air fryer` en minúsculas y tener `Air
fryer` en el catálogo produce dos consultas a Wikimedia que devuelven dos páginas
distintas —30.897 visitas en doce meses una, 5 visitas en cuatro meses la otra— y
por tanto dos candidatos para el mismo objeto, uno con 0,7483 de demanda y un
gemelo con 0,1297 que parece un producto que no le interesa a nadie. Ninguno de
los dos está marcado como duplicado y los dos son reales.

## La regla

Dos nombres son el mismo producto por **normalización** —una transformación
determinista, siempre la misma— o por **alias declarado** en `aliases.py`. Por
nada más. Lo que no case por una de esas dos vías **se queda separado**.

No hay distancia de edición, ni similitud, ni umbral. Un 0,85 de parecido uniría
«Air fryer» con «Air dryer» algún día y nadie sabría qué día empezó: es el
equivalente en identidad al cero inventado que el Milestone 34 prohibió. Preferir
quedarse corto es una decisión: dos candidatos que eran uno son un duplicado
visible; un candidato que eran dos es una medición contaminada que nadie puede
deshacer.

Y cada resolución dice **cómo** se resolvió (`normalised` o `alias:v1`), porque
«¿por qué estos dos son uno?» tiene que poder contestarse desde la base de datos
meses después.
"""

from dataclasses import dataclass

from app.core.text import fold
from app.integrations.product_intelligence.aliases import ALIASES, CATALOGUE_VERSION

#: Resuelto por la transformación determinista: los dos nombres se escribían
#: igual salvo mayúsculas, acentos, puntuación o un paréntesis de desambiguación.
NORMALISED = "normalised"

#: Resuelto porque alguien lo escribió en el catálogo. Lleva la versión: una
#: identidad resuelta hoy se puede atribuir a la lista que había hoy.
ALIAS = f"alias:{CATALOGUE_VERSION}"

#: `fold` vive en `app.core.text` desde el Milestone 39, porque la identidad de
#: proveedores necesita la misma transformación y dos copias divergen. Se
#: reexporta aquí para que quien la importaba siga encontrándola donde estaba.
__all__ = ["ALIAS", "NORMALISED", "Identity", "fold", "resolve", "same_entity"]


@dataclass(frozen=True)
class Identity:
    """Quién es un candidato, y cómo se supo."""

    #: Con qué se compara. Dos candidatos son el mismo si comparten clave.
    key: str
    #: La forma del nombre que se usa para hablar de él: la canónica del catálogo
    #: cuando la hay, y si no la que llegó, limpia de espacios de sobra.
    name: str
    #: `normalised` o `alias:<versión>`. No es adorno: es la respuesta a «¿por
    #: qué estos dos son uno?».
    method: str


def resolve(name: str) -> Identity:
    """La identidad de un nombre. Función pura: mismo nombre, misma respuesta."""
    folded = fold(name)
    canonical = ALIASES.get(folded)
    if canonical is not None:
        return Identity(key=fold(canonical), name=canonical, method=ALIAS)
    return Identity(key=folded, name=" ".join(name.split()), method=NORMALISED)


def same_entity(left: str, right: str) -> bool:
    """Si dos nombres designan el mismo producto **según lo que se sabe hoy**.

    Un `False` no dice que sean productos distintos: dice que nadie ha
    establecido que sean el mismo. Es la misma distinción que entre una señal
    ausente y un cero.
    """
    return resolve(left).key == resolve(right).key
