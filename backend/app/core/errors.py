class AmazonaError(Exception):
    """Base class for domain errors raised across AMAZONA services."""


class NotFoundError(AmazonaError):
    """Raised when a requested domain record does not exist."""


class NoAgentAvailableError(AmazonaError):
    """Raised when no registered agent can currently serve a capability."""


class AgentIOValidationError(AmazonaError):
    """Raised when an agent's input or output doesn't match its declared schema."""


class PipelineDisabledError(AmazonaError):
    """Raised when a new pipeline run is attempted while the kill switch is disabled."""


class PipelineReviewNotPendingError(AmazonaError):
    """Raised when acting on a pipeline review that is already resolved."""
