"""Apoyo compartido de las pruebas de acciones externas (hardening pre-M44, ADR 0024).

Módulo auxiliar de tests, **no** un test: un proveedor **falso** que se comporta como se le dice y lleva la
cuenta de los efectos que ha producido «en el mundo real». Ningún test habla con un proveedor de verdad.

Cada llamada a `execute` consume el siguiente comportamiento de la lista (por defecto, `ok`):

- `ok`: ejecuta y responde.
- `reject`: el proveedor se niega. **No hay efecto.**
- `unreachable`: la petición no llega a salir. **No hay efecto.**
- `timeout_before`: se agota el tiempo y el proveedor **no** llegó a ejecutar (pero desde fuera no se sabe).
- `timeout_after`: el proveedor **ejecutó** y la respuesta se perdió.
- `die`: el proceso muere en mitad de la llamada (una `KeyboardInterrupt`, que el código no captura).

`effects` es lo único que importa para saber si algo ocurrió «de verdad»: una entrada por efecto. Con
`supports_idempotency=True` el proveedor deduplica por clave (repetir la misma clave no añade un efecto);
con `False` no hay forma de deduplicar y cada llamada que ejecuta añade el suyo.
"""

from collections import deque

from app.actions.contract import (
    ActionRequest,
    ActionResponse,
    ProviderRejectedError,
    ProviderTimeoutError,
    ProviderUnreachableError,
)


class FakeProviderAdapter:
    def __init__(
        self,
        *,
        name: str = "fake-provider",
        supports_idempotency: bool = True,
        behaviors=None,
        only_operation: str | None = None,
    ) -> None:
        self.name = name
        self.supports_idempotency = supports_idempotency
        self.behaviors = deque(behaviors or [])
        #: Si se indica, los comportamientos solo se aplican a esa operación; las demás van siempre bien.
        self.only_operation = only_operation
        self.effects: list[str] = []
        self.effect_operations: list[str] = []
        self.requests: list[ActionRequest] = []
        self._by_key: dict[str, ActionResponse] = {}

    def execute(self, request: ActionRequest) -> ActionResponse:
        self.requests.append(request)
        scripted = self.only_operation is None or request.operation == self.only_operation
        behavior = self.behaviors.popleft() if self.behaviors and scripted else "ok"
        if behavior == "reject":
            raise ProviderRejectedError("the provider refused the request")
        if behavior == "unreachable":
            raise ProviderUnreachableError("could not connect to the provider")
        if behavior == "timeout_before":
            raise ProviderTimeoutError("timed out before the provider executed anything")
        if behavior == "die":
            raise KeyboardInterrupt("the process died in the middle of the call")

        key = request.idempotency_key
        if key is not None and key in self._by_key:
            response = self._by_key[key]  # el proveedor reconoce la clave y no repite el efecto
        else:
            self.effects.append(key or f"unkeyed-{len(self.effects) + 1}")
            self.effect_operations.append(request.operation)
            response = ActionResponse(reference=f"remote-{len(self.effects)}")
            if key is not None:
                self._by_key[key] = response
        if behavior == "timeout_after":
            raise ProviderTimeoutError("the provider executed but the response was lost")
        return response

    @property
    def effect_count(self) -> int:
        return len(self.effects)

    def effects_of(self, operation: str) -> int:
        return self.effect_operations.count(operation)


class FakeLookupProviderAdapter(FakeProviderAdapter):
    """Un proveedor que además sabe decir, por la clave, si ejecutó una operación."""

    def lookup(self, idempotency_key: str) -> ActionResponse | None:
        return self._by_key.get(idempotency_key)
