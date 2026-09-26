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
    """Qué se va a preguntar para una categoría.

    Los términos de quien llama van primero: son más específicos que una lista
    general y quien pregunta sabe mejor qué busca. El catálogo completa hasta el
    tope. Si no hay ni lo uno ni lo otro, la lista es vacía — y eso significa que
    no se pregunta nada, no que no haya demanda.
    """
    asked = [term.strip() for term in (keywords or []) if term and term.strip()]
    seeded = [term for term in SEED_TERMS.get(category, []) if term not in asked]
    return (asked + seeded)[:limit]
