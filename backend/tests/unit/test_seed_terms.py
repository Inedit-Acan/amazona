"""Qué se le pregunta a una fuente real, y que no se le pregunte dos veces.

El caso del primer test no es hipotético. Medido el 27-09-2026 contra la API de
Wikimedia: `Air_fryer` devuelve 30.897 visitas en doce meses y `air_fryer` —una
redirección con vida propia— devuelve 5 en cuatro meses. Antes del Milestone 36,
pedir `air fryer` en minúsculas sobre la categoría `home` preguntaba por las dos
y persistía dos candidatos para el mismo producto: uno con 0,7483 de demanda y un
gemelo con 0,1297 que parecía un producto que no le interesa a nadie.
"""

from app.integrations.product_intelligence.identity import resolve
from app.integrations.product_intelligence.terms import SEED_TERMS, terms_for


def test_a_keyword_that_is_already_in_the_catalogue_is_asked_once():
    terms = terms_for("home", ["air fryer"])

    assert terms.count("Air fryer") == 1
    assert "air fryer" not in terms


def test_the_catalogue_spelling_wins_over_the_callers():
    """No es estética: la forma del catálogo está revisada y es la que la fuente
    conoce; la de quien pregunta es texto libre."""
    assert terms_for("home", ["air fryer"])[0] == "Air fryer"
    assert terms_for("electronics", ["POWER BANK"])[0] == "Power bank"


def test_an_alias_is_asked_by_its_canonical_name():
    assert terms_for("home", ["airfryer"])[0] == "Air fryer"
    assert terms_for("electronics", ["smart watch"])[0] == "Smartwatch"


def test_what_the_caller_asks_still_goes_first():
    terms = terms_for("home", ["Humidifier"])

    assert terms[0] == "Humidifier"


def test_a_term_nobody_catalogued_is_asked_as_it_came():
    terms = terms_for("home", ["Sous vide cooker"])

    assert terms[0] == "Sous vide cooker"


def test_the_limit_counts_distinct_products_not_slots():
    """El recorte va después de resolver: si no, un duplicado gastaría una de las
    ocho peticiones que el adaptador tiene por ejecución."""
    terms = terms_for("home", ["air fryer", "AIR-FRYER", "airfryer"], limit=3)

    assert len(terms) == 3
    assert len({resolve(term).key for term in terms}) == 3


def test_nothing_to_ask_is_an_empty_list():
    """Y eso significa que no se pregunta nada, no que no haya demanda."""
    assert terms_for("una categoría que no existe") == []


def test_blank_keywords_are_not_questions():
    assert terms_for("una categoría que no existe", ["  ", ""]) == []


def test_no_category_asks_the_same_product_twice():
    """Un guardia sobre el catálogo escrito a mano: añadir «Airfryer» debajo de
    «Air fryer» no daría error, solo duplicaría candidatos en silencio."""
    for category, terms in SEED_TERMS.items():
        keys = [resolve(term).key for term in terms]
        assert len(keys) == len(set(keys)), f"la categoría {category} repite un producto"
