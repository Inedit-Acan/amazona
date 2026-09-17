from app.pipeline.review import assess_pipeline_run

_HEALTHY_STEPS = {
    "research": {"correlation_id": "c1", "entity_id": "p1", "candidate_count": 3},
    "sourcing": {"correlation_id": "c2", "entity_id": "q1", "candidate_count": 3},
    "economics": {"correlation_id": "c3", "entity_id": "e1", "recommendation": "GO"},
    "legal": {"correlation_id": "c4", "entity_id": "l1", "recommendation": "GO"},
    "ecommerce": {"correlation_id": "c5", "entity_id": "s1", "status": "READY"},
    "marketplace": {"correlation_id": "c6", "entity_id": "m1", "status": "READY"},
    "marketing": {"correlation_id": "c7", "entity_id": "mk1", "status": "READY"},
    "operations": {"correlation_id": "c8", "entity_id": "o1", "status": "READY"},
    "cfo": {"correlation_id": "c9", "entity_id": "cfo1", "status": "HEALTHY"},
}


def test_a_fully_healthy_completed_run_does_not_need_review():
    result = assess_pipeline_run(status="COMPLETED", steps=_HEALTHY_STEPS)

    assert result.needs_review is False
    assert result.reasons == []


def test_a_partial_run_needs_review():
    result = assess_pipeline_run(status="PARTIAL", steps={"research": {"correlation_id": "c1"}})

    assert result.needs_review is True
    assert any("PARTIAL" in reason for reason in result.reasons)


def test_economics_no_go_needs_review():
    steps = {**_HEALTHY_STEPS, "economics": {**_HEALTHY_STEPS["economics"], "recommendation": "NO_GO"}}

    result = assess_pipeline_run(status="COMPLETED", steps=steps)

    assert result.needs_review is True
    assert any("economics" in reason for reason in result.reasons)


def test_legal_no_go_needs_review():
    steps = {**_HEALTHY_STEPS, "legal": {**_HEALTHY_STEPS["legal"], "recommendation": "NO_GO"}}

    result = assess_pipeline_run(status="COMPLETED", steps=steps)

    assert result.needs_review is True
    assert any("legal" in reason for reason in result.reasons)


def test_any_blocked_downstream_step_needs_review():
    for step_name in ("ecommerce", "marketplace", "marketing", "operations"):
        steps = {**_HEALTHY_STEPS, step_name: {**_HEALTHY_STEPS[step_name], "status": "BLOCKED"}}

        result = assess_pipeline_run(status="COMPLETED", steps=steps)

        assert result.needs_review is True, f"{step_name} BLOCKED should require review"
        assert any(step_name in reason for reason in result.reasons)


def test_cfo_at_risk_or_critical_needs_review():
    for cfo_status in ("AT_RISK", "CRITICAL"):
        steps = {**_HEALTHY_STEPS, "cfo": {**_HEALTHY_STEPS["cfo"], "status": cfo_status}}

        result = assess_pipeline_run(status="COMPLETED", steps=steps)

        assert result.needs_review is True
        assert any(cfo_status in reason for reason in result.reasons)


def test_multiple_risk_signals_are_all_reported():
    steps = {
        **_HEALTHY_STEPS,
        "economics": {**_HEALTHY_STEPS["economics"], "recommendation": "NO_GO"},
        "cfo": {**_HEALTHY_STEPS["cfo"], "status": "CRITICAL"},
    }

    result = assess_pipeline_run(status="COMPLETED", steps=steps)

    assert result.needs_review is True
    assert len(result.reasons) == 2
