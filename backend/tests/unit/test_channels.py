"""Dónde se mide una señal (Milestone 38, ADR 0016).

Las propiedades que estos tests protegen son tres: que **añadir una plataforma no
toque el núcleo**, que el **tipo no se deduzca del nombre** de la plataforma, y que
un canal inventado **falle en voz alta** en vez de convertirse en un canal fantasma
con sus propias señales.
"""

import pytest

from app.integrations.channels import (
    CHANNELS,
    Channel,
    ChannelKind,
    UnknownChannelError,
    channel_for,
    keys_of_kind,
)


def test_the_four_structural_kinds_are_the_only_ones():
    """Cerrado a propósito: un tipo nuevo significaría una manera de vender que el
    sistema no contemplaba, y eso merece una decisión, no una entrada."""
    assert {kind.value for kind in ChannelKind} == {"own_web", "marketplace", "search", "social"}


def test_a_marketplace_is_a_value_not_a_structural_type():
    """Amazon, eBay o Etsy son plataformas dentro de `marketplace`. Añadir una es
    una línea de catálogo y **ninguna migración**."""
    for key in ("marketplace:amazon", "marketplace:ebay", "marketplace:etsy"):
        assert channel_for(key).kind is ChannelKind.MARKETPLACE


def test_tiktok_is_not_tiktok_shop():
    """Uno es una superficie social donde se descubre; el otro un marketplace donde
    se cobra. Comparten marca y no naturaleza — es el ejemplo que mejor explica por
    qué el tipo no se puede deducir del nombre."""
    social = channel_for("social:tiktok")
    shop = channel_for("marketplace:tiktok_shop")

    assert social.kind is ChannelKind.SOCIAL
    assert shop.kind is ChannelKind.MARKETPLACE
    assert social.transactional is False
    assert shop.transactional is True


def test_an_undeclared_channel_fails_loudly():
    """Un typo se convertiría en un canal fantasma con sus propias señales,
    invisible para cualquier consulta que buscara el canal de verdad."""
    with pytest.raises(UnknownChannelError, match="marketplace:amazonn"):
        channel_for("marketplace:amazonn")


def test_the_error_says_what_is_available():
    with pytest.raises(UnknownChannelError, match="own_web"):
        channel_for("lo-que-sea")


def test_all_marketplaces_can_be_asked_without_parsing_a_string():
    """El tipo lo da el catálogo, no un `split(':')`: si mañana una clave cambiara
    de forma, cambiaría en un sitio y no en cinco que la interpretaban."""
    marketplaces = keys_of_kind(ChannelKind.MARKETPLACE)

    assert "marketplace:amazon" in marketplaces
    assert "own_web" not in marketplaces
    assert all(CHANNELS[key].kind is ChannelKind.MARKETPLACE for key in marketplaces)


def test_own_web_is_the_priority_channel_and_has_no_data_yet():
    """No hay ninguna web propia con tráfico real, así que no hay señal de este
    canal — y no se simula ninguna."""
    own = channel_for("own_web")

    assert own.kind is ChannelKind.OWN_WEB
    assert own.transactional is True
    assert "tráfico real" in own.notes


def test_search_is_declared_without_a_source_and_says_so():
    """Es el canal que la venta directa necesita medir y para el que no hay fuente
    gratuita fiable. Se declara para que la señal del día que la haya no tenga que
    inventarse un sitio donde vivir."""
    search = channel_for("search:google")

    assert search.kind is ChannelKind.SEARCH
    assert search.transactional is False
    assert "gratuita" in search.notes


@pytest.mark.parametrize("key", sorted(CHANNELS))
def test_every_channel_key_matches_its_entry(key):
    """Una clave y una entrada que no coinciden producirían un canal al que no se
    puede llegar."""
    assert CHANNELS[key].key == key


@pytest.mark.parametrize("key", sorted(CHANNELS))
def test_every_channel_has_a_human_name(key):
    assert isinstance(CHANNELS[key], Channel)
    assert CHANNELS[key].name


@pytest.mark.parametrize("key", sorted(CHANNELS))
def test_the_key_is_readable_on_its_own(key):
    """Una fila cruda de `product_signals` se entiende sin consultar nada, que es la
    misma razón por la que `method` viaja con cada número."""
    channel = CHANNELS[key]
    if channel.kind is ChannelKind.OWN_WEB:
        assert key == "own_web"
    else:
        assert key.startswith(f"{channel.kind.value}:")
