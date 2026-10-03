"""La validación de arranque del techo de una llamada externa (Milestone 45, ADR 0029 §3 y §9).

El arranque **falla cerrado** —la API y cada worker— si la configuración de la reconciliación no se sostiene:

- **Siempre:** un techo configurado que no sea positivo (lo impide el propio ajuste).
- **Con un proveedor de escritura no simulado** (cobros, fulfillment, anuncios o marketplaces fuera de `mock`):
`EXTERNAL_CALL_MAX_SECONDS` **tiene que estar
  configurado explícitamente** (no hay valor por defecto fuera de la simulación), el adaptador tiene que **declarar
  su timeout efectivo** (`max_call_seconds`)
  y este no puede ser mayor que el techo configurado. El techo se define a partir del proveedor real: su timeout
  documentado, el timeout efectivo del cliente
  HTTP, un margen operacional y la política de `UNKNOWN_OUTCOME`.
- **Con la reconciliación encendida:** el umbral del barrido de acciones tiene que superar el techo con margen:
  `reconcile_actions_older_than_minutes × 60 ≥ 2 × techo + arriendo de un trabajo`.

Nada de esto interpreta superar un umbral como un fallo confirmado: `CALLING` abandonada pasa a `UNKNOWN_OUTCOME` y
la seguridad no depende de estas cifras (compare-and-set
y respuesta tardía). Lo que se valida es que la configuración sea **coherente**, no que el código garantice un techo
que ninguna capa aplica todavía.
"""

from collections.abc import Mapping

from app.core.config import Settings
from app.integrations.ports import IntegrationDomain, ProviderKind
from app.integrations.registry import ProviderRegistry
from app.jobs.queue import DEFAULT_LEASE_SECONDS

#: Los dominios cuyos adaptadores escriben fuera del sistema.
WRITE_DOMAINS = (
    IntegrationDomain.PAYMENTS,
    IntegrationDomain.FULFILMENT,
    IntegrationDomain.ADS,
    IntegrationDomain.MARKETPLACES,
)


class ReconciliationConfigError(RuntimeError):
    """La configuración de la reconciliación no se sostiene: el proceso no arranca."""


def validate_reconciliation(settings: Settings, adapters: Mapping[str, object] | None = None) -> None:
    """Comprueba la configuración. `adapters` son los adaptadores de escritura **no simulados** (nombre → adaptador);
    vacío o `None` si no hay."""
    problems: list[str] = []
    ceiling = settings.effective_external_call_max_seconds
    real_writers = dict(adapters or {})

    if ceiling is None:
        problems.append(
            "EXTERNAL_CALL_MAX_SECONDS must be configured explicitly when a write provider is not simulated: "
            "derive it from the provider's documented timeout, the effective HTTP client timeout, an operational "
            "margin and the UNKNOWN_OUTCOME policy"
        )
    else:
        for name, adapter in sorted(real_writers.items()):
            declared = getattr(adapter, "max_call_seconds", None)
            if not isinstance(declared, int) or isinstance(declared, bool) or declared < 1:
                problems.append(f"the adapter of {name} must declare its effective call timeout (max_call_seconds)")
            elif declared > ceiling:
                problems.append(
                    f"the adapter of {name} declares a call timeout of {declared}s, "
                    f"above EXTERNAL_CALL_MAX_SECONDS={ceiling}s"
                )
        if settings.reconciliation_enabled:
            threshold = settings.reconcile_actions_older_than_minutes * 60
            needed = 2 * ceiling + DEFAULT_LEASE_SECONDS
            if threshold < needed:
                problems.append(
                    f"RECONCILE_ACTIONS_OLDER_THAN_MINUTES ({settings.reconcile_actions_older_than_minutes} min = "
                    f"{threshold}s) must be at least 2 x the external call ceiling ({ceiling}s) plus the job lease "
                    f"({DEFAULT_LEASE_SECONDS}s) = {needed}s: an action could be taken for abandoned while its call "
                    "is legitimately in flight"
                )

    if problems:
        raise ReconciliationConfigError("invalid reconciliation configuration: " + "; ".join(problems))


def validate_reconciliation_for_startup(settings: Settings) -> None:
    """La comprobación de arranque de la API y de los workers: resuelve los adaptadores de escritura no simulados y
    los valida."""
    registry = ProviderRegistry(settings)
    adapters = {
        domain.value: registry.resolve(domain)
        for domain in WRITE_DOMAINS
        if settings.provider_kinds[domain] is not ProviderKind.MOCK
    }
    validate_reconciliation(settings, adapters)
