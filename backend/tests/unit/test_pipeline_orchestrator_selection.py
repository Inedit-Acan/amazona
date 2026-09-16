from dataclasses import dataclass

from app.pipeline.service import pick_best_candidate, pick_best_quote


@dataclass
class _FakeProduct:
    id: str


@dataclass
class _FakeQuote:
    id: str
    total_landed_cost_per_unit: float


def test_pick_best_candidate_picks_the_highest_opportunity_score():
    products = [_FakeProduct(id="a"), _FakeProduct(id="b"), _FakeProduct(id="c")]
    scores = {"a": 0.4, "b": 0.9, "c": 0.6}

    best = pick_best_candidate(products, scores)

    assert best.id == "b"


def test_pick_best_candidate_treats_a_missing_score_as_zero():
    products = [_FakeProduct(id="a"), _FakeProduct(id="b")]
    scores = {"a": 0.1}

    best = pick_best_candidate(products, scores)

    assert best.id == "a"


def test_pick_best_quote_picks_the_lowest_total_landed_cost():
    quotes = [
        _FakeQuote(id="expensive", total_landed_cost_per_unit=5.0),
        _FakeQuote(id="cheap", total_landed_cost_per_unit=2.1),
        _FakeQuote(id="middle", total_landed_cost_per_unit=3.5),
    ]

    best = pick_best_quote(quotes)

    assert best.id == "cheap"
