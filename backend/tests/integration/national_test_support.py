"""Apoyo compartido de las pruebas de transposiciones nacionales (Milestone 43).

Módulo auxiliar de tests, **no** un test: la fuente falsa del BOE y un constructor de
registros a partir de las **respuestas reales** guardadas en `tests/fixtures/boe/`.
Se importa por su nombre, igual que `regulatory_test_support.py`.
"""

import datetime
import json
from pathlib import Path

from app.integrations.ports import NationalNormRecord, PublicationCheck
from app.integrations.regulatory.boe import parse_metadata, parse_relations
from app.legal.national import PROVIDER_NAME, official_url

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "boe"
TOYS_ID = "BOE-A-2011-14252"
#: Directiva 2009/48/CE (juguetes): la que el análisis del BOE dice que traspone el
#: Real Decreto 1205/2011.
TOYS = "32009L0048"


def _load(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def toys_record(
    *,
    when: datetime.datetime,
    publication: str = "confirmed",
    consolidated: bool = True,
    metadata: dict | None = None,
    relations: dict | None = None,
) -> NationalNormRecord:
    if not consolidated:
        return NationalNormRecord(
            provider=PROVIDER_NAME,
            national_id=TOYS_ID,
            retrieved_at=when,
            consolidated=False,
            publication=PublicationCheck("not_checked", "no consolidated metadata"),
            source_urls=("https://www.boe.es/datosabiertos/api/legislacion-consolidada/id/x/metadatos",),
        )
    meta = parse_metadata(_load(f"metadatos_{TOYS_ID}.json"), TOYS_ID)
    meta.update(metadata or {})
    rels = relations if relations is not None else parse_relations(_load(f"analisis_{TOYS_ID}.json"))
    return NationalNormRecord(
        provider=PROVIDER_NAME,
        national_id=TOYS_ID,
        retrieved_at=when,
        consolidated=True,
        metadata=meta,
        relations=rels,
        publication=PublicationCheck(publication, "detail", official_url(TOYS_ID)),
        source_urls=(
            f"https://www.boe.es/datosabiertos/api/legislacion-consolidada/id/{TOYS_ID}/metadatos",
            f"https://www.boe.es/datosabiertos/api/legislacion-consolidada/id/{TOYS_ID}/analisis",
        ),
    )


class FakeNationalSource:
    """Una fuente que responde lo que se le diga y anota cada pregunta."""

    name = PROVIDER_NAME

    def __init__(self, answers: dict[str, NationalNormRecord | Exception] | None = None) -> None:
        self.answers = answers or {}
        self.asked: list[str] = []

    def lookup(self, national_id: str) -> NationalNormRecord:
        self.asked.append(national_id)
        answer = self.answers.get(national_id)
        if isinstance(answer, Exception):
            raise answer
        if answer is None:
            raise AssertionError(f"nothing scripted for {national_id}")
        return answer
