class AmazonaError(Exception):
    """Base class for domain errors raised across AMAZONA services."""


class NotFoundError(AmazonaError):
    """Raised when a requested domain record does not exist."""


class ValidationError(AmazonaError, ValueError):
    """Raised when a domain rule refuses the data it was given.

    Hereda de `ValueError` a propósito (Milestone 39): las reglas del dominio de
    proveedores —un Incoterm que no existe, un «verificado» sin emisor, un precio
    sin moneda— fallan al **construir** el objeto, como el techo de confianza de
    las señales del Milestone 37, y quien las escribe las espera como un
    `ValueError`. Heredar de las dos deja que sigan siéndolo y que además el API
    las convierta en un 422 en vez de en un 500.
    """


class NoAgentAvailableError(AmazonaError):
    """Raised when no registered agent can currently serve a capability."""


class AgentIOValidationError(AmazonaError):
    """Raised when an agent's input or output doesn't match its declared schema."""


class PipelineDisabledError(AmazonaError):
    """Raised when a new pipeline run is attempted while the kill switch is disabled."""


class PipelineRunStateError(AmazonaError):
    """Raised when a pipeline run cannot do what is being asked of it in the
    state it is in: resuming one that is still running, cancelling one that
    already finished, or reaching a step whose input the run never produced."""


class PipelineReviewNotPendingError(AmazonaError):
    """Raised when acting on a pipeline review that is already resolved."""


class IncidentNotOpenError(AmazonaError):
    """Raised when resolving an incident that isn't OPEN."""


class IdempotencyKeyRequiredError(AmazonaError):
    """Raised when an operation that can have an external effect is requested
    without an `Idempotency-Key`: a retry after a timeout could not be told
    apart from a second request."""

    #: Código legible por máquina que viaja en la respuesta HTTP: el cliente no clasifica por texto.
    code = "idempotency_key_required"


class IdempotencyConflictError(AmazonaError):
    """Raised when an `Idempotency-Key` that was already used comes with a
    different payload: it is a different request hiding behind the same key."""

    #: Código legible por máquina que viaja en la respuesta HTTP: el cliente no clasifica por texto.
    code = "idempotency_conflict"


class IdempotencyInProgressError(AmazonaError):
    """Raised when an `Idempotency-Key` belongs to a request that has not finished (or whose process stopped
    before finishing). It is never run again on a timer: repeating it could repeat an effect."""

    #: Código legible por máquina que viaja en la respuesta HTTP: el cliente no clasifica por texto.
    code = "idempotency_in_progress"


class IdempotencyOutcomeUnknownError(AmazonaError):
    """Raised when an `Idempotency-Key` belongs to a request that failed in a way that does not say whether it
    took effect. The key is not reusable: a person checks and uses a new one."""

    #: Código legible por máquina que viaja en la respuesta HTTP: el cliente no clasifica por texto.
    code = "idempotency_outcome_unknown"


class BudgetExhaustedError(AmazonaError):
    """Raised when a spend that fitted when it was assessed no longer fits when it is reserved:
    another request took the budget in between."""


class ExternalActionFailedError(AmazonaError):
    """An external action failed and the provider confirmed it had no effect (or the request never left):
    its budget is released and it may be tried again as a new operation."""


class ExternalOutcomeUnknownError(AmazonaError):
    """An external action may have been executed and its result is not known. It is not retried blindly,
    its budget is not released and it is not declared a success: it needs reconciling."""


class PipelineOutcomeUnknownError(AmazonaError):
    """A pipeline step stopped on an external action whose outcome is unknown. The run is blocked until it is
    reconciled; it does not burn job attempts."""


class ConflictError(AmazonaError):
    """The request is valid but the thing it acts on is not in a state that allows it (someone else moved it first,
    or it is already done). It is a 409: nothing was changed."""
