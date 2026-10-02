"""Un doble clic al crear un pedido produce un solo pedido (Milestone 44, ADR 0028 §9).

SQLite serializa las transacciones y nunca reproduce la carrera; aquí cada hilo tiene su propia sesión, en una base
PostgreSQL efímera, y arrancan juntos tras una barrera. Lo que se afirma son invariantes, no tiempos: veinte
peticiones iguales con la misma clave producen **un** pedido, y cada petición recibe o el pedido original o un 409
de «en curso»; ninguna crea otro.
"""

import threading

from order_test_support import SIMULATION, add_product
from pg_test_support import ephemeral_postgres
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.api.orders import MoneyIn, OrderCreate, OrderLineCreate, OrderOut, create_order
from app.auth.actor import Actor, ActorSource, RoleName
from app.core.errors import IdempotencyInProgressError
from app.db.models.order import Order, OrderItem

OWNER = Actor(subject="owner@amazona.local", role=RoleName.OWNER, source=ActorSource.DECLARED)


def run_together(engine, jobs: list) -> list:
    barrier = threading.Barrier(len(jobs))
    results: list = []
    lock = threading.Lock()

    def worker(job) -> None:
        with Session(engine) as session:
            try:
                barrier.wait(timeout=10)
                outcome = job(session)
            except Exception as exc:  # noqa: BLE001 - lo que le pasó a cada tarea es el dato
                outcome = exc
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=worker, args=(job,)) for job in jobs]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    return results


def post(product_id: str, *, key: str = "double-click", customer: str = "sim_double_click"):
    payload = OrderCreate(
        customer_ref=customer,
        market="eu",
        lines=[OrderLineCreate(product_id=product_id, quantity=2, unit_price=MoneyIn(amount="25.00", currency="EUR"))],
    )

    def job(session: Session):
        return create_order(
            payload=payload,
            response=Response(),
            db=session,
            identity=OWNER,
            settings=SIMULATION,
            idempotency_key=key,
        )

    return job


def test_twenty_simultaneous_clicks_with_the_same_key_create_one_order():
    with ephemeral_postgres() as engine:
        with Session(engine) as db:
            product_id = add_product(db).id

        results = run_together(engine, [post(product_id)] * 20)

        created = [r for r in results if isinstance(r, OrderOut)]
        replays = [r for r in results if isinstance(r, dict)]
        in_progress = [r for r in results if isinstance(r, IdempotencyInProgressError)]
        assert len(created) == 1
        assert len(created) + len(replays) + len(in_progress) == 20, "nobody receives anything else"
        assert all(r["id"] == created[0].id for r in replays)
        with Session(engine) as db:
            assert db.query(Order).count() == 1
            assert db.query(OrderItem).count() == 1


def test_clicks_with_different_keys_are_different_intentions():
    with ephemeral_postgres() as engine:
        with Session(engine) as db:
            product_id = add_product(db).id

        results = run_together(
            engine, [post(product_id, key=f"intent-{n}", customer=f"sim_intent_{n}") for n in range(8)]
        )

        assert all(isinstance(r, OrderOut) for r in results), results
        with Session(engine) as db:
            assert db.query(Order).count() == 8
