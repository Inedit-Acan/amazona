"""Batería de conformidad de un adaptador con efecto (hardening pre-M44, ADR 0024).

Módulo auxiliar de tests, **no** un test. Es lo que cualquier adaptador que **escriba** en un proveedor —el primero de
M44 y todos los que vengan— tendrá que pasar con su transporte falso, antes de que el pipeline lo use:

- declara su nombre y si es idempotente;
- si dice que **sí** lo es, repetir la misma clave **no repite el efecto** y devuelve la misma respuesta, mientras que
  otra clave es otra operación;
- si dice que **no**, no se le manda clave (lo comprueba el servicio, no el adaptador);
- si sabe consultar (`lookup`), devuelve la respuesta de lo que ejecutó y `None` solo de lo que no existe.

`effects` es lo único que importa para saber si algo ocurrió «de verdad»: cuántos efectos ha producido el proveedor. Sin
él (un adaptador simulado no produce ninguno) solo se comprueban las respuestas.
"""

from collections.abc import Callable

from app.actions.contract import (
    ActionRequest,
    ActionResponse,
    ExternalActionAdapter,
    LookupCapableAdapter,
    derive_idempotency_key,
)


def request_for(adapter: ExternalActionAdapter, key_site: str = "site-a", sequence: int = 1) -> ActionRequest:
    """La petición que el servicio mandaría: con clave solo si el adaptador la declara admitir."""
    key = derive_idempotency_key(key_site, sequence) if adapter.supports_idempotency else None
    return ActionRequest(
        provider=adapter.name,
        operation="activate_ads",
        idempotency_key=key,
        amount=10.0,
        payload={"platform": "meta"},
        correlation_id="corr-1",
    )


def assert_adapter_honours_contract(adapter: ExternalActionAdapter, effects: Callable[[], int] | None = None) -> None:
    assert isinstance(adapter, ExternalActionAdapter), "the adapter does not implement the contract"
    assert isinstance(adapter.name, str) and adapter.name, "the adapter must name itself"
    assert isinstance(adapter.supports_idempotency, bool), "idempotency must be declared, not inferred"

    request = request_for(adapter)
    first = adapter.execute(request)
    assert isinstance(first, ActionResponse), "execute must answer with an ActionResponse"

    if adapter.supports_idempotency:
        before = effects() if effects else None
        again = adapter.execute(request)  # la misma clave, otra vez
        assert again.reference == first.reference, "the same key must give back the same operation"
        if effects:
            assert effects() == before, "an idempotent adapter repeated the effect for the same key"

        other = adapter.execute(request_for(adapter, key_site="site-b"))  # otra clave: otra operación
        assert other.reference != first.reference, "a different key must be a different operation"
        if effects:
            assert effects() == before + 1, "a different key must produce its own effect"

    if isinstance(adapter, LookupCapableAdapter):
        found = adapter.lookup(request.idempotency_key or "")
        if adapter.supports_idempotency:
            assert found is not None, "lookup must find what the adapter executed"
            assert found.reference == first.reference, "lookup must return the response of what the adapter executed"
        assert adapter.lookup("amz-never-executed") is None, "lookup must answer None for what does not exist"
