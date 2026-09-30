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


class IdempotencyConflictError(AmazonaError):
    """Raised when an `Idempotency-Key` that was already used comes with a
    different payload: it is a different request hiding behind the same key."""


class BudgetExhaustedError(AmazonaError):
    """Raised when a spend that fitted when it was assessed no longer fits when it is reserved:
    another request took the budget in between."""
