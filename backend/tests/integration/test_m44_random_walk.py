"""Caminatas aleatorias sobre M44: el estado persistente es coherente pase lo que pase (Milestone 44, ADR 0028).

Las pruebas de ejemplo comprueban los caminos que alguien imaginó. Esta recorre los que nadie imaginó: con una semilla,
elige operaciones al azar (abrir cobros, entregar eventos —repetidos, alterados, antiguos, de importes distintos—, pedir
reembolsos, repartir, comprar, enviar, cancelar, barrer, reconciliar, resolver a mano y **morir en mitad de una
llamada**), con proveedores que fallan de todas las formas que declara el contrato, y después de **cada** paso exige:

1. `check_invariants`: el estado entero es coherente (pedidos, cobros, reembolsos, asignación, y el dominio y su
   `ExternalAction` cuentan la misma historia);
2. ningún proveedor recibió más llamadas que operaciones cruzaron la frontera de durabilidad;
3. **ningún error escapa sin ser una respuesta limpia**: lo que no es 404, 409, 422, 423 o el 400 de un webhook sin
   verificar sería un 500 en la API.

Al final, una recuperación con las herramientas que existen (barrido, resolución humana, reconciliación de eventos)
tiene que dejar **todo** en un estado que no esté a medias. Si una semilla falla, el mensaje trae la semilla y la
secuencia de operaciones: se reproduce tal cual. Las operaciones viven en `m44_walk_test_support.py`.
"""

import pytest
from m44_walk_test_support import (
    OPERATIONS,
    STEPS,
    make_world,
    reconcile_events,
    resolve_by_hand,
    run_operation,
    sweep,
    verdict,
)
from sqlalchemy import select

from app.db.models.external_action import ExternalAction
from app.db.models.fulfillment import Fulfillment
from app.db.models.order import Order
from app.db.models.payment import Payment, PaymentEvent, Refund

SEEDS = list(range(60))


@pytest.mark.parametrize("seed", SEEDS)
def test_a_random_walk_keeps_every_invariant_at_every_step(seed: int):
    world, engine = make_world(seed)
    try:
        weights = [weight for weight, _, _ in OPERATIONS]
        for step in range(STEPS):
            _, name, operation = world.rnd.choices(OPERATIONS, weights=weights)[0]
            world.log.append(name)
            run_operation(world, name, operation)
            broken = verdict(world, seed, f"after step {step} ({name})")
            assert not broken, "\n".join(broken)
    finally:
        engine.dispose()


@pytest.mark.parametrize("seed", SEEDS[:15])
def test_the_tools_that_exist_leave_nothing_half_done(seed: int):
    """Tras caminar al azar, el barrido, la resolución humana y la reconciliación de eventos —lo que existe— dejan
    todo sin estados a medias. Lo único que queda abierto es lo que solo cierra un hecho del proveedor."""
    world, engine = make_world(1000 + seed)
    try:
        weights = [weight for weight, _, _ in OPERATIONS]
        for _ in range(STEPS):
            _, name, operation = world.rnd.choices(OPERATIONS, weights=weights)[0]
            world.log.append(name)
            run_operation(world, name, operation)

        run_operation(world, "reconcile_events", reconcile_events)
        run_operation(world, "sweep", sweep)  # PENDING → liberada; CALLING → UNKNOWN_OUTCOME
        for _ in range(60):
            with world.session() as db:
                pending = db.scalar(
                    select(ExternalAction.id).where(ExternalAction.status == "UNKNOWN_OUTCOME").limit(1)
                )
            if pending is None:
                break
            run_operation(world, "resolve_by_hand", resolve_by_hand)
        run_operation(world, "reconcile_events", reconcile_events)

        with world.session() as db:
            stuck = {
                "actions": [
                    a.reference
                    for a in db.scalars(select(ExternalAction))
                    if a.status in ("PENDING", "CALLING", "UNKNOWN_OUTCOME")
                ],
                "payments": [
                    p.id for p in db.scalars(select(Payment)) if p.status in ("REQUESTED", "OPENING", "UNKNOWN_OUTCOME")
                ],
                "refunds": [r.id for r in db.scalars(select(Refund)) if r.status in ("REQUESTED", "UNKNOWN_OUTCOME")],
                "fulfillments": [
                    f.id
                    for f in db.scalars(select(Fulfillment))
                    if f.status in ("PURCHASING", "SHIPPING", "UNKNOWN_OUTCOME")
                ],
                "events": [e.id for e in db.scalars(select(PaymentEvent)) if e.processing_status == "RECEIVED"],
            }
        assert not any(stuck.values()), f"seed {1000 + seed} left things half done: {stuck}\noperations: " + " > ".join(
            world.log
        )
        broken = verdict(world, 1000 + seed, "after recovery")
        assert not broken, "\n".join(broken)
    finally:
        engine.dispose()


def test_the_walks_really_exercise_the_dangerous_paths():
    """Una caminata que nunca llega a nada no prueba nada: entre todas las semillas hay cobros capturados, duplicados,
    reembolsos, fulfillments comprados y resultados desconocidos."""
    seen = {
        "captured": 0,
        "duplicate": 0,
        "refunds": 0,
        "bought": 0,
        "unknown": 0,
        "cancelled": 0,
        "completed": 0,
        "events": 0,
    }
    for seed in SEEDS[:20]:
        world, engine = make_world(seed)
        try:
            weights = [weight for weight, _, _ in OPERATIONS]
            for _ in range(STEPS):
                _, name, operation = world.rnd.choices(OPERATIONS, weights=weights)[0]
                run_operation(world, name, operation)
            with world.session() as db:
                payments = list(db.scalars(select(Payment)))
                seen["captured"] += sum(1 for p in payments if p.status == "SUCCEEDED")
                seen["duplicate"] += sum(1 for p in payments if p.status == "DUPLICATE_CAPTURE")
                seen["refunds"] += len(list(db.scalars(select(Refund))))
                fulfillments = list(db.scalars(select(Fulfillment)))
                seen["bought"] += sum(1 for f in fulfillments if f.purchased_at is not None)
                seen["unknown"] += sum(1 for a in db.scalars(select(ExternalAction)) if a.status == "UNKNOWN_OUTCOME")
                seen["cancelled"] += sum(1 for o in db.scalars(select(Order)) if o.status == "CANCELLED")
                seen["completed"] += sum(1 for f in fulfillments if f.status == "COMPLETED")
                seen["events"] += len(list(db.scalars(select(PaymentEvent))))
        finally:
            engine.dispose()
    assert all(count > 0 for count in seen.values()), (
        f"the walks never reached: {[k for k, v in seen.items() if v == 0]} ({seen})"
    )
