"""La frontera entre `Approval` y `PipelineReview` (hardening pre-M44, ADR 0027).

Son dos conceptos distintos que comparten pantalla, no dos bandejas intercambiables:

- `Approval` es la autorización humana de una **decisión** del CEO (con su importe reservado, que se compromete o
  se libera al resolverla, y una caducidad);
- `PipelineReview` es la autorización de un **efecto de un paso** del pipeline (de un solo uso, `CONSUMED` al
  arrancar el paso) o la revisión a posteriori de una ejecución que ya terminó.

Lo que impide usar una por la otra por descuido no es una convención sino esto: ningún módulo de un lado importa
el modelo, el servicio o la API del otro, y las referencias con las que cada uno mueve el libro de presupuesto
viven en espacios de nombres distintos que ningún otro módulo escribe.
"""

import ast
import re
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"

#: Lo que pertenece al pipeline: ejecutar pasos con efecto, el gate, los trabajos y el ciclo de vida de las acciones.
PIPELINE_SIDE = ("pipeline/*.py", "gates/*.py", "jobs/*.py", "actions/*.py")
#: Lo que pertenece a las decisiones del CEO y a su aprobación.
CEO_SIDE = ("ceo/*.py", "approvals/*.py", "api/approvals.py")

APPROVAL_SIDE_MODULES = ("app.db.models.approval", "app.approvals", "app.api.approvals")
PIPELINE_SIDE_MODULES = (
    "app.db.models.pipeline_review",
    "app.pipeline",
    "app.gates",
    "app.actions",
    "app.api.pipeline",
)


def _imports(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def _files(patterns: tuple[str, ...]) -> list[Path]:
    return sorted(p for pattern in patterns for p in APP.glob(pattern) if p.is_file())


def _offenders(patterns: tuple[str, ...], forbidden: tuple[str, ...]) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in _files(patterns):
        hits = sorted(m for m in _imports(path) if any(m == f or m.startswith(f + ".") for f in forbidden))
        if hits:
            found[str(path.relative_to(APP))] = hits
    return found


def test_the_pipeline_never_reads_the_approval_of_a_ceo_decision():
    assert _offenders(PIPELINE_SIDE, APPROVAL_SIDE_MODULES) == {}


def test_the_ceo_approval_flow_never_reads_a_pipeline_review_nor_runs_a_step():
    assert _offenders(CEO_SIDE, PIPELINE_SIDE_MODULES) == {}


def test_the_gate_authorises_from_the_pipeline_review_and_nothing_else():
    gate_files = _files(("gates/*.py",))

    assert gate_files, "the gate package moved: update the boundary test"
    for path in gate_files:
        text = path.read_text(encoding="utf-8")
        assert "Approval" not in re.sub(r"HumanApproval", "", text).replace("human_approval", ""), path.name


def _files_writing(namespace: str) -> set[str]:
    pattern = re.compile(r"""f?["']""" + re.escape(namespace))
    return {
        str(path.relative_to(APP)).replace("\\", "/")
        for path in APP.rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
    }


def test_the_ledger_reference_of_a_ceo_approval_is_written_only_by_the_ceo_and_its_resolution():
    assert _files_writing("approval:") == {"api/approvals.py", "ceo/orchestrator.py"}


def test_the_ledger_reference_of_an_external_action_is_written_only_by_the_action_model():
    assert _files_writing("action:") == {"db/models/external_action.py"}


def test_the_site_of_a_pipeline_step_is_written_only_by_the_pipeline():
    assert _files_writing("pipeline_step:") == {"pipeline/service.py"}


def test_the_in_memory_approval_service_is_not_a_way_to_authorise_anything():
    """`ApprovalService` es un modelo en memoria del Milestone 1: no persiste nada y ninguna ruta autoriza a través
    de él. Si algún día una ruta lo usa, que sea una decisión consciente y no un descuido."""
    users = {
        str(path.relative_to(APP)).replace("\\", "/")
        for path in APP.rglob("*.py")
        if "ApprovalService" in path.read_text(encoding="utf-8")
    }

    assert users == {"approvals/service.py", "ceo/orchestrator.py"}
    api_imports = {m for path in (APP / "api").glob("*.py") for m in _imports(path)}
    assert "app.approvals.service.ApprovalService" not in api_imports
