"""Cuándo dos fichas son el mismo proveedor (Milestone 39, principio del M36)."""

from app.sourcing.identity import ALIAS, NORMALISED, resolve, same_entity


def test_case_accents_and_spacing_do_not_make_two_companies():
    assert same_entity(
        resolve("Shenzhen Volta Electronics", region="china"),
        resolve("  shenzhen   volta electronics ", region="china"),
    )


def test_punctuation_does_not_make_two_companies():
    assert same_entity(
        resolve("Porto Leather & Co", region="eu"), resolve("Porto Leather and Co", region="eu")
    ) is False
    assert same_entity(
        resolve("Porto Leather & Co.", region="eu"), resolve("Porto Leather & Co", region="eu")
    )


def test_a_disambiguating_parenthesis_is_a_note_not_a_name():
    assert same_entity(
        resolve("Acme Supplies (Shenzhen)", country="CN"), resolve("Acme Supplies", country="CN")
    )


def test_the_same_name_in_two_countries_is_two_companies():
    """Unirlos mezclaría un plazo de tres días con uno de veinticinco."""
    assert not same_entity(resolve("Acme", country="CN"), resolve("Acme", country="PL"))


def test_a_country_and_a_region_do_not_merge_on_their_own():
    """Afirmar que el de región `eu` es el mismo que el de país `PL` es la
    inferencia por parecido que la ADR 0014 prohíbe."""
    assert not same_entity(resolve("Acme", region="eu"), resolve("Acme", country="PL"))


def test_a_supplier_with_no_place_keeps_its_own_key():
    nowhere = resolve("Acme")
    assert nowhere.key.endswith("|nowhere:")
    assert not same_entity(nowhere, resolve("Acme", region="eu"))


def test_the_method_says_how_it_was_resolved():
    assert resolve("Acme", region="eu").method == NORMALISED


def test_the_alias_catalogue_starts_empty_and_says_so_when_used(monkeypatch):
    """El catálogo está vacío a propósito: hoy no hay ni un par de nombres del
    que se pueda afirmar que son la misma empresa."""
    monkeypatch.setattr(
        "app.sourcing.identity.SUPPLIER_ALIASES", {"acme supplies co": "Acme Supplies"}
    )

    resolved = resolve("Acme Supplies Co", country="PL")

    assert resolved.name == "Acme Supplies"
    assert resolved.method == ALIAS
    assert resolved.key == resolve("Acme Supplies", country="PL").key


def test_a_name_with_no_letters_at_all_keeps_its_own_key():
    """Devolver la clave vacía haría que dos nombres distintos la compartieran."""
    assert resolve("???", region="eu").key != resolve("!!!", region="eu").key
