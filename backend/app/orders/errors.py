"""Los errores del núcleo de pedidos (Milestone 44, ADR 0028). Todos son un 409: la petición es válida, pero lo que
toca no está en un estado que lo permita, o el gate no la deja pasar. No se cambió nada."""

from app.core.errors import ConflictError


class OperationNotAllowedError(ConflictError):
    """El ActionGate o una regla de dominio no dejan ejecutar la operación, y dicen por qué.

    Cuando el gate responde `REQUIRE_APPROVAL`, M44 **no** tiene bandeja de aprobación de pedidos (ADR 0028 §7):
    la operación no se ejecuta y los motivos se devuelven tal cual."""

    def __init__(self, message: str, *, reasons: list[str] | None = None, requires_approval: bool = False) -> None:
        super().__init__(message)
        self.reasons = reasons or []
        self.requires_approval = requires_approval


class OutcomeUnknownBlockError(ConflictError):
    """Hay una operación de resultado desconocido que bloquea esta: se reconcilia o se resuelve antes (ADR 0024)."""
