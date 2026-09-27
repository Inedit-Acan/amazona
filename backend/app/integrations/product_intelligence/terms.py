"""Los términos que se le preguntan a una fuente real, por categoría.

**Esto es la pregunta, no la respuesta.** Ninguna cifra sale de aquí: las
medidas las da la fuente externa. Lo que hay en este fichero es la lista de
términos sobre los que se pregunta, escrita a mano y versionada en git, de modo
que siempre se puede ver quién añadió qué término y cuándo.

## Es un arranque, no el mecanismo definitivo

Un catálogo escrito a mano **no descubre productos**: solo mide los que alguien
ya pensó. Sirve para poner en marcha el primer adaptador real y para poder
comparar mock contra real (Milestone 35), y nada más. El descubrimiento de
verdad —marketplaces, minería de reseñas y problemas, señales sociales,
distribución de precios, persistencia de tendencia; los ocho ejes del plan
maestro §8— necesita fuentes y mecanismos reales que este milestone **no**
construye.

Mientras esta lista sea el único origen de candidatos, el sistema encuentra lo
que ya sabíamos buscar. Decirlo aquí es parte del trabajo: lo contrario sería
que dentro de tres milestones alguien lo tomara por un buscador.
"""

from app.integrations.product_intelligence.identity import resolve

#: Términos por categoría. Nombres comunes, no marcas: se consulta interés
#: general por el tipo de producto, y una marca mediría otra cosa.
SEED_TERMS: dict[str, list[str]] = {
    "electronics": [
        "Wireless earbuds",
        "Headphones",
        "Power bank",
        "Video projector",
        "Smartwatch",
        "Bluetooth speaker",
    ],
    "home": [
        "Air fryer",
        "Robotic vacuum cleaner",
        "Espresso machine",
        "Humidifier",
        "Kitchen utensil",
        "Water filter",
    ],
    "accessories": [
        "Backpack",
        "Wallet",
        "Sunglasses",
        "Wristwatch",
        "Handbag",
        "Belt (clothing)",
    ],
}


def terms_for(category: str, keywords: list[str] | None = None, *, limit: int = 8) -> list[str]:
    """Qué se va a preguntar para una categoría, cada cosa una sola vez.

    Los términos de quien llama van primero: son más específicos que una lista
    general y quien pregunta sabe mejor qué busca. El catálogo completa hasta el
    tope. Si no hay ni lo uno ni lo otro, la lista es vacía — y eso significa que
    no se pregunta nada, no que no haya demanda.

    ## Dos términos que son el mismo producto se preguntan una vez

    Hasta el Milestone 36 esto se comparaba con `term not in asked`, igualdad
    exacta de cadena, y por eso `terms_for("home", ["air fryer"])` devolvía `air
    fryer` **y** `Air fryer`: dos de las ocho peticiones disponibles gastadas en
    lo mismo, y dos candidatos para un solo producto. Ahora se comparan claves de
    identidad (ADR 0014).

    ## Y se pregunta con la forma del catálogo

    Cuando el término de quien llama y uno del catálogo son el mismo producto, se
    manda **el del catálogo**: está escrito a mano, revisado y versionado, y el
    de quien llama es texto libre. No es una preferencia estética. Medido contra
    la API real: `Air_fryer` devuelve 30.897 visitas en doce meses y `air_fryer`
    —una redirección con vida propia— devuelve 5 en cuatro. Quedarse con la forma
    de quien pregunta conservaría la peor medición de las dos.

    El recorte a `limit` se hace **después** de resolver, para que el tope sean
    tantos productos distintos y no tantas casillas con duplicados dentro.
    """
    asked = [term.strip() for term in (keywords or []) if term and term.strip()]
    catalogue = SEED_TERMS.get(category, [])
    curated = {resolve(term).key: term for term in catalogue}

    chosen: dict[str, str] = {}
    for term in asked:
        identity = resolve(term)
        chosen.setdefault(identity.key, curated.get(identity.key, identity.name))
    for term in catalogue:
        chosen.setdefault(resolve(term).key, term)
    return list(chosen.values())[:limit]
