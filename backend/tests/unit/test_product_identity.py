"""Cuándo dos nombres son el mismo producto, y —sobre todo— cuándo no.

La mitad de estos tests comprueban que algo **no** se une. Es deliberado: el
fallo peligroso de la resolución de entidades no es quedarse corto —eso deja un
duplicado visible— sino unir de más, que contamina una medición y nadie puede
deshacerlo después (ADR 0014).
"""

import pytest

from app.integrations.product_intelligence.aliases import ALIASES, CATALOGUE_VERSION
from app.integrations.product_intelligence.identity import (
    ALIAS,
    NORMALISED,
    fold,
    resolve,
    same_entity,
)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Air fryer", "air fryer"),
        ("Air fryer", "  AIR   FRYER  "),
        ("Air fryer", "air-fryer"),
        ("Air fryer", "air_fryer"),
        # El paréntesis de Wikipedia desambigua, no nombra.
        ("Belt (clothing)", "Belt"),
        ("Belt (clothing)", "belt"),
        # Acentos: el mismo café.
        ("Café", "Cafe"),
        ("Jamón", "jamon"),
    ],
)
def test_normalisation_joins_the_same_name_written_differently(left, right):
    assert same_entity(left, right)
    assert resolve(left).method == NORMALISED


@pytest.mark.parametrize(
    ("left", "right"),
    [
        # Una letra de diferencia y otro producto. Esto es lo que un umbral de
        # similitud uniría algún día sin avisar.
        ("Air fryer", "Air dryer"),
        ("Power bank", "Power tank"),
        # Un producto más específico no es el mismo producto.
        ("Wireless earbuds", "Wireless earbuds pro"),
        ("Mini projector", "Video projector"),
        # Una categoría más amplia tampoco.
        ("Espresso machine", "Coffee machine"),
        ("Portable phone charger", "Power bank"),
        # Idiomas: nadie ha declarado que sean el mismo, y decirlo cambiaría una
        # medición que funciona por un 404 (ver `aliases.py`).
        ("Air fryer", "Freidora de aire"),
    ],
)
def test_nothing_is_joined_by_resemblance(left, right):
    assert not same_entity(left, right)


@pytest.mark.parametrize(
    ("asked", "canonical"),
    [
        ("airfryer", "Air fryer"),
        ("AirFryer", "Air fryer"),
        ("smart watch", "Smartwatch"),
        ("robot vacuum", "Robotic vacuum cleaner"),
        ("powerbank", "Power bank"),
    ],
)
def test_the_catalogue_joins_what_normalisation_cannot(asked, canonical):
    """Partir una palabra compuesta necesita un léxico, y un léxico es una
    opinión. Aquí la opinión está firmada en git."""
    identity = resolve(asked)

    assert identity.key == resolve(canonical).key
    assert identity.name == canonical
    assert identity.method == ALIAS
    assert CATALOGUE_VERSION in identity.method


def test_the_canonical_name_is_the_one_that_travels():
    """Quien pregunta por `airfryer` acaba preguntando por `Air fryer`, que es la
    forma que la fuente conoce."""
    assert resolve("  airfryer ").name == "Air fryer"
    # Y un nombre que nadie ha declarado viaja tal cual, solo sin sobras.
    assert resolve("  Nicho   raro  ").name == "Nicho raro"


def test_resolving_is_a_pure_function():
    assert resolve("Air fryer") == resolve("Air fryer")


def test_an_alias_key_is_already_a_key():
    """Una clave mal escrita en el catálogo no falla: simplemente deja de
    encontrarse. Este test es el que la encuentra."""
    for alias in ALIASES:
        assert fold(alias) == alias, f"la clave {alias!r} no está normalizada"


def test_no_alias_points_at_another_alias():
    """Sin cadenas: `a → b → c` haría que la identidad dependiera del orden en
    que se leyera el diccionario."""
    for alias, canonical in ALIASES.items():
        assert fold(canonical) not in ALIASES, f"{alias!r} apunta a otro alias"


def test_letters_of_any_alphabet_survive():
    """Filtrar por `a-z` convertiría dos nombres en otro alfabeto en la misma
    clave vacía, y dos productos distintos pasarían a ser uno."""
    assert fold("Чайник") != fold("Кофеварка")
    assert fold("扇風機") != fold("加湿器")
    assert fold("Чайник") != ""


def test_a_name_without_letters_keeps_itself():
    """Devolver la clave vacía haría que estos dos fueran el mismo producto."""
    assert fold("???") != fold("!!!")


def test_folding_is_idempotent():
    for name in ["Air fryer", "Belt (clothing)", "Café  au lait", "???"]:
        assert fold(fold(name)) == fold(name)
