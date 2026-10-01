"""El contrato entre AMAZONA y quien ejecuta una acción con efecto fuera del sistema.

Un adaptador de **lectura** (precios, normativa, tipos de cambio) no pasa por aquí: si falla, se
vuelve a leer. Esto es para lo que **escribe** en un proveedor —publicar, activar publicidad,
gastar— donde un timeout puede significar «el proveedor lo hizo y no recibimos la respuesta».

Tres resultados, y solo tres, porque son los tres que cambian lo que se puede hacer después:

- **SUCCEEDED**: el proveedor lo confirmó. El presupuesto se compromete.
- **FAILED_CONFIRMED**: se sabe que no hubo efecto (el proveedor lo rechazó, o la petición no
  llegó a salir). Se puede liberar el presupuesto y, si se quiere, intentarlo de nuevo como
  una operación nueva.
- **UNKNOWN_OUTCOME**: pudo ejecutarse y no conocemos la respuesta. No se reintenta a ciegas, no se
  libera el presupuesto y no se declara éxito.

Cualquier excepción de un adaptador que no sea una de las dos que dicen «no hubo efecto» se
trata como UNKNOWN_OUTCOME: lo conservador no es suponer que falló, es reconocer que no se sabe.
"""

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable


class ActionStatus(StrEnum):
    #: La operación existe y tiene su reserva, pero la petición **todavía no ha salido**.
    PENDING = "PENDING"
    #: Confirmado (commit) que la petición está a punto de salir o ha salido.
    CALLING = "CALLING"
    SUCCEEDED = "SUCCEEDED"
    FAILED_CONFIRMED = "FAILED_CONFIRMED"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"


#: Las que bloquean abrir otra operación en el mismo sitio: están sin resolver.
OPEN_STATUSES: frozenset[ActionStatus] = frozenset(
    {ActionStatus.PENDING, ActionStatus.CALLING, ActionStatus.UNKNOWN_OUTCOME}
)


class ProviderError(Exception):
    """Base de lo que un adaptador puede decir que salió mal."""


class ProviderRejectedError(ProviderError):
    """El proveedor respondió y se negó. **No hubo efecto**."""


class ProviderUnreachableError(ProviderError):
    """La petición no llegó a salir (conexión rechazada, DNS, sin red). **No hubo efecto**."""


class ProviderTimeoutError(ProviderError):
    """La petición pudo llegar y no hubo respuesta a tiempo. **No se sabe** si hubo efecto."""


@dataclass(frozen=True)
class ActionRequest:
    provider: str
    operation: str
    #: La clave estable que el proveedor puede usar para no repetir el efecto. `None` si el adaptador
    #: no admite claves idempotentes: no se manda una clave que no se va a respetar.
    idempotency_key: str | None
    amount: float | None
    payload: dict = field(default_factory=dict)
    correlation_id: str | None = None


@dataclass(frozen=True)
class ActionResponse:
    reference: str | None = None
    detail: dict = field(default_factory=dict)


@runtime_checkable
class ExternalActionAdapter(Protocol):
    """Quien ejecuta la acción. Las capacidades se **declaran**, no se infieren."""

    name: str
    #: Si repetir `execute` con la misma `idempotency_key` **no repite el efecto**. Un adaptador que
    #: dice `True` se compromete a ello; uno que dice `False` queda registrado como tal, y su UNKNOWN_OUTCOME
    #: solo se resuelve con `lookup` o con una persona.
    supports_idempotency: bool

    def execute(self, request: ActionRequest) -> ActionResponse:
        """Hace la acción. Lanza `ProviderRejectedError` / `ProviderUnreachableError` si **no** hubo
        efecto, `ProviderTimeoutError` (u otra cosa) si no se sabe."""
        ...


@runtime_checkable
class LookupCapableAdapter(ExternalActionAdapter, Protocol):
    """Un adaptador que además sabe **consultar** si ejecutó una operación, por su clave.

    Es la única forma en que el sistema puede afirmar «no hubo efecto» tras un timeout sin que lo haga una
    persona: `lookup` devuelve la respuesta de la operación si existe y `None` si el proveedor asegura que no
    existe. No es lo mismo que no poder alcanzar al proveedor: eso es un `ProviderError`, no un `None`."""

    def lookup(self, idempotency_key: str) -> ActionResponse | None: ...


def derive_idempotency_key(reference: str, sequence: int) -> str:
    """La clave hacia el proveedor: de `(sitio, operación)`, nada más.

    Es estable entre reintentos, reinicios y reanudaciones de la **misma** operación, y distinta para una
    operación nueva (otra `sequence`). No lleva el intento ni la fecha —cambiarían en cada reintento— ni
    ningún dato de nadie: es un resumen opaco."""
    digest = hashlib.sha256(f"amazona-action:{reference}#{sequence}".encode()).hexdigest()
    return f"amz-{digest[:48]}"


def request_fingerprint(provider: str, operation: str, amount: float | None, payload: dict) -> str:
    """Huella canónica de lo que se va a pedir: dos operaciones del mismo sitio con huellas distintas no
    son la misma petición reintentada."""
    canonical = json.dumps(
        {"provider": provider, "operation": operation, "amount": amount, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class SimulatedAdapter:
    """El «proveedor» de un despliegue simulado: no sale nada de AMAZONA. Cumple el contrato (y por eso el
    pipeline recorre el mismo ciclo de vida con proveedores simulados que con reales) y declara que sí es
    idempotente, porque no tiene efecto que repetir."""

    name = "simulated"
    supports_idempotency = True

    def execute(self, request: ActionRequest) -> ActionResponse:
        return ActionResponse(reference=f"simulated:{request.idempotency_key}", detail={"simulated": True})
