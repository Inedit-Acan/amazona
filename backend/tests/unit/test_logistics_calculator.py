from app.sourcing.logistics import estimate_logistics_cost


def test_same_input_returns_the_same_result():
    first = estimate_logistics_cost(
        origin_region="china", destination_region="mexico", unit_cost=4.2, moq=500
    )
    second = estimate_logistics_cost(
        origin_region="china", destination_region="mexico", unit_cost=4.2, moq=500
    )

    assert first == second


def test_farther_or_less_connected_regions_cost_more_per_unit():
    nearby = estimate_logistics_cost(
        origin_region="mexico", destination_region="mexico", unit_cost=4.2, moq=500
    )
    far = estimate_logistics_cost(
        origin_region="china", destination_region="mexico", unit_cost=4.2, moq=500
    )

    assert far.shipping_cost_per_unit > nearby.shipping_cost_per_unit
    assert far.estimated_total_logistics_cost > nearby.estimated_total_logistics_cost


def test_unknown_region_pair_uses_a_conservative_default_not_an_error():
    result = estimate_logistics_cost(
        origin_region="does-not-exist", destination_region="also-unknown", unit_cost=4.2, moq=500
    )

    assert result.shipping_cost_per_unit > 0
    assert result.estimated_total_logistics_cost > 0


def test_result_has_the_required_shape():
    unit_cost = 4.2
    moq = 500
    result = estimate_logistics_cost(
        origin_region="china", destination_region="eu", unit_cost=unit_cost, moq=moq
    )

    assert result.shipping_cost_per_unit > 0
    assert result.customs_factor >= 1.0
    expected_total = round(
        (result.shipping_cost_per_unit * moq) + (unit_cost * (result.customs_factor - 1) * moq),
        4,
    )
    assert result.estimated_total_logistics_cost == expected_total
    assert result.notes


def test_total_cost_scales_with_moq():
    small_order = estimate_logistics_cost(
        origin_region="china", destination_region="eu", unit_cost=4.2, moq=100
    )
    large_order = estimate_logistics_cost(
        origin_region="china", destination_region="eu", unit_cost=4.2, moq=1000
    )

    assert large_order.estimated_total_logistics_cost > small_order.estimated_total_logistics_cost
