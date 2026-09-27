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

import re
import unicodedata
from dataclasses import dataclass

from app.integrations.product_intelligence.aliases import ALIASES, CATALOGUE_VERSION

#: Resuelto por la transformación determinista: los dos nombres se escribían
#: igual salvo mayúsculas, acentos, puntuación o un paréntesis de desambiguación.
NORMALISED = "normalised"

#: Resuelto porque alguien lo escribió en el catálogo. Lleva la versión: una
#: identidad resuelta hoy se puede atribuir a la lista que había hoy.
ALIAS = f"alias:{CATALOGUE_VERSION}"

#: Los paréntesis de Wikipedia desambiguan, no nombran: `Belt (clothing)` es
#: «Belt» para cualquiera que no esté leyendo una enciclopedia.
_PARENTHETICAL = re.compile(r"\([^)]*\)")


def fold(name: str) -> str:
    """La clave de identidad de un nombre. Determinista y sin ninguna opinión.

    Quita los paréntesis de desambiguación, descompone en NFKD y tira las marcas
    diacríticas (`Café` y `Cafe` son el mismo café), pasa a minúsculas, convierte
    en espacio todo lo que no sea letra o dígito —guiones, comas, comillas— y
    colapsa los espacios.

    Lo que **no** hace: juntar palabras compuestas. `airfryer` no se convierte en
    `air fryer`, porque partir palabras necesita un léxico y un léxico es una
    opinión. Para eso está el catálogo de alias, donde la opinión se firma.

    Se conservan letras de cualquier alfabeto, no solo el latino: filtrar por
    `a-z` convertiría dos nombres en cirílico o en japonés en la misma clave
    vacía, y dos productos distintos pasarían a ser uno.
    """
    without_notes = _PARENTHETICAL.sub(" ", name)
    decomposed = unicodedata.normalize("NFKD", without_notes)
    unaccented = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    lowered = unaccented.casefold()
    words = "".join(ch if ch.isalnum() else " " for ch in lowered).split()
    if not words:
        # Un nombre sin una sola letra ni dígito. Devolver la clave vacía haría
        # que dos nombres distintos la compartieran, así que se conserva tal cual.
        return " ".join(name.split())
    return " ".join(words)


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
