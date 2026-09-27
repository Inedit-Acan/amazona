"""Qué nombres distintos designan el mismo producto, dicho a mano (Milestone 36).

**Cada entrada de este fichero es una afirmación.** «airfryer es lo mismo que
Air fryer» no lo deduce nadie: lo escribe una persona, queda en git con su autor
y su fecha, y se puede discutir en una revisión. Eso es exactamente lo que la
ADR 0014 quiere: identidad **declarada**, nunca inferida por parecido. Un umbral
de similitud uniría «Air fryer» con «Air dryer» algún día, y nadie sabría cuándo
empezó a hacerlo.

Igual que `terms.py`, **esto es la pregunta y no la respuesta**: de aquí no sale
ninguna cifra. Solo sale qué dos preguntas eran la misma pregunta.

## Qué entra aquí y qué no

Entran variantes del **mismo nombre** en el mismo idioma: palabra junta o
separada (`airfryer`, `smart watch`), y el nombre común de un objeto que el
catálogo llama de otra forma (`robot vacuum` por `Robotic vacuum cleaner`).

**No entran generalizaciones.** `coffee machine` no apunta a `Espresso machine`:
una cafetera de goteo no es una cafetera espresso, y unirlas mezclaría el interés
por dos productos distintos. Tampoco `projector` a `Video projector`.

**No entran traducciones**, y no por descuido. Medido el 27-09-2026 contra la API
real: `es.wikipedia` no tiene artículo «Air fryer» (HTTP 404), sí tiene «Freidora
de aire» (12.099 visitas en doce meses). Mandar la forma inglesa al proyecto
español cambiaría una medición que funciona por un 404. Resolver idiomas exige un
nombre **por mercado**, no un nombre canónico único, y adivinar títulos de
artículo en alemán o francés sería inventar. Queda escrito como límite en la ADR
0014 con el mecanismo real que lo cerraría: los *langlinks* de Wikimedia, que son
una fuente y no una suposición.

**Y no entran los nombres del mock.** `Portable phone charger` no apunta a
`Power bank` ni `Mini projector` a `Video projector`, aunque se parezcan: eso
fabricaría un solapamiento falso entre fixtures y fuente real, que es justo lo
que la ADR 0013 rechazó cuando descartó «añadir los términos semilla al mock».
Lo que el informe de comparación dice hoy —cero candidatos en común— es verdad, y
no se arregla con un alias.
"""

#: Versión del catálogo. Viaja en el motivo de cada fusión (`alias:v1`), para
#: que una identidad resuelta hace tres meses se pueda atribuir a la lista que
#: estaba escrita entonces y no a la de hoy.
CATALOGUE_VERSION = "v1"

#: Alias → nombre canónico. Las claves están **ya normalizadas** (minúsculas, sin
#: acentos, sin puntuación): son claves de identidad, no texto que se enseñe. Hay
#: un test que lo comprueba, porque una clave mal escrita aquí no falla, solo
#: deja de encontrarse.
#:
#: Solo hace falta una entrada cuando la normalización no basta. `Belt (clothing)`
#: y `Belt` ya comparten clave —el paréntesis de desambiguación se cae— y
#: `air-fryer` también, porque el guion se convierte en espacio.
ALIASES: dict[str, str] = {
    # Compuestos que se escriben juntos o separados.
    "airfryer": "Air fryer",
    "smart watch": "Smartwatch",
    "powerbank": "Power bank",
    "sun glasses": "Sunglasses",
    "back pack": "Backpack",
    "wrist watch": "Wristwatch",
    "hand bag": "Handbag",
    "head phones": "Headphones",
    "wireless ear buds": "Wireless earbuds",
    # El nombre común de lo mismo, no una categoría más amplia.
    "robot vacuum": "Robotic vacuum cleaner",
    "robot vacuum cleaner": "Robotic vacuum cleaner",
}
