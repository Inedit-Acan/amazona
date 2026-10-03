"""El registro de ingresos verificados (Milestone 45, ADR 0030).

**No es el libro contable ni fiscal de KOVA**: es una lista inmutable de hechos monetarios operativos verificados, una
proyección determinista de los hechos de pago que `PaymentService` aplica. Solo `ledger.py` escribe en su tabla, y solo
`PaymentService` llama a `ledger.py`; el resto (`evidence.py`, `check.py`) solo lee.
"""
