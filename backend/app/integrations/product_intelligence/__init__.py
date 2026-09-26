"""Product Intelligence: el primer dominio con un adaptador real (Milestone 34).

La carpeta por dominio que la ADR 0008 dejó anotada —«llegan con el primer
adaptador real, en el Milestone 34»— es esta.

- `mock.py`: fixtures, con procedencia y marcados como simulados.
- `wikimedia.py`: interés real medido, proxy declarado.
- `composite.py`: lo real primero, el relleno después.
- `terms.py`: qué se pregunta (no qué se responde), y por qué es un arranque.
"""

from app.integrations.product_intelligence.composite import CompositeProductSignalProvider
from app.integrations.product_intelligence.mock import MockProductSignalProvider
from app.integrations.product_intelligence.wikimedia import WikimediaPageviewsProvider

__all__ = [
    "CompositeProductSignalProvider",
    "MockProductSignalProvider",
    "WikimediaPageviewsProvider",
]
