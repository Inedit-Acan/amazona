"""Las herramientas del CEO (M52): una lista CERRADA, cada una con su contrato.

El modelo no ve ni elige otra cosa. Cada herramienta declara su nombre, su descripción, el esquema de su entrada
(estricto: ni campos de más, ni tipos
coaccionados), una descripción de su salida, el permiso que exige (siempre `OWNER`), sus efectos, si necesita
confirmación y el evento de auditoría que
deja. No hay herramientas dinámicas ni una que confirme, ejecute, lea ficheros, ejecute SQL o toque un proveedor:
confirmar es un acto autenticado del propietario por
otra vía (`POST /api/ceo/actions/{id}/confirm`), que el modelo no puede invocar.

- **Lectura** (`get_*`): se ejecutan sin confirmación. Tipadas, acotadas, sin filtros libres.
- **Propuesta** (`propose_*`): preparan una acción. Proponer no ejecuta: crea una propuesta `PROPOSED` y nada más.
"""

from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator

from app.ceo_chat.provider import ModelToolSpec
from app.core.errors import AmazonaError

Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
Reason = Annotated[str, StringConstraints(min_length=3, max_length=500)]

#: Las únicas claves de contexto que una misión propuesta puede llevar (las de datos de cada especialista). Ninguna es
#: de gasto.
MISSION_CONTEXT_KEYS = frozenset({"product_validation", "supplier_sourcing", "finance_validation", "legal_validation"})


class ToolRejected(AmazonaError):
    """El modelo pidió algo que no se puede hacer: una herramienta que no existe, parámetros de más o inválidos. Se le
    devuelve como error de la herramienta
    y NO se ejecuta nada."""


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


# --- Lectura
# ----------------------------------------------------------------------------------------------------


class GetSystemStatusIn(_Input):
    pass


class GetLatestMissionIn(_Input):
    pass


class GetBudgetStatusIn(_Input):
    pass


class GetPendingApprovalsIn(_Input):
    include_resolved: bool = False
    limit: int = Field(default=5, ge=1, le=10)


class GetTaskDetailsIn(_Input):
    task_id: Identifier


class GetDecisionHistoryIn(_Input):
    #: Sin proyecto, el de la última misión.
    project_id: Identifier | None = None


class GetAuditSummaryIn(_Input):
    limit: int = Field(default=10, ge=1, le=20)
    correlation_id: Identifier | None = None


# --- Propuestas
# ---------------------------------------------------------------------------------------------------------------------


class ProposeCreateMissionIn(_Input):
    title: Annotated[str, StringConstraints(min_length=3, max_length=255)]
    description: Annotated[str, StringConstraints(max_length=1000)] | None = None
    reason: Reason
    #: Datos de los especialistas (de fixtures), nunca de gasto: una misión propuesta por el chat no pide gasto ni toca
    #: el presupuesto.
    context: dict[str, Any] | None = None

    @field_validator("context")
    @classmethod
    def _only_specialist_data(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return value
        for key, section in value.items():
            if key not in MISSION_CONTEXT_KEYS:
                raise ValueError(f"context key {key!r} is not allowed: only {sorted(MISSION_CONTEXT_KEYS)}")
            if not isinstance(section, dict) or any(
                not isinstance(k, str) or not isinstance(v, (str, int, float, bool, type(None)))
                for k, v in section.items()
            ):
                raise ValueError(f"context section {key!r} must be a flat object of plain values")
        return value


class ProposeRetryTaskIn(_Input):
    task_id: Identifier
    after_attempt: int = Field(ge=1, le=10)
    reason: Reason


class ProposeReassignTaskIn(_Input):
    task_id: Identifier
    agent_id: Identifier
    reason: Reason


class ProposeResumeMissionIn(_Input):
    objective_id: Identifier
    project_id: Identifier | None = None
    reason: Reason


class ProposeResolveApprovalIn(_Input):
    approval_id: Identifier
    decision: Literal["approve", "reject"]
    reason: Reason


@dataclass(frozen=True)
class ToolDef:
    name: str
    description: str
    input_model: type[BaseModel]
    kind: Literal["read", "propose"]
    output_schema: dict[str, Any]
    audit_event: str
    #: `none` (solo lee) o `proposal_only` (escribe la propuesta, nada más).
    side_effects: str
    confirmation_required: bool
    permission: str = "OWNER"


def _read(name: str, description: str, model: type[BaseModel], output: dict[str, Any]) -> ToolDef:
    return ToolDef(name, description, model, "read", output, "ceo.tool_read", "none", False)


def _propose(name: str, description: str, model: type[BaseModel], output: dict[str, Any]) -> ToolDef:
    return ToolDef(name, description, model, "propose", output, "ceo.action_proposed", "proposal_only", True)


_PROPOSAL_OUTPUT = {"type": "object", "description": "La propuesta creada (estado PROPOSED): no se ha ejecutado nada."}

READ_TOOLS: dict[str, ToolDef] = {
    tool.name: tool
    for tool in (
        _read(
            "get_system_status",
            "Estado general de AMAZONA: backend, misiones, tareas por estado, agentes y bloqueos.",
            GetSystemStatusIn,
            {"type": "object", "description": "Recuentos y bloqueos."},
        ),
        _read(
            "get_latest_mission",
            "La última misión: objetivo, proyecto, estado, tareas, decisión vigente y su historial de decisiones.",
            GetLatestMissionIn,
            {"type": "object", "description": "Misión, tareas y decisiones."},
        ),
        _read(
            "get_budget_status",
            "El presupuesto autorizado: límite, reservado, comprometido, gastado y restante.",
            GetBudgetStatusIn,
            {"type": "object", "description": "Importes en texto decimal."},
        ),
        _read(
            "get_pending_approvals",
            "Las aprobaciones pendientes (y, si se pide, las resueltas) con su motivo.",
            GetPendingApprovalsIn,
            {"type": "object", "description": "Lista acotada de aprobaciones."},
        ),
        _read(
            "get_task_details",
            "Una tarea: estado, agente asignado, intentos, ejecuciones y estado de recuperación.",
            GetTaskDetailsIn,
            {"type": "object", "description": "Tarea, asignación, intentos y recuperación."},
        ),
        _read(
            "get_decision_history",
            "Las decisiones de un proyecto (V1, V2…): cuál es la vigente, a cuál sustituye y sus evidencias.",
            GetDecisionHistoryIn,
            {"type": "object", "description": "Decisiones con versión y evidencias."},
        ),
        _read(
            "get_audit_summary",
            "Actividad relevante reciente de la auditoría (acción, actor, recurso, hora), sin secretos.",
            GetAuditSummaryIn,
            {"type": "object", "description": "Lista acotada de eventos redactados."},
        ),
    )
}

PROPOSE_TOOLS: dict[str, ToolDef] = {
    tool.name: tool
    for tool in (
        _propose(
            "propose_create_mission",
            "Propone crear y ejecutar una misión con agentes simulados (sin gasto). No la ejecuta: el propietario "
            "confirma en una tarjeta.",
            ProposeCreateMissionIn,
            _PROPOSAL_OUTPUT,
        ),
        _propose(
            "propose_retry_task",
            "Propone reintentar UNA vez una tarea FAILED con su agente asignado. No lo ejecuta.",
            ProposeRetryTaskIn,
            _PROPOSAL_OUTPUT,
        ),
        _propose(
            "propose_reassign_task",
            "Propone cambiar el agente de una tarea FAILED, BLOQUEADA o PENDIENTE a otro agente compatible. "
            "No lo ejecuta ni reintenta.",
            ProposeReassignTaskIn,
            _PROPOSAL_OUTPUT,
        ),
        _propose(
            "propose_resume_mission",
            "Propone reanudar una misión incompleta ya recuperada: ejecuta solo lo pendiente y escribe una decisión "
            "nueva. No lo ejecuta.",
            ProposeResumeMissionIn,
            _PROPOSAL_OUTPUT,
        ),
        _propose(
            "propose_resolve_approval",
            "Propone aprobar o rechazar una aprobación PENDIENTE existente. No lo ejecuta.",
            ProposeResolveApprovalIn,
            _PROPOSAL_OUTPUT,
        ),
    )
}

TOOLS: dict[str, ToolDef] = {**READ_TOOLS, **PROPOSE_TOOLS}


def parse_arguments(name: str, arguments: object) -> BaseModel:
    """Valida la llamada del modelo: la herramienta tiene que existir y los argumentos cumplir su esquema estricto.
    Cualquier otra cosa es `ToolRejected`."""
    tool = TOOLS.get(name) if isinstance(name, str) else None
    if tool is None:
        raise ToolRejected(f"unknown tool {name!r}: only the listed tools exist")
    if not isinstance(arguments, dict):
        raise ToolRejected(f"arguments of {name} must be an object")
    try:
        return tool.input_model.model_validate(arguments)
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(str(p) for p in e['loc']) or 'arguments'}: {e['type']}" for e in exc.errors())
        raise ToolRejected(f"invalid arguments for {name}: {problems}") from None


def tool_specs() -> list[ModelToolSpec]:
    """Lo que se le enseña al modelo: nombre, descripción y esquema JSON de la entrada (con `additionalProperties:
    false`)."""
    return [
        ModelToolSpec(name=tool.name, description=tool.description, input_schema=tool.input_model.model_json_schema())
        for tool in TOOLS.values()
    ]
