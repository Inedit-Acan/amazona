"""El modelo de lectura de los pasos (Milestone 32, ADR 0010).

`steps_view` reconstruye el JSON que la API devuelve desde el Milestone 12 a partir
de las filas de `pipeline_steps`. Lo importante no es la forma por la forma: es que
la evaluación de riesgo de la ADR 0006 sigue leyendo lo mismo que antes, porque
depende del estado de **negocio** de cada paso —y ese no es el estado de ejecución
del paso, que ahora también existe.
"""

from app.db.models.pipeline_step import PipelineStep
from app.pipeline.review import assess_pipeline_run
from app.pipeline.schemas import STEP_ORDER, PipelineStepStatus, step_ordinal
from app.pipeline.service import steps_view


def step(name: str, *, status: str, ordinal: int | None = None, **kwargs) -> PipelineStep:
    return PipelineStep(
        pipeline_run_id="run-1",
        name=name,
        ordinal=step_ordinal(name) if ordinal is None else ordinal,
        status=status,
        attempt=kwargs.pop("attempt", 1),
        **kwargs,
    )


def test_the_view_is_ordered_by_the_only_order_the_chain_can_have():
    rows = [
        step("cfo", status=PipelineStepStatus.PENDING),
        step("research", status=PipelineStepStatus.COMPLETED),
        step("economics", status=PipelineStepStatus.COMPLETED),
    ]

    view = steps_view(rows)

    assert list(view.keys()) == ["research", "economics", "cfo"]


def test_the_business_detail_of_a_step_stays_where_it_always_was():
    rows = [
        step(
            "economics",
            status=PipelineStepStatus.COMPLETED,
            correlation_id="cid-econ",
            entity_id="econ-1",
            detail={"recommendation": "NO_GO"},
        )
    ]

    view = steps_view(rows)

    assert view["economics"]["correlation_id"] == "cid-econ"
    assert view["economics"]["entity_id"] == "econ-1"
    assert view["economics"]["recommendation"] == "NO_GO"


def test_the_execution_state_travels_apart_from_the_business_state():
    """Un paso puede estar COMPLETED y su resultado de negocio ser BLOCKED: son
    dos preguntas distintas y mezclarlas rompería la ADR 0006."""
    rows = [
        step(
            "marketplace",
            status=PipelineStepStatus.COMPLETED,
            correlation_id="cid-mkt",
            entity_id="listing-1",
            detail={"status": "BLOCKED"},
        )
    ]

    view = steps_view(rows)

    assert view["marketplace"]["step_status"] == "COMPLETED"
    assert view["marketplace"]["status"] == "BLOCKED"


def test_a_step_that_produced_nothing_has_no_entity_id_key():
    """El JSON antiguo omitía la clave cuando no había fila; omitirla sigue
    diciendo «no hay», que es distinto de «hay un nulo»."""
    rows = [step("research", status=PipelineStepStatus.FAILED, correlation_id="cid-r", detail={"candidate_count": 0})]

    view = steps_view(rows)

    assert "entity_id" not in view["research"]
    assert view["research"]["candidate_count"] == 0


def test_an_error_only_shows_up_when_there_is_one():
    rows = [
        step("legal", status=PipelineStepStatus.FAILED, error="RuntimeError: provider is down"),
        step("research", status=PipelineStepStatus.COMPLETED, entity_id="prod-1"),
    ]

    view = steps_view(rows)

    assert view["legal"]["error"] == "RuntimeError: provider is down"
    assert "error" not in view["research"]


def test_the_risk_assessment_still_fires_on_a_view_built_from_rows():
    """Regresión de la ADR 0006 a través del modelo nuevo: las mismas señales
    tienen que seguir pidiendo revisión humana."""
    rows = [
        step("research", status=PipelineStepStatus.COMPLETED, entity_id="prod-1"),
        step("economics", status=PipelineStepStatus.COMPLETED, detail={"recommendation": "NO_GO"}),
        step("marketplace", status=PipelineStepStatus.COMPLETED, detail={"status": "BLOCKED"}),
        step("cfo", status=PipelineStepStatus.COMPLETED, detail={"status": "CRITICAL"}),
    ]

    assessment = assess_pipeline_run(status="COMPLETED", steps=steps_view(rows))

    assert assessment.needs_review is True
    assert any("economics" in reason for reason in assessment.reasons)
    assert any("marketplace" in reason for reason in assessment.reasons)
    assert any("cfo" in reason for reason in assessment.reasons)


def test_a_clean_run_asks_for_nothing():
    rows = [
        step("economics", status=PipelineStepStatus.COMPLETED, detail={"recommendation": "GO"}),
        step("cfo", status=PipelineStepStatus.COMPLETED, detail={"status": "HEALTHY"}),
    ]

    assessment = assess_pipeline_run(status="COMPLETED", steps=steps_view(rows))

    assert assessment.needs_review is False


def test_the_nine_steps_are_the_nine_steps():
    assert len(STEP_ORDER) == 9
    assert STEP_ORDER[0] == "research"
    assert STEP_ORDER[-1] == "cfo"
    assert [step_ordinal(name) for name in STEP_ORDER] == list(range(9))
