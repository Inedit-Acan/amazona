"""Apoyo compartido de los tests de requisitos regulatorios (Milestone 41).

Módulo auxiliar de tests, **no** un test: aquí viven la fuente falsa de EUR-Lex y
sus constantes, para que `test_regulatory_service.py` y `test_regulatory_api.py`
las importen de un sitio común en vez de que un test dependa de otro.

Se importa por su nombre (`from regulatory_test_support import ...`). `tests/` no
es un paquete: pytest, en su modo de importación por defecto (`prepend`), añade a
`sys.path` el directorio de cada fichero de test que recoge, y este módulo está en
ese mismo directorio. Funciona igual con `pytest` que con `python -m pytest`.
"""

import datetime

from app.integrations.ports import SourceAnchor

NOW = datetime.datetime(2026, 9, 29, 12, 0, tzinfo=datetime.UTC)
GPSR = "32023R0988"
LVD = "32014L0035"


def anchor(celex: str, *, found=True, in_force=True, code="REG", when=NOW, **extra) -> SourceAnchor:
    return SourceAnchor(
        provider="eur-lex-cellar",
        celex=celex,
        found=found,
        retrieved_at=when,
        source_url=f"https://publications.europa.eu/webapi/rdf/sparql?celex={celex}",
        in_force=in_force if found else None,
        act_type_code=code if found else None,
        eli="http://data.europa.eu/eli/x" if found else None,
        entry_into_force=("2024-12-13",) if found else (),
        end_of_validity="9999-12-31" if found else None,
        raw={"resource_legal_in-force": ["1"]} if found else {},
        **extra,
    )


class FakeSource:
    """Una fuente que responde lo que se le diga y anota cada pregunta."""

    name = "eur-lex-cellar"

    def __init__(self, answers: dict[str, SourceAnchor | Exception] | None = None) -> None:
        self.answers = answers or {}
        self.asked: list[str] = []

    def lookup(self, celex: str) -> SourceAnchor:
        self.asked.append(celex)
        answer = self.answers.get(celex)
        if isinstance(answer, Exception):
            raise answer
        if answer is None:
            return anchor(celex, found=False)
        return answer
