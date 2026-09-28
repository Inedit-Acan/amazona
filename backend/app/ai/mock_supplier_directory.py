"""Directorio de proveedores de fixtures. Sin red.

Sigue siendo lo que era desde el principio: un sustituto determinista de un
directorio real (Alibaba, Made-in-China…) para que el agente de Supplier
Sourcing tenga algo que ordenar.

## Qué cambió en el Milestone 39, y qué no

**Las cifras no cambian.** Los mismos ocho proveedores, los mismos precios, los
mismos MOQ y los mismos plazos que había antes de la ADR 0017. Es la regla del
Milestone 30: el mock no se elimina y sigue dando exactamente lo mismo, para que
cualquier diferencia que aparezca en una pantalla sea atribuible al cambio de
contrato y no a un fixture retocado de paso.

**Lo que cambia es que ahora dice de dónde salen.** Cada oferta se declara
`SIMULATED`, con `source` apuntando a este fichero. Antes decía `verified: True`
con la misma cara con la que lo diría un registro mercantil, que es exactamente
lo que el plan maestro §10 prohíbe.

Y las dos cosas que el fixture **no sabe** se quedan sin decir en vez de
inventarse: no hay Incoterm, no hay condiciones de pago, no hay país ni ciudad y
no hay capacidades del §16. Ninguna fuente pública dice si un fabricante hace
envío ciego; inventarlo aquí habría sido rellenar la pantalla con ocho
afirmaciones falsas, que es justo lo que el frontend hacía con `lib/demo`.

La moneda **sí** se declara: los precios estaban escritos en algún sitio y no
decirlo dejaría un número incomparable. Se declara `USD`, que es la moneda en la
que cotiza un directorio asiático, y queda como parte del fixture — no como un
hecho sobre ninguna empresa real, porque ninguna de estas empresas existe.
"""

from app.integrations.ports import SupplierOffer
from app.sourcing.provenance import SupplierFactProvenance

#: De dónde salen estos números: de aquí, y de ningún sitio más.
SOURCE = "fixtures:mock-supplier-directory"

#: La moneda de los precios del fixture. Está escrita porque un precio sin
#: moneda no se puede comparar con otro (ADR 0017), no porque nadie la haya
#: negociado.
CURRENCY = "USD"

_SUPPLIER_DATASET: dict[str, list[dict]] = {
    "electronics": [
        {
            "name": "Shenzhen Volta Electronics",
            "region": "china",
            "unit_price": 4.2,
            "moq": 500,
            "lead_time_days": 25,
            "reliability": 0.88,
        },
        {
            "name": "Hanoi Circuit Works",
            "region": "vietnam",
            "unit_price": 4.6,
            "moq": 300,
            "lead_time_days": 20,
            "reliability": 0.81,
        },
        {
            "name": "Guadalajara ElectroPack",
            "region": "mexico",
            "unit_price": 5.9,
            "moq": 200,
            "lead_time_days": 12,
            "reliability": 0.55,
        },
    ],
    "home": [
        {
            "name": "Foshan Home Goods Co",
            "region": "china",
            "unit_price": 2.1,
            "moq": 1000,
            "lead_time_days": 30,
            "reliability": 0.79,
        },
        {
            "name": "Bratislava Homeware Supply",
            "region": "eu",
            "unit_price": 3.4,
            "moq": 250,
            "lead_time_days": 10,
            "reliability": 0.9,
        },
        {
            "name": "Monterrey Casa Distribution",
            "region": "mexico",
            "unit_price": 2.8,
            "moq": 400,
            "lead_time_days": 14,
            "reliability": 0.48,
        },
    ],
    "accessories": [
        {
            "name": "Yiwu Accessory Hub",
            "region": "china",
            "unit_price": 1.3,
            "moq": 1500,
            "lead_time_days": 28,
            "reliability": 0.72,
        },
        {
            "name": "Porto Leather & Co",
            "region": "eu",
            "unit_price": 3.9,
            "moq": 150,
            "lead_time_days": 9,
            "reliability": 0.93,
        },
    ],
}


class MockSupplierDirectory:
    """Sustituto de fixtures de un directorio global de proveedores.

    Determinista: la misma categoría devuelve siempre lo mismo, en el orden del
    fichero. Ordenar por coste sigue siendo cosa del agente, no de aquí.
    """

    name = "mock-supplier-directory"

    def find_suppliers(
        self, *, category: str, destination_market: str, max_results: int = 5
    ) -> list[SupplierOffer]:
        pool = _SUPPLIER_DATASET.get(category.lower(), [])
        return [
            SupplierOffer(
                name=row["name"],
                provenance=SupplierFactProvenance.SIMULATED,
                source=SOURCE,
                region=row["region"],
                unit_price=row["unit_price"],
                currency=CURRENCY,
                moq=row["moq"],
                lead_time_days=row["lead_time_days"],
                destination_market=destination_market,
                reliability=row["reliability"],
                # La identidad de una empresa inventada la sostiene el fixture y
                # nadie más. No es `supplier_claim`: no hay proveedor que
                # reclame nada.
                verification=SupplierFactProvenance.SIMULATED,
            )
            for row in pool[:max_results]
        ]
