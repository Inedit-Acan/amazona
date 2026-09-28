"""Normalización de texto compartida entre dominios.

`fold` nació en el Milestone 36 dentro de la identidad de productos. El
Milestone 39 necesita exactamente la misma transformación para la identidad de
proveedores —dos nombres son el mismo si se escriben igual salvo mayúsculas,
acentos y puntuación— y copiarla habría dejado dos funciones que empiezan
iguales y divergen el día que alguien arregle una sola.

Vive en `core` y no en uno de los dos dominios porque no es de ninguno: es una
operación sobre cadenas, sin opinión sobre qué se está nombrando.
`product_intelligence.identity` la sigue exportando con su nombre de siempre.
"""

import re
import unicodedata

#: Los paréntesis de Wikipedia desambiguan, no nombran: `Belt (clothing)` es
#: «Belt» para cualquiera que no esté leyendo una enciclopedia. En un nombre de
#: empresa pasa lo mismo con `Acme Ltd. (Shenzhen)`.
_PARENTHETICAL = re.compile(r"\([^)]*\)")


def fold(name: str) -> str:
    """La clave de identidad de un nombre. Determinista y sin ninguna opinión.

    Quita los paréntesis de desambiguación, descompone en NFKD y tira las marcas
    diacríticas (`Café` y `Cafe` son el mismo café), pasa a minúsculas, convierte
    en espacio todo lo que no sea letra o dígito —guiones, comas, comillas— y
    colapsa los espacios.

    Lo que **no** hace: juntar palabras compuestas. `airfryer` no se convierte en
    `air fryer`, porque partir palabras necesita un léxico y un léxico es una
    opinión. Para eso están los catálogos de alias, donde la opinión se firma.

    Se conservan letras de cualquier alfabeto, no solo el latino: filtrar por
    `a-z` convertiría dos nombres en cirílico o en japonés en la misma clave
    vacía, y dos cosas distintas pasarían a ser una.
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
