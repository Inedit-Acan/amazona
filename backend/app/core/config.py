from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.costs.policy import SpendLimit
from app.integrations.ports import IntegrationDomain, ProviderKind

# Anchored to backend/.env regardless of the process's current working
# directory. A relative "env_file" is resolved against cwd, and
# pydantic-settings silently skips a missing .env instead of erroring —
# so invoking alembic/uvicorn/pytest from anywhere other than backend/
# (e.g. the repo root) used to silently fall back to the hardcoded
# localhost default below instead of failing loudly.
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Environment(StrEnum):
    """Where this process is running. The distinction is what decides whether
    identity is enforced and whether simulated data may be used at all
    (Milestone 29, ADR 0007).

    - development: local work. Mocks allowed, identity optional.
    - test: automated suites. Controlled fixtures.
    - demo: demonstrations. Demo data allowed, but labelled as such.
    - staging: real integrations in sandbox. Identity enforced.
    - production: real operation. Identity enforced, no demo data for
      operational decisions.
    """

    DEVELOPMENT = "development"
    TEST = "test"
    DEMO = "demo"
    STAGING = "staging"
    PRODUCTION = "production"


#: Environments that run against real systems and therefore refuse anonymous
#: mutations and client-declared identity.
_ENFORCING = frozenset({Environment.STAGING, Environment.PRODUCTION})


class WikimediaSettings(BaseModel):
    """Ajustes del adaptador de Wikimedia Pageviews (Milestone 34).

    El tope de peticiones existe por el arriendo de 60 s del runtime (ADR 0009):
    la investigación corre dentro de un trabajo, y una categoría con muchos
    términos no puede acercarse a ese límite.
    """

    months: int = 12
    max_requests: int = 8
    timeout_seconds: float = 6.0
    #: Si se pregunta a Wikimedia cómo se llama cada artículo en el idioma del
    #: mercado (Milestone 38). Con esto desactivado, un mercado que no sea el del
    #: proyecto por defecto se queda sin señal en vez de medir el artículo
    #: equivocado.
    resolve_languages: bool = True


class EbaySettings(BaseModel):
    """Ajustes del adaptador de eBay Browse (Milestone 37).

    Las claves son de un **keyset de desarrollador gratuito**: no hay nada que
    pagar y no hace falta cuenta de vendedor. Vacías por defecto, y configurar
    eBay como fuente real sin ellas falla al arrancar en vez de fallar a mitad de
    una investigación (ADR 0008 §4).
    """

    client_id: str = ""
    client_secret: str = ""
    #: `false` apunta al entorno de pruebas de eBay. Es lo que da contenido real a
    #: `ProviderKind.SANDBOX`, que hasta el Milestone 37 era una casilla vacía.
    use_production: bool = True
    max_requests: int = 8
    timeout_seconds: float = 6.0


class SpendLimitSettings(BaseModel):
    """Lo autorizado para un proveedor. Cualquier campo a `None` es «sin techo
    por esa vía», no «cero»."""

    currency: str = "EUR"
    max_cost_per_run: float | None = None
    max_cost_per_day: float | None = None
    max_units_per_day: int | None = None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE, extra="ignore", env_nested_delimiter="__"
    )

    environment: Environment = Environment.DEVELOPMENT
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://amazona:amazona@localhost:5432/amazona"
    redis_url: str = "redis://localhost:6379/0"

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: list[str] = ["http://localhost:3000"]

    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""

    # --- Proveedores externos (Milestone 30) ---
    # Qué implementación se usa en cada dominio. "mock" son fixtures
    # deterministas: valen para desarrollo, demos y tests, y nunca para una
    # decisión operativa, así que staging y production se niegan a arrancar con
    # ellas (ADR 0008).
    product_intelligence_provider: ProviderKind = ProviderKind.MOCK
    #: Qué fuentes reales se usan y **en qué orden** cuando el dominio está en
    #: `real` o `composite` (Milestone 37, ADR 0015). Son nombres de adaptador, no
    #: clases: quitar un proveedor es quitarlo de esta lista, que es lo que hace
    #: reversible la elección.
    #:
    #: El orden es el de preferencia: el primero que dé una señal de un tipo
    #: manda, y los siguientes solo rellenan lo que falte (ADR 0012 §6).
    product_intelligence_real_sources: list[str] = ["wikimedia-pageviews"]
    #: Ajustes por proveedor, cada uno en su espacio de nombres
    #: (`WIKIMEDIA__MONTHS`, `EBAY__CLIENT_ID`). Antes vivían sueltos en este
    #: objeto —`wikimedia_months`—, y con dos proveedores eso se convierte en un
    #: cajón desastre donde no se sabe qué ajuste es de quién.
    wikimedia: WikimediaSettings = WikimediaSettings()
    ebay: EbaySettings = EbaySettings()
    #: Lo que el propietario **ha autorizado** gastar, por proveedor. Vacío
    #: significa que no hay autorización, y sin autorización un proveedor de pago
    #: no se llama (plan maestro §25). No se escribe aquí ningún techo futuro:
    #: esto se rellena por configuración el día que haya una decisión de gasto.
    api_spend_limits: dict[str, SpendLimitSettings] = {}
    suppliers_provider: ProviderKind = ProviderKind.MOCK
    regulatory_provider: ProviderKind = ProviderKind.MOCK
    #: Cada cuántos días se vuelve a comprobar una norma contra la fuente (ADR
    #: 0019). **Política operativa nuestra, no un plazo jurídico**: superarlo hace
    #: que Legal pida revisión hasta la siguiente comprobación, y no dice nada de
    #: si la norma sigue en vigor.
    legal_anchor_recheck_days: int = 30
    #: De dónde salen los tipos de cambio además de los que declara una persona
    #: (Milestone 42, ADR 0020). `mock` (por defecto) es exactamente el sistema de
    #: antes: declaradas más fixture. `real` añade las referencias del BCE ya
    #: guardadas —no llama a nadie— y habilita el refresco.
    exchange_rate_provider: ProviderKind = ProviderKind.MOCK
    #: Cuántos días puede tener una referencia del BCE. Las tasas declaradas a mano
    #: conservan sus 30 días (Milestone 40). No puede superarlos.
    ecb_rate_max_age_days: int = Field(default=7, ge=1, le=30)
    ads_provider: ProviderKind = ProviderKind.MOCK
    marketplaces_provider: ProviderKind = ProviderKind.MOCK

    #: `aud` claim Supabase puts in the access tokens it issues. Configurable
    #: because a self-hosted GoTrue can be told to use another one.
    jwt_audience: str = "authenticated"

    # Explicit opt-in for the non-enforcing environments, deliberately separate
    # from is_supabase_configured: merely having Supabase credentials in .env
    # (to reach its Postgres or its REST API) must never silently start
    # requiring auth on every mutating endpoint while developing. In staging and
    # production auth is enforced regardless of this flag — see enforces_auth.
    require_auth: bool = False

    @property
    def is_supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_anon_key)

    @property
    def enforces_auth(self) -> bool:
        """Mutating endpoints demand a verified bearer token."""
        return self.environment in _ENFORCING or self.require_auth

    @property
    def enforces_rbac(self) -> bool:
        """The actor's role decides what it may do. Only the environments that
        touch real systems: in development an authenticated user is enough, so
        a local session without a seeded role keeps working as before."""
        return self.environment in _ENFORCING

    @property
    def allows_declared_actor(self) -> bool:
        """Whether an `actor` field in a request body may be trusted. Never in
        staging or production (plan maestro §P0.3)."""
        return self.environment not in _ENFORCING

    @property
    def provider_kinds(self) -> dict[IntegrationDomain, ProviderKind]:
        return {
            IntegrationDomain.PRODUCT_INTELLIGENCE: self.product_intelligence_provider,
            IntegrationDomain.SUPPLIERS: self.suppliers_provider,
            IntegrationDomain.REGULATORY: self.regulatory_provider,
            IntegrationDomain.ADS: self.ads_provider,
            IntegrationDomain.MARKETPLACES: self.marketplaces_provider,
        }

    @property
    def spend_limits(self) -> dict[str, SpendLimit]:
        """Los límites autorizados, en la forma que entiende la función pura."""
        return {
            provider: SpendLimit(
                provider=provider,
                currency=limit.currency,
                max_cost_per_run=limit.max_cost_per_run,
                max_cost_per_day=limit.max_cost_per_day,
                max_units_per_day=limit.max_units_per_day,
            )
            for provider, limit in self.api_spend_limits.items()
        }

    @property
    def allows_simulated_providers(self) -> bool:
        """Whether fixture data may back an agent here. Everywhere but staging
        and production (plan maestro §P0.1)."""
        return self.environment not in _ENFORCING

    @property
    def jwt_issuer(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/auth/v1" if self.supabase_url else ""

    def validate_for_startup(self) -> None:
        """Refuses to start a misconfigured enforcing environment. Failing loudly
        here is the whole point: a production deployment that silently accepts
        anonymous mutations is worse than one that does not boot."""
        if self.environment not in _ENFORCING:
            return

        problems: list[str] = []
        if not self.supabase_url:
            problems.append("SUPABASE_URL is required to verify access tokens")
        if not self.is_supabase_configured:
            problems.append("SUPABASE_ANON_KEY is required")
        if self.environment is Environment.PRODUCTION:
            local = [origin for origin in self.cors_origins if "localhost" in origin or "127.0.0.1" in origin]
            if local:
                problems.append(f"CORS_ORIGINS must not include local origins in production: {local}")

        if problems:
            raise RuntimeError(f"invalid configuration for {self.environment}: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()
