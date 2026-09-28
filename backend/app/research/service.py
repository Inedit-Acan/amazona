import datetime
from typing import cast

from sqlalchemy.orm import Session

from app.agents.product_research import ProductResearchAgent
from app.core.config import get_settings
from app.costs.service import CostMeter
from app.db.models.audit import AuditLog
from app.db.models.product import Product
from app.db.models.product_analysis import ProductAnalysis
from app.db.models.product_identity_alias import ProductIdentityAlias
from app.db.models.product_signal import ProductSignal
from app.db.models.product_signal_observation import ProductSignalObservation
from app.integrations.ports import IntegrationDomain, ProductSignalProvider
from app.integrations.product_intelligence.identity import resolve
from app.integrations.registry import ProviderRegistry
from app.integrations.usage_rights import UsageRight, permits

RESEARCH_AGENT_ACTOR = "agent-product-research-1"


def _parse_observed_at(value: str | None) -> datetime.datetime:
    """La marca de tiempo de la señal, o ahora si el proveedor no la puso. No
    se inventa hacia atrás: una señal sin fecha es una señal de este momento."""
    if not value:
        return datetime.datetime.now(datetime.UTC)
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError:
        return datetime.datetime.now(datetime.UTC)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=datetime.UTC)


class ResearchService:
    """Runs the Product Research agent and persists every candidate as a
    first-class Product + ProductAnalysis, so a research run is
    reconstructable from the database, exactly like the rest of the
    system — not just an ephemeral agent call.

    Desde el Milestone 36 un candidato que ya existe **no crea otra fila**: se
    resuelve su identidad y sus señales se acumulan sobre el producto que ya
    estaba (ADR 0014). Cada ejecución sigue dejando su propio `ProductAnalysis`
    con su `correlation_id`, así que la historia por ejecución no se pierde."""

    def __init__(self, db: Session, agent: ProductResearchAgent | None = None) -> None:
        self._db = db
        #: Se guarda tal cual, **sin construir uno por defecto**: el agente de
        #: verdad se monta por ejecución, porque su proveedor necesita un contador
        #: de gasto atado a un `correlation_id` y eso no existe todavía aquí
        #: (Milestone 37, plan §25).
        self._agent = agent

    def _agent_for(self, correlation_id: str) -> ProductResearchAgent:
        """El agente de esta ejecución, con su contador de llamadas externas.

        Un agente inyectado manda: es lo que permite a un test poner una fuente
        de mentira. Cuando no hay, se monta el configurado y se le pasa el
        contador, de modo que **en el camino real ninguna llamada externa ocurre
        sin quedar anotada**.
        """
        if self._agent is not None:
            return self._agent
        meter = CostMeter(
            self._db, correlation_id=correlation_id, limits=get_settings().spend_limits
        )
        provider = ProviderRegistry().resolve(
            IntegrationDomain.PRODUCT_INTELLIGENCE, meter=meter
        )
        return ProductResearchAgent(trends_provider=cast(ProductSignalProvider, provider))

    def run_research(
        self,
        *,
        category: str,
        keywords: list[str] | None,
        max_results: int,
        correlation_id: str,
        market: str = "us",
    ) -> list[Product]:
        result = self._agent_for(correlation_id).run(
            {
                "category": category,
                "keywords": keywords or [],
                "max_results": max_results,
                "market": market,
            }
        )

        products: list[Product] = []
        reused = 0
        withheld: list[str] = []
        for candidate in result.data["candidates"]:
            product, was_reused = self._product_for(candidate, correlation_id)
            reused += int(was_reused)

            self._db.add(
                ProductAnalysis(
                    product_id=product.id,
                    analysis_type="research",
                    opportunity_score=candidate["opportunity_score"],
                    confidence=result.confidence,
                    data=candidate,
                    correlation_id=correlation_id,
                )
            )
            # Cada número, con de dónde salió (Milestone 34, plan maestro §8).
            # Sin esto, un valor medido y uno inventado son la misma fila.
            for signal in candidate.get("signals", []):
                # Guardar es un uso, y un uso necesita permiso (Milestone 37,
                # ADR 0015). Si la licencia del proveedor no lo autoriza —o nadie
                # la ha leído—, la señal no se persiste y se cuenta cuántas se
                # quedaron fuera: un dato que desaparece sin dejar rastro es peor
                # que un dato que falta.
                if not permits(signal["provider"], UsageRight.STORAGE):
                    withheld.append(signal["provider"])
                    continue
                row = ProductSignal(
                    product_id=product.id,
                    kind=signal["kind"],
                    value=signal["value"],
                    confidence=signal["confidence"],
                    provider=signal["provider"],
                    source=signal["source"],
                    query=signal["query"],
                    market=signal["market"],
                    observed_at=_parse_observed_at(signal.get("observed_at")),
                    method=signal["method"],
                    raw_reference=signal.get("raw_reference"),
                    basis=signal["basis"],
                    channel=signal.get("channel"),
                    correlation_id=correlation_id,
                )
                self._db.add(row)
                self._db.flush()
                # La evidencia detrás del número, si la fuente la dio
                # (Milestone 35). Una señal sin observaciones no es una señal
                # con cero: es una que no se midió así.
                for observation in signal.get("observations") or []:
                    self._db.add(
                        ProductSignalObservation(
                            signal_id=row.id,
                            period=observation["period"],
                            value=observation["value"],
                        )
                    )
            if product not in products:
                products.append(product)

        self._record_asked_names(keywords, products, correlation_id)

        self._db.add(
            AuditLog(
                actor=RESEARCH_AGENT_ACTOR,
                action="research.run",
                resource=f"research:{correlation_id}",
                before=None,
                after={
                    "category": category,
                    "candidate_count": len(products),
                    # Cuántos candidatos eran un producto que ya estaba
                    # (Milestone 36): sin esto, una ejecución que no descubrió
                    # nada nuevo se leería igual que una que descubrió cuatro.
                    "reused_products": reused,
                    # Señales que llegaron y no se guardaron porque su licencia
                    # no lo autoriza, por proveedor (Milestone 37). Vacío es lo
                    # normal; si no lo está, hay una licencia por resolver.
                    "signals_withheld_by_provider": {
                        provider: withheld.count(provider) for provider in sorted(set(withheld))
                    },
                    # Qué parte de lo que se acaba de guardar es real.
                    "provenance": sorted(
                        {c.get("provenance", "unknown") for c in result.data["candidates"]}
                    ),
                },
                correlation_id=correlation_id,
            )
        )
        self._db.commit()
        return products

    def _record_asked_names(
        self, keywords: list[str] | None, products: list[Product], correlation_id: str
    ) -> None:
        """Con qué palabra preguntó quien pidió la investigación (Milestone 36).

        El catálogo de términos resuelve la identidad **antes** de llamar a la
        fuente: quien pide `AIRFRYER` acaba preguntando por `Air fryer`, que es la
        forma que la fuente conoce y la que queda en el `query` de cada señal. Eso
        es correcto para la procedencia de la medición, y pierde la pregunta
        original — que es justo lo que alguien querrá reconstruir cuando mire el
        resultado y no encuentre la palabra que escribió.

        Solo se anota lo que difiere, y una vez: el mismo keyword en tres
        ejecuciones es la misma respuesta a la misma pregunta.
        """
        by_key = {p.identity_key: p for p in products if p.identity_key}
        for keyword in keywords or []:
            asked = keyword.strip()
            if not asked:
                continue
            identity = resolve(asked)
            product = by_key.get(identity.key)
            if product is None or asked == product.name:
                continue
            already = (
                self._db.query(ProductIdentityAlias)
                .filter_by(product_id=product.id, alias=asked)
                .first()
            )
            if already is None:
                self._db.add(
                    ProductIdentityAlias(
                        product_id=product.id,
                        alias=asked,
                        identity_key=identity.key,
                        method=identity.method,
                        correlation_id=correlation_id,
                    )
                )

    def _product_for(self, candidate: dict, correlation_id: str) -> tuple[Product, bool]:
        """El producto de un candidato: el que ya existía, o uno nuevo
        (Milestone 36, ADR 0014).

        Antes creaba una fila siempre. Dos investigaciones sobre `home` dejaban
        dos «Air fryer» sin relación entre sí, y las doce observaciones mensuales
        que el Milestone 35 empezó a guardar quedaban repartidas entre ellas: la
        pregunta que justificó esa tabla —«¿cómo se movió el interés el último
        trimestre?»— no se podía contestar por producto.

        Se busca por clave de identidad **y categoría**. La categoría viene de la
        petición, no de la fuente, y un mismo término pedido bajo dos categorías
        son dos afirmaciones distintas: unirlas reescribiría en silencio la
        primera. Queda como límite conocido, no como descuido.

        La fila más antigua gana cuando hay varias —un duplicado anterior al
        milestone—: así la acumulación se concentra en una y no en la última.
        """
        identity = resolve(candidate["name"])
        product = (
            self._db.query(Product)
            .filter_by(identity_key=identity.key, category=candidate["category"])
            .order_by(Product.created_at.asc())
            .first()
        )
        reused = product is not None
        if product is None:
            product = Product(
                name=identity.name,
                identity_key=identity.key,
                category=candidate["category"],
                created_by=RESEARCH_AGENT_ACTOR,
                source="research",
                status="CANDIDATE",
            )
            self._db.add(product)
            self._db.flush()

        # Lo que una fuente declara equivalente a este candidato (Milestone 38).
        # Es la segunda vía de la ADR 0014 —identidad declarada— firmada por otro:
        # Wikimedia dice que «Freidora de aire» es el artículo español de «Air
        # fryer», y eso no lo deduce este código de que dos cadenas se parezcan.
        for declared in candidate.get("declared_aliases") or []:
            self._record_alias(
                product,
                alias=declared["name"],
                identity_key=identity.key,
                method=declared["method"],
                correlation_id=correlation_id,
            )

        if candidate["name"].strip() != product.name:
            # Llegó con otro nombre. Se anota con qué nombre llegó y por qué vía
            # se resolvió, porque una fusión sin motivo escrito es
            # indistinguible de un error.
            self._record_alias(
                product,
                alias=candidate["name"],
                identity_key=identity.key,
                method=identity.method,
                correlation_id=correlation_id,
            )
        return product, reused

    def _record_alias(
        self,
        product: Product,
        *,
        alias: str,
        identity_key: str,
        method: str,
        correlation_id: str,
    ) -> None:
        """Anota un nombre equivalente, una sola vez.

        El mismo alias en tres ejecuciones es la misma respuesta a la misma
        pregunta, y tres filas idénticas esconderían las que sí aportan algo."""
        if alias.strip() == product.name:
            return
        already = (
            self._db.query(ProductIdentityAlias)
            .filter_by(product_id=product.id, alias=alias)
            .first()
        )
        if already is not None:
            return
        self._db.add(
            ProductIdentityAlias(
                product_id=product.id,
                alias=alias,
                identity_key=identity_key,
                method=method,
                correlation_id=correlation_id,
            )
        )
