"""Qué se guarda de un proveedor, y de dónde vino (Milestone 39, ADR 0017).

Dos caminos de escritura, y son distintos a propósito:

- **Descubrimiento**: el agente pregunta a un directorio y se persiste lo que
  conteste, con su procedencia. Hoy el único directorio es el mock.
- **Entrada manual**: una persona teclea un proveedor, una cotización o una
  capacidad. Es la razón de ser del Milestone 39 — un precio de proveedor
  negociado es un dato real que solo puede entrar así, y la decisión del
  propietario es que este camino se sostiene **permanentemente**, no como
  arranque hasta que haya API.

Los dos escriben en las mismas tablas y las dos clases de fila se distinguen por
`provenance` y `source`, nunca por qué tabla ocupan. Un dato real y uno de
fixture conviviendo sin poder distinguirse es lo que el Milestone 30 arregló
para los proveedores de señales; esto es lo mismo para los de mercancía.
"""

import datetime

from sqlalchemy.orm import Session

from app.agents.supplier_sourcing import SupplierSourcingAgent
from app.core.errors import NotFoundError, ValidationError
from app.db.models.audit import AuditLog
from app.db.models.product import Product
from app.db.models.supplier import Supplier
from app.db.models.supplier_capability import SupplierCapability
from app.db.models.supplier_quote import SupplierQuote
from app.sourcing import identity as supplier_identity
from app.sourcing.capabilities import CapabilityDeclaration, SupplyCapability
from app.sourcing.provenance import (
    STORABLE,
    MissingVerifierError,
    SupplierFactProvenance,
    parse,
)
from app.sourcing.risk import SupplierRiskFacts, SupplierRiskProfile, assess
from app.sourcing.trade_terms import currency_for, incoterm_for

SOURCING_AGENT_ACTOR = "agent-supplier-sourcing-1"


def supplier_identity_verified(db: Session, quote: SupplierQuote) -> bool | None:
    """Si un tercero independiente ha comprobado quién es la empresa detrás de
    esta cotización (Milestone 39).

    Devuelve tres cosas, no dos. `None` significa que **nadie lo ha dicho**, y
    no es `False`: hasta aquí `quote.verified` valía `False` tanto para un
    proveedor que alguien había mirado y rechazado como para uno que nadie había
    mirado, y los agentes de legal, operaciones y economía levantaban el mismo
    aviso en los dos casos. Un aviso que no distingue eso no informa de nada.
    """
    supplier = db.get(Supplier, quote.supplier_id)
    declared = parse(supplier.verification if supplier else None)
    if declared is SupplierFactProvenance.UNKNOWN:
        return None
    return declared is SupplierFactProvenance.THIRD_PARTY_VERIFIED


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class SourcingService:
    """Ejecuta el agente de Supplier Sourcing sobre un Product existente y
    persiste cada candidato como SupplierQuote, **reutilizando** la ficha de
    proveedor cuando ya existe.

    Hasta el Milestone 39 «ya existe» significaba nombre y región idénticos
    carácter a carácter. Con la entrada manual —donde el nombre lo teclea una
    persona— eso habría creado una empresa nueva por cada espacio de más. Ahora
    la reutilización va por la clave de identidad del Milestone 36 aplicada a
    empresas (`app.sourcing.identity`): determinista o declarada, nunca por
    parecido.
    """

    def __init__(self, db: Session, agent: SupplierSourcingAgent | None = None) -> None:
        self._db = db
        self._agent = agent or SupplierSourcingAgent()

    # ------------------------------------------------------------------ lectura

    def capability_declarations(
        self, supplier_id: str, *, product_id: str | None = None
    ) -> list[CapabilityDeclaration]:
        """Lo declarado para un proveedor: lo general y, si se pide, lo de un
        producto. Quién gana sobre quién lo decide `app.sourcing.capabilities`,
        no esta consulta."""
        rows = self._db.query(SupplierCapability).filter_by(supplier_id=supplier_id).all()
        return [
            CapabilityDeclaration(
                capability=SupplyCapability(row.capability),
                supported=row.supported,
                provenance=SupplierFactProvenance(row.provenance),
                source=row.source,
                note=row.note,
                observed_at=row.observed_at,
                product_id=row.product_id,
            )
            for row in rows
            if row.product_id is None or product_id is None or row.product_id == product_id
        ]

    def risk_profile(self, quote: SupplierQuote) -> SupplierRiskProfile:
        """Las ocho dimensiones de §11 para una cotización concreta.

        Se calcula al leer y no se guarda. Una evaluación guardada envejece sin
        avisar: el día que alguien declare la dirección de retorno en la UE, una
        fila de riesgo legal escrita hace tres meses seguiría diciendo lo
        contrario. Derivarla de los hechos guardados la mantiene siempre al día
        y, sobre todo, siempre reconstruible: se puede enseñar de qué salió.
        """
        supplier = self._db.get(Supplier, quote.supplier_id)
        from app.sourcing.capabilities import profile as capability_profile

        declarations = self.capability_declarations(
            quote.supplier_id, product_id=quote.product_id
        )
        alternatives = (
            self._db.query(SupplierQuote).filter_by(product_id=quote.product_id).count()
        )
        return assess(
            SupplierRiskFacts(
                country=supplier.country if supplier else None,
                region=supplier.region if supplier else None,
                website=supplier.website if supplier else None,
                verification=parse(supplier.verification if supplier else None),
                reliability=supplier.reliability_score if supplier else None,
                reliability_provenance=parse(
                    supplier.reliability_provenance if supplier else None
                ),
                incoterm=quote.incoterm,
                payment_terms=quote.payment_terms,
                lead_time_days=quote.lead_time_days,
                transit_days=quote.transit_days,
                destination_market=quote.destination_market,
                capabilities=tuple(
                    capability_profile(declarations, product_id=quote.product_id)
                ),
                alternatives_for_product=alternatives,
            )
        )

    # ------------------------------------------------------- escritura: agente

    def run_sourcing(
        self,
        *,
        product_id: str,
        category: str,
        destination_region: str,
        max_results: int,
        correlation_id: str,
    ) -> list[SupplierQuote]:
        product = self._db.get(Product, product_id)
        if product is None:
            raise NotFoundError(f"product {product_id} not found")

        result = self._agent.run(
            {
                "category": category,
                "destination_region": destination_region,
                "max_results": max_results,
            }
        )

        quotes: list[SupplierQuote] = []
        for candidate in result.data["candidates"]:
            supplier = self._upsert_supplier(
                name=candidate["name"],
                region=candidate["region"],
                country=candidate["country"],
                city=candidate["city"],
                website=candidate["website"],
                verification=candidate["verification"],
                verified_by=candidate["verified_by"],
                reliability=candidate["reliability"],
                reliability_provenance=candidate["provenance"],
            )

            quote = SupplierQuote(
                product_id=product.id,
                supplier_id=supplier.id,
                unit_price=candidate["unit_price"],
                currency=candidate["currency"],
                quoted_unit=candidate["quoted_unit"],
                quoted_quantity=candidate["quoted_quantity"],
                moq=candidate["moq"],
                lead_time_days=candidate["lead_time_days"],
                transit_days=candidate["transit_days"],
                transport_mode=candidate["transport_mode"],
                incoterm=candidate["incoterm"],
                payment_terms=candidate["payment_terms"],
                destination_market=candidate["destination_market"],
                provenance=candidate["provenance"],
                source=candidate["source"],
                logistics_cost_per_unit=candidate["logistics_cost_per_unit"],
                logistics_provenance=candidate["logistics_provenance"],
                total_landed_cost_per_unit=candidate["total_landed_cost_per_unit"],
                data=candidate,
                correlation_id=correlation_id,
            )
            self._db.add(quote)
            quotes.append(quote)

        self._db.add(
            AuditLog(
                actor=SOURCING_AGENT_ACTOR,
                action="sourcing.run",
                resource=f"sourcing:{correlation_id}",
                before=None,
                after={"product_id": product_id, "quote_count": len(quotes)},
                correlation_id=correlation_id,
            )
        )
        self._db.commit()
        return quotes

    # ------------------------------------------------------- escritura: manual

    def record_supplier(
        self,
        *,
        name: str,
        actor: str,
        correlation_id: str,
        region: str | None = None,
        country: str | None = None,
        city: str | None = None,
        website: str | None = None,
        contact_info: dict | None = None,
        #: Por defecto, lo que dice el propio proveedor: una ficha que trae una
        #: persona de una conversación es exactamente eso. Subirla a
        #: `third_party_verified` exige nombrar al verificador.
        verification: str | None = SupplierFactProvenance.SUPPLIER_CLAIM.value,
        verified_by: str | None = None,
        reliability: float | None = None,
        reliability_provenance: str | None = None,
    ) -> Supplier:
        """Da de alta —o actualiza— un proveedor tecleado por una persona.

        Actualiza en vez de duplicar cuando la clave de identidad coincide. Y
        **solo rellena lo que llega**: un campo ausente en la petición no borra
        lo que ya se sabía. Sobrescribir con nulos convertiría cada corrección
        parcial en una pérdida de datos silenciosa.
        """
        if not name.strip():
            raise ValidationError("a supplier needs a name")
        self._check_verification(verification, verified_by, what=f"supplier {name!r}")

        supplier = self._upsert_supplier(
            name=name,
            region=region,
            country=country,
            city=city,
            website=website,
            verification=verification,
            verified_by=verified_by,
            reliability=reliability,
            reliability_provenance=reliability_provenance or (
                SupplierFactProvenance.SUPPLIER_CLAIM.value if reliability is not None else None
            ),
            contact_info=contact_info,
            checked_now=True,
        )
        self._db.add(
            AuditLog(
                actor=actor,
                action="supplier.record",
                resource=f"supplier:{supplier.id}",
                before=None,
                after={"name": supplier.name, "identity_key": supplier.identity_key},
                correlation_id=correlation_id,
            )
        )
        self._db.commit()
        return supplier

    def record_quote(
        self,
        *,
        supplier_id: str,
        product_id: str,
        actor: str,
        correlation_id: str,
        provenance: str = SupplierFactProvenance.SUPPLIER_CLAIM.value,
        source: str | None = None,
        unit_price: float | None = None,
        currency: str | None = None,
        quoted_unit: str | None = None,
        quoted_quantity: int | None = None,
        moq: int | None = None,
        lead_time_days: int | None = None,
        transit_days: int | None = None,
        transport_mode: str | None = None,
        incoterm: str | None = None,
        payment_terms: str | None = None,
        destination_market: str | None = None,
        logistics_cost_per_unit: float | None = None,
        valid_from: datetime.datetime | None = None,
        valid_until: datetime.datetime | None = None,
    ) -> SupplierQuote:
        """Registra una cotización real, la que trae una persona de una
        negociación.

        Lo que no se pasa se queda nulo. **No se completa nada**: sin MOQ no hay
        MOQ de uno, y sin coste logístico no hay coste de aterrizaje aunque haya
        precio — sumar cero sería decir que el transporte es gratis, y el coste
        de aterrizaje es precisamente la cifra sobre la que después se calculan
        el margen y el techo de CAC.
        """
        supplier = self._db.get(Supplier, supplier_id)
        if supplier is None:
            raise NotFoundError(f"supplier {supplier_id} not found")
        if self._db.get(Product, product_id) is None:
            raise NotFoundError(f"product {product_id} not found")

        if parse(provenance) not in STORABLE:
            raise ValidationError(
                "a quote must say who says so; 'unknown' is not a provenance you can record"
            )
        self._check_verification(provenance, source, what="quote")
        if unit_price is not None and currency is None:
            raise ValidationError(
                "a price needs a currency: without one it cannot be compared with any "
                "other price, and assuming they match invents an exchange rate of 1.00"
            )
        if currency is not None:
            currency_for(currency)
            currency = currency.strip().upper()
        if incoterm is not None:
            incoterm_for(incoterm)
            incoterm = incoterm.strip().upper()
        if valid_from and valid_until and valid_until < valid_from:
            raise ValidationError("an offer cannot expire before it starts")

        landed = (
            round(unit_price + logistics_cost_per_unit, 4)
            if unit_price is not None and logistics_cost_per_unit is not None
            else None
        )

        quote = SupplierQuote(
            product_id=product_id,
            supplier_id=supplier_id,
            unit_price=unit_price,
            currency=currency,
            quoted_unit=quoted_unit,
            quoted_quantity=quoted_quantity,
            moq=moq,
            lead_time_days=lead_time_days,
            transit_days=transit_days,
            transport_mode=transport_mode,
            incoterm=incoterm,
            payment_terms=payment_terms,
            destination_market=destination_market,
            provenance=provenance,
            source=source or f"manual:{actor}",
            logistics_cost_per_unit=logistics_cost_per_unit,
            # Un coste logístico que trae una persona de una negociación lo
            # sostiene el proveedor, no un estimador nuestro.
            logistics_provenance=(
                provenance if logistics_cost_per_unit is not None else None
            ),
            total_landed_cost_per_unit=landed,
            valid_from=valid_from,
            valid_until=valid_until,
            data=None,
            correlation_id=correlation_id,
        )
        self._db.add(quote)
        supplier.last_checked_at = _utcnow()
        self._db.add(
            AuditLog(
                actor=actor,
                action="supplier.quote.record",
                resource=f"supplier:{supplier_id}",
                before=None,
                after={"product_id": product_id, "provenance": provenance},
                correlation_id=correlation_id,
            )
        )
        self._db.commit()
        return quote

    def declare_capability(
        self,
        *,
        supplier_id: str,
        capability: str,
        supported: bool,
        provenance: str,
        actor: str,
        correlation_id: str,
        product_id: str | None = None,
        source: str | None = None,
        note: str | None = None,
    ) -> SupplierCapability:
        """Registra que alguien dice que un proveedor soporta —o no— algo del §16.

        Una declaración nueva **no borra la anterior**: se apilan y gana la que
        más pesa (`app.sourcing.capabilities.resolve`). Que un proveedor dijera
        una cosa en marzo y la contraria en septiembre es información, y
        machacar la fila la tiraría.
        """
        if self._db.get(Supplier, supplier_id) is None:
            raise NotFoundError(f"supplier {supplier_id} not found")
        if product_id is not None and self._db.get(Product, product_id) is None:
            raise NotFoundError(f"product {product_id} not found")

        # Construir la declaración del dominio antes de guardarla es lo que
        # rechaza un `third_party_verified` sin emisor y una capacidad que no
        # existe. La validación vive en el dominio; aquí solo se persiste.
        declaration = CapabilityDeclaration(
            capability=SupplyCapability(capability),
            supported=supported,
            provenance=SupplierFactProvenance(provenance),
            source=source,
            note=note,
            observed_at=_utcnow(),
            product_id=product_id,
        )

        row = SupplierCapability(
            supplier_id=supplier_id,
            product_id=declaration.product_id,
            capability=declaration.capability.value,
            supported=declaration.supported,
            provenance=declaration.provenance.value,
            source=declaration.source,
            note=declaration.note,
            observed_at=declaration.observed_at,
        )
        self._db.add(row)
        self._db.add(
            AuditLog(
                actor=actor,
                action="supplier.capability.declare",
                resource=f"supplier:{supplier_id}",
                before=None,
                after={
                    "capability": declaration.capability.value,
                    "supported": declaration.supported,
                    "provenance": declaration.provenance.value,
                    "product_id": declaration.product_id,
                },
                correlation_id=correlation_id,
            )
        )
        self._db.commit()
        return row

    # ------------------------------------------------------------------ apoyo

    @staticmethod
    def _check_verification(provenance: str | None, issuer: str | None, *, what: str) -> None:
        if (
            parse(provenance) is SupplierFactProvenance.THIRD_PARTY_VERIFIED
            and not (issuer or "").strip()
        ):
            raise MissingVerifierError(
                f"{what}: third-party verification must name the verifier — "
                "'verified' without an issuer explains nothing (plan maestro §10)"
            )

    def _upsert_supplier(
        self,
        *,
        name: str,
        region: str | None,
        country: str | None,
        city: str | None,
        website: str | None,
        verification: str | None,
        verified_by: str | None,
        reliability: float | None,
        reliability_provenance: str | None,
        contact_info: dict | None = None,
        checked_now: bool = False,
    ) -> Supplier:
        resolved = supplier_identity.resolve(name, country=country, region=region)
        supplier = (
            self._db.query(Supplier).filter_by(identity_key=resolved.key).first()
        )
        if supplier is None:
            supplier = Supplier(
                name=resolved.name,
                identity_key=resolved.key,
                identity_method=resolved.method,
                region=region,
                country=country,
                city=city,
                website=website,
                contact_info=contact_info,
                verification=verification,
                verified_by=verified_by,
                verified_at=_utcnow() if verification else None,
                reliability_score=reliability,
                reliability_provenance=reliability_provenance if reliability is not None else None,
                last_checked_at=_utcnow() if checked_now else None,
            )
            self._db.add(supplier)
            self._db.flush()
            return supplier

        # Solo se completa lo que falta o lo que llega. Un campo ausente en la
        # petición no borra lo que ya se sabía.
        for field, value in (
            ("region", region),
            ("country", country),
            ("city", city),
            ("website", website),
            ("contact_info", contact_info),
        ):
            if value is not None:
                setattr(supplier, field, value)
        if verification is not None:
            supplier.verification = verification
            supplier.verified_by = verified_by
            supplier.verified_at = _utcnow()
        if reliability is not None:
            supplier.reliability_score = reliability
            supplier.reliability_provenance = reliability_provenance
        if checked_now:
            supplier.last_checked_at = _utcnow()
        self._db.flush()
        return supplier
