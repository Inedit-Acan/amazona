"""La ficha que acredita que un evento de pago fue verificado (Milestone 44, ADR 0028 §1).

`VerifiedPaymentEvent` solo se puede construir con `PROOF`. Esta ficha **solo la importan los módulos de
`app/payments/providers/`**: un test de arquitectura recorre el árbol de código y falla si alguien más la
importa. Es la diferencia entre «el evento pasó por `verify_webhook`» y «alguien construyó un evento y lo
llamó verificado».

No es una barrera criptográfica (Python no las tiene dentro de un proceso): es una frontera que el repositorio
hace cumplir, del mismo linaje que la de `Approval` y `PipelineReview` (ADR 0027).
"""

import hashlib

PROOF = object()


def payload_hash(raw_body: bytes) -> str:
    """El SHA-256 del cuerpo bruto: lo único que se conserva de él. Sirve para distinguir un reenvío idéntico de
    un evento distinto con el mismo identificador."""
    return hashlib.sha256(raw_body).hexdigest()
