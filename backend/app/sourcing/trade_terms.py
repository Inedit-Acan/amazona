"""Incoterms y monedas: el vocabulario cerrado de una cotización (Milestone 39).

Una cotización sin Incoterm y sin moneda no es una cotización, es un número.
«4,20» puede ser EXW Shenzhen en dólares —sin transporte, sin aduana, sin
seguro— o DDP Valencia en euros, que ya lo incluye todo. Entre las dos hay la
diferencia entre ganar dinero y perderlo, y hasta este milestone el modelo no
podía distinguirlas: `SupplierQuote.unit_price` era un `float` a secas.

## Por qué son catálogos y no texto libre

Por lo mismo que los canales del Milestone 38: un `DPP` tecleado con un dedo
torcido sería un Incoterm fantasma que ninguna consulta encuentra, y el sistema
diría «no consta» sobre algo que consta. Validar al escribir convierte un error
silencioso en un error ruidoso.

Los Incoterms son un conjunto **cerrado**: los once de la Cámara de Comercio
Internacional, edición 2020. No es una lista que crezca con el negocio.

Las monedas son un catálogo **extensible**: una línea más y cero migraciones,
igual que las plataformas de canal. Están las que aparecen en comercio con los
orígenes que el sistema ya conoce; añadir una es una línea, y no añadirla antes
de tiempo evita fingir que aceptamos cotizaciones en monedas que nadie ha
negociado.

## Lo que NO hay aquí

**No hay conversión entre monedas.** Convertir exige un tipo de cambio, y un
tipo de cambio es un dato de mercado con fecha, fuente y coste. Inventar uno
—o peor, usar uno de hace seis meses— metería un error del 5 % en el cálculo
del margen sin que nadie lo viera. Hasta que haya fuente, dos cotizaciones en
monedas distintas **no se comparan**: se dice que no se pueden comparar.
"""

from dataclasses import dataclass

from app.core.errors import ValidationError


class UnknownIncotermError(ValidationError):
    """Un Incoterm que no existe. Se rechaza en vez de guardarse: un término de
    entrega inventado se leería como una condición pactada."""


class UnknownCurrencyError(ValidationError):
    """Una moneda que no está en el catálogo. Se rechaza por la misma razón, y
    añadirla es una línea de este fichero."""


@dataclass(frozen=True)
class Incoterm:
    """Un término de entrega, y hasta dónde llega la responsabilidad del vendedor."""

    code: str
    name: str
    #: Si el precio ya incluye el transporte principal hasta el destino. Es la
    #: pregunta que decide si el coste logístico hay que sumarlo o ya está
    #: dentro, y la que hacía falta para que «coste de aterrizaje» signifique
    #: algo comparable entre dos proveedores.
    includes_main_carriage: bool
    #: Si el precio ya incluye el despacho de importación y los derechos.
    includes_import_duties: bool


#: Los once Incoterms 2020 de la CCI. Cerrado.
INCOTERMS: dict[str, Incoterm] = {
    term.code: term
    for term in (
        Incoterm("EXW", "Ex Works", False, False),
        Incoterm("FCA", "Free Carrier", False, False),
        Incoterm("FAS", "Free Alongside Ship", False, False),
        Incoterm("FOB", "Free On Board", False, False),
        Incoterm("CFR", "Cost and Freight", True, False),
        Incoterm("CIF", "Cost, Insurance and Freight", True, False),
        Incoterm("CPT", "Carriage Paid To", True, False),
        Incoterm("CIP", "Carriage and Insurance Paid To", True, False),
        Incoterm("DAP", "Delivered at Place", True, False),
        Incoterm("DPU", "Delivered at Place Unloaded", True, False),
        Incoterm("DDP", "Delivered Duty Paid", True, True),
    )
}


#: Código ISO 4217 -> nombre. Extensible: una línea.
CURRENCIES: dict[str, str] = {
    "EUR": "euro",
    "USD": "dólar estadounidense",
    "CNY": "yuan renminbi",
    "GBP": "libra esterlina",
    "PLN": "esloti polaco",
    "VND": "dong vietnamita",
    "MXN": "peso mexicano",
    "HKD": "dólar de Hong Kong",
}

#: La moneda en la que AMAZONA razona sobre márgenes. Una cotización en otra
#: moneda **no se convierte**: se marca como no comparable hasta que haya fuente
#: de tipos de cambio.
ACCOUNTING_CURRENCY = "EUR"


def incoterm_for(code: str) -> Incoterm:
    """El Incoterm de un código, o un error. Nunca `None`: un término de entrega
    que no se reconoce no puede tratarse como «sin condiciones»."""
    term = INCOTERMS.get(code.strip().upper())
    if term is None:
        raise UnknownIncotermError(
            f"{code!r} is not an Incoterms 2020 term; known: {', '.join(sorted(INCOTERMS))}"
        )
    return term


def currency_for(code: str) -> str:
    """El nombre de una moneda del catálogo, o un error."""
    normalised = code.strip().upper()
    name = CURRENCIES.get(normalised)
    if name is None:
        raise UnknownCurrencyError(
            f"{code!r} is not a known trade currency; known: {', '.join(sorted(CURRENCIES))}. "
            "Adding one is a line in app/sourcing/trade_terms.py"
        )
    return name


def comparable(left: str | None, right: str | None) -> bool:
    """Si dos importes se pueden comparar sin inventar un tipo de cambio.

    Dos monedas desconocidas **no** son comparables aunque las dos sean `None`:
    que nadie haya dicho en qué moneda está un precio no permite suponer que
    están en la misma.
    """
    if left is None or right is None:
        return False
    return left.strip().upper() == right.strip().upper()
