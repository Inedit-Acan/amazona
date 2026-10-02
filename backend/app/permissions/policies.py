from enum import StrEnum

from app.auth.actor import RoleName


class ActionType(StrEnum):
    """Agent-level actions, evaluated by PermissionEngine inside the CEO graph.

    These are about what an *agent* may do while running (Milestone 1), and
    their answer can be "ask a human". They are deliberately separate from
    ApiAction below, which is about what an authenticated *person* may request
    over HTTP and whose answer is only yes or no.
    """

    RESEARCH_READ = "research.read"
    DRAFT_CREATE = "draft.create"
    EXTERNAL_SPEND = "external.spend"
    POLICY_EDIT = "policy.edit"
    PERMISSION_GRANT = "permission.grant"
    #: Abrir un cobro en una pasarela (Milestone 44): una cobranza no es un gasto, así que no pide la
    #: aprobación que pide `EXTERNAL_SPEND`.
    PAYMENT_COLLECT = "payment.collect"
    #: Devolver dinero cobrado (Milestone 44). Tampoco es gasto del presupuesto operativo. Lo pide siempre una
    #: persona con permiso (`REFUND_WRITE`); ningún camino automático crea reembolsos.
    MONEY_REFUND = "money.refund"


class PermissionResult(StrEnum):
    ALLOWED = "ALLOWED"
    HUMAN_APPROVAL_REQUIRED = "HUMAN_APPROVAL_REQUIRED"
    DENIED = "DENIED"


OWNER_ONLY_ACTIONS = {ActionType.POLICY_EDIT}

DEFAULT_POLICY: dict[ActionType, PermissionResult] = {
    ActionType.RESEARCH_READ: PermissionResult.ALLOWED,
    ActionType.DRAFT_CREATE: PermissionResult.ALLOWED,
    ActionType.EXTERNAL_SPEND: PermissionResult.HUMAN_APPROVAL_REQUIRED,
    ActionType.POLICY_EDIT: PermissionResult.ALLOWED,
    ActionType.PERMISSION_GRANT: PermissionResult.ALLOWED,
    ActionType.PAYMENT_COLLECT: PermissionResult.ALLOWED,
    ActionType.MONEY_REFUND: PermissionResult.ALLOWED,
}


class ApiAction(StrEnum):
    """What a request to a mutating endpoint is trying to do. Every mutating
    route declares exactly one (Milestone 29)."""

    #: Create an objective and run the CEO validation graph on it.
    OBJECTIVE_WRITE = "objective.write"
    #: Run one specialist agent: research, sourcing, economics, legal,
    #: ecommerce, marketplace, marketing, operations, cfo.
    AGENT_RUN = "agent.run"
    #: Run the full Fase 3 pipeline.
    PIPELINE_RUN = "pipeline.run"
    #: Approve or reject a spend approval.
    APPROVAL_RESOLVE = "approval.resolve"
    #: Approve or reject a risky pipeline step.
    REVIEW_RESOLVE = "review.resolve"
    #: Open or resolve an incident.
    INCIDENT_WRITE = "incident.write"
    #: Enable or disable the pipeline kill switch.
    KILL_SWITCH_WRITE = "kill_switch.write"
    #: Read business data: catalogue, projects, suppliers, economics, decisions,
    #: approvals, incidents, pipeline state. Milestone 29.1.
    BUSINESS_READ = "business.read"
    #: Read the audit trail. Separate from BUSINESS_READ because it is not
    #: information about the business but about the people operating it.
    AUDIT_READ = "audit.read"
    #: Read deployment diagnostics: schema version, environment and which
    #: provider backs each external domain.
    DIAGNOSTICS_READ = "diagnostics.read"
    #: Dar de alta un proveedor, una cotización o una capacidad del §16 a mano
    #: (Milestone 39). Es distinto de `AGENT_RUN`: correr el agente de sourcing
    #: es pedirle datos a un directorio, y esto es **afirmar un hecho** sobre una
    #: empresa real. Un ANALYST analiza lo que hay; declarar que un proveedor
    #: hace envío ciego es una decisión de negocio con consecuencias operativas.
    SUPPLIER_WRITE = "supplier.write"
    #: Declarar un tipo de cambio a mano (Milestone 40). Acción propia y no
    #: `SUPPLIER_WRITE`: un tipo de cambio no es un hecho sobre un proveedor, y
    #: es la cifra por la que se multiplica todo lo demás. `SYSTEM` no la tiene:
    #: ningún proceso automático declara un cambio.
    EXCHANGE_RATE_WRITE = "exchange_rate.write"
    #: Declarar, sustituir o retirar un requisito regulatorio, aportar evidencia de
    #: cumplimiento y pedir una comprobación contra la fuente (Milestone 41, ADR
    #: 0019). Declarar que una norma **se aplica** a una clase de producto es un
    #: juicio jurídico con consecuencias: solo OWNER y ADMIN. REVIEWER lee y no
    #: escribe, y `SYSTEM` no la tiene: ningún proceso automático declara
    #: aplicabilidad normativa por iniciativa propia.
    REGULATORY_WRITE = "regulatory.write"
    #: Enqueue, cancel or requeue a job. Milestone 31. Reading jobs is
    #: BUSINESS_READ: seeing what the system is doing is not the same as
    #: making it do something.
    JOB_WRITE = "job.write"
    #: Crear un pedido (Milestone 44, ADR 0028). Lo crea una persona con permiso, o el CLI en una simulación;
    #: cuando exista la web pública lo creará una identidad de sistema. Distinto de cobrar, devolver o enviar.
    ORDER_WRITE = "order.write"
    #: Abrir un intento de cobro de un pedido (Milestone 44). Es una acción externa con consecuencias, aunque no
    #: gaste presupuesto: pasa por el ActionGate (`COLLECT_PAYMENT`) y por `ExternalAction`.
    PAYMENT_WRITE = "payment.write"
    #: Devolver dinero cobrado (Milestone 44). Solo OWNER y ADMIN: es dinero que sale, y ningún camino automático lo
    #: pide. Pasa por el ActionGate (`REFUND`: permiso, kill switch, resultado desconocido) y por `ExternalAction`.
    REFUND_WRITE = "refund.write"
    #: Repartir un pedido pagado en fulfillments, comprar al proveedor, enviar y confirmar la entrega (Milestone 44).
    #: Comprar y enviar son acciones externas gobernadas por el ActionGate y por `ExternalAction`.
    FULFILMENT_WRITE = "fulfilment.write"


#: Who may do what over HTTP. Deny by default: an action absent from a role's
#: set is denied, and a role that is not in this table (or no role at all) can
#: do nothing.
#:
#: ANALYST may run the specialist agents because research, sourcing, economics
#: and legal are analysis without external side effects (plan maestro §7);
#: OPERATOR runs pipelines but cannot touch the kill switch, and REVIEWER
#: resolves decisions without being able to start work.
API_ROLE_ACTIONS: dict[RoleName, frozenset[ApiAction]] = {
    RoleName.OWNER: frozenset(ApiAction),
    RoleName.ADMIN: frozenset(ApiAction),
    RoleName.OPERATOR: frozenset(
        {
            ApiAction.OBJECTIVE_WRITE,
            ApiAction.AGENT_RUN,
            ApiAction.PIPELINE_RUN,
            ApiAction.INCIDENT_WRITE,
            ApiAction.JOB_WRITE,
            ApiAction.SUPPLIER_WRITE,
            ApiAction.ORDER_WRITE,
            ApiAction.PAYMENT_WRITE,
            ApiAction.FULFILMENT_WRITE,
            ApiAction.BUSINESS_READ,
            ApiAction.DIAGNOSTICS_READ,
        }
    ),
    RoleName.ANALYST: frozenset(
        {ApiAction.AGENT_RUN, ApiAction.BUSINESS_READ, ApiAction.DIAGNOSTICS_READ}
    ),
    RoleName.REVIEWER: frozenset(
        {
            ApiAction.APPROVAL_RESOLVE,
            ApiAction.REVIEW_RESOLVE,
            ApiAction.BUSINESS_READ,
            ApiAction.AUDIT_READ,
            ApiAction.DIAGNOSTICS_READ,
        }
    ),
    #: Read-only really is read-only: every read except the audit trail, which
    #: carries the identity of whoever performed each action.
    RoleName.VIEWER: frozenset({ApiAction.BUSINESS_READ, ApiAction.DIAGNOSTICS_READ}),
    RoleName.SYSTEM: frozenset(
        {
            ApiAction.OBJECTIVE_WRITE,
            ApiAction.AGENT_RUN,
            ApiAction.PIPELINE_RUN,
            ApiAction.INCIDENT_WRITE,
            ApiAction.JOB_WRITE,
            ApiAction.BUSINESS_READ,
            ApiAction.DIAGNOSTICS_READ,
        }
    ),
}


def role_can(role: RoleName | None, action: ApiAction) -> bool:
    """Deny by default, including when there is no role at all."""
    if role is None:
        return False
    return action in API_ROLE_ACTIONS.get(role, frozenset())
