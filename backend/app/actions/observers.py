"""Quien refleja en su dominio lo que le pasa a una acción externa (Milestone 44, ADR 0028 §3).

Una `ExternalAction` es la verdad de **qué se hizo hacia fuera**. Un pedido, un cobro, un reembolso o un envío
son la verdad de **qué significa eso para el negocio**. Si el dominio se actualizara después de la acción, en
otra transacción, quedaría una ventana en la que la acción dice «posiblemente enviada» y el dominio sigue
diciendo «nada enviado»: la ambigüedad que el hardening quitó de la acción volvería a entrar por el dominio.

Un observador se llama **dentro de la transacción de cada transición**, antes del `commit`, así que la acción y
su proyección al dominio se confirman juntas o no se confirma ninguna. Cubre todos los caminos que mueven una
acción: `begin_call`, `finish`, el barrido de huérfanas, `reconcile` (consulta o repetición con la misma clave)
y `resolve` (una persona). Por eso `reconcile-actions` y `resolve-action` dejan el dominio consistente sin saber
nada de pedidos.

Un observador solo atiende las acciones cuya `reference` empieza por su prefijo. El pipeline no registra
ninguno y no cambia.

Si un observador falla, la excepción sube **antes** del commit y la transición no se confirma: una acción jamás
queda movida con su dominio sin mover.
"""

import importlib
from typing import Protocol

from sqlalchemy.orm import Session

from app.actions.contract import ActionResponse
from app.db.models.external_action import ExternalAction


class ActionObserver(Protocol):
    def on_transition(
        self,
        db: Session,
        action: ExternalAction,
        *,
        previous: str,
        current: str,
        response: ActionResponse | None,
    ) -> None:
        """`previous` y `current` son valores de `ActionStatus`. `response` es la respuesta del proveedor
        cuando la transición la trae (el cierre de una llamada o una consulta que encontró la operación)."""
        ...


#: Los observadores del producto: `(prefijo de la referencia, "módulo:Clase")`. Se cargan la primera vez que se
#: necesitan y se instancian sin argumentos (no guardan estado). Un import perezoso evita el ciclo entre este
#: paquete y los dominios que lo usan.
REGISTERED: list[tuple[str, str]] = [
    ("order_payment:", "app.payments.projection:PaymentOpenObserver"),
    ("order_refund:", "app.payments.refund_projection:RefundActionObserver"),
    ("order_fulfilment:", "app.orders.fulfilment_projection:FulfilmentActionObserver"),
]

_loaded: dict[str, ActionObserver] = {}


def _load(path: str) -> ActionObserver:
    cached = _loaded.get(path)
    if cached is None:
        module_name, _, class_name = path.partition(":")
        cached = getattr(importlib.import_module(module_name), class_name)()
        _loaded[path] = cached
    return cached


def observers_for(reference: str, injected: list[tuple[str, ActionObserver]] | None = None) -> list[ActionObserver]:
    """Los observadores que atienden esta referencia. `injected` sustituye al registro (pruebas)."""
    if injected is not None:
        return [observer for prefix, observer in injected if reference.startswith(prefix)]
    return [_load(path) for prefix, path in REGISTERED if reference.startswith(prefix)]
