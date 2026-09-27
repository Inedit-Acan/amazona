"""Ejecuta la comparación y la guarda (Milestone 35, ADR 0013).

La regla que decide dónde puede correr esto: comparar exige **ejecutar el
mock**, y la ADR 0008 prohíbe los datos simulados en los entornos que tocan
sistemas reales. Hacer una excepción «solo para un informe» sería justo la
clase de excepción que vacía una regla, así que aquí no se hace: en `staging` y
`production` la comparación se rechaza diciendo por qué.
"""

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import AmazonaError
from app.core.ids import new_correlation_id
from app.db.models.audit import AuditLog
from app.db.models.research_comparison import ResearchComparison
from app.integrations.ports import IntegrationDomain, ProductSignalProvider, ProviderKind
from app.integrations.product_intelligence.mock import MockProductSignalProvider
from app.integrations.registry import ProviderRegistry
from app.research.comparison import ComparisonReport, compare

COMPARISON_ACTOR = "research-comparison"


class ComparisonNotAllowedError(AmazonaError):
    """Comparar exige ejecutar el mock, y aquí los datos simulados no se
    admiten (ADR 0008)."""


class ResearchComparisonService:
    def __init__(
        self,
        db: Session,
        *,
        settings: Settings | None = None,
        baseline: ProductSignalProvider | None = None,
        candidate: ProductSignalProvider | None = None,
    ) -> None:
        self._db = db
        self._settings = settings or get_settings()
        self._baseline = baseline
        self._candidate = candidate

    def run(
        self,
        *,
        category: str,
        market: str = "us",
        max_results: int = 5,
        keywords: list[str] | None = None,
        actor: str | None = None,
    ) -> ResearchComparison:
        if not self._settings.allows_simulated_providers:
            raise ComparisonNotAllowedError(
                f"comparing against the mock would run simulated data in "
                f"{self._settings.environment}, which ADR 0008 does not allow"
            )

        baseline = self._baseline or MockProductSignalProvider()
        candidate = self._candidate or self._configured_candidate()

        report = compare(
            category=category,
            market=market,
            baseline_provider=baseline.name,
            baseline=baseline.discover(
                category=category, keywords=keywords or [], market=market, max_results=max_results
            ),
            candidate_provider=candidate.name,
            candidate=candidate.discover(
                category=category, keywords=keywords or [], market=market, max_results=max_results
            ),
        )
        return self._persist(report, actor=actor)

    # --- Interno -----------------------------------------------------------

    def _configured_candidate(self) -> ProductSignalProvider:
        """Contra qué se compara el mock: el proveedor configurado, y si el
        configurado **es** el mock, la fuente real directamente — comparar algo
        consigo mismo no informa de nada."""
        registry = ProviderRegistry(self._settings)
        kind = registry.kind_for(IntegrationDomain.PRODUCT_INTELLIGENCE)
        if kind is ProviderKind.MOCK:
            from app.integrations.registry import BUILDERS

            builder = BUILDERS[(IntegrationDomain.PRODUCT_INTELLIGENCE, ProviderKind.REAL)]
            return builder(self._settings)  # type: ignore[return-value]
        return registry.resolve(IntegrationDomain.PRODUCT_INTELLIGENCE)  # type: ignore[return-value]

    def _persist(self, report: ComparisonReport, *, actor: str | None) -> ResearchComparison:
        correlation_id = new_correlation_id()
        row = ResearchComparison(
            category=report.category,
            market=report.market,
            baseline_provider=report.baseline.provider,
            candidate_provider=report.candidate.provider,
            summary=report.as_dict(),
            correlation_id=correlation_id,
        )
        self._db.add(row)
        self._db.add(
            AuditLog(
                actor=actor or COMPARISON_ACTOR,
                action="research.compare",
                resource=f"research_comparison:{correlation_id}",
                before=None,
                after={
                    "category": report.category,
                    "market": report.market,
                    "baseline": report.baseline.provider,
                    "candidate": report.candidate.provider,
                    "shared": len(report.shared),
                    "verdict": report.verdict,
                },
                correlation_id=correlation_id,
            )
        )
        self._db.commit()
        self._db.refresh(row)
        return row
