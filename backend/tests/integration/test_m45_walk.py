"""Caminatas aleatorias sobre M44 **con el registro de ingresos de M45 mirando cada paso** (Milestone 45, ADR 0030).

`test_m44_random_walk.py` recorre cientos de caminos que nadie imaginó, pero su `check_invariants` es de M44: no sabe
que existe un registro de ingresos verificados. Las pruebas del registro (`test_revenue_ledger*.py`) comprueban caminos
concretos. Faltaba lo que une las dos cosas: **el mismo azar, con el dinero verificado bajo la lupa después de cada
paso**. Esto es eso, y nada más:

1. Se reutilizan las operaciones, los proveedores con guion y el mundo de M44 (`m44_walk_test_support`): ni una
   operación nueva, ni un proveedor nuevo.
2. Después de **cada** paso: `check_invariants` (M44) + `check_revenue_invariants` (M45, oráculo independiente: cada
   entrada con su evento verificado, cada cobro con sus entradas, ningún reembolso por encima de lo capturado, ningún
   pedido pagado sin ingreso, los agregados iguales a las entradas) + el registro no se ha reescrito ni ha perdido nada.
3. **Un `UNKNOWN_OUTCOME` solo lo cierra quien puede**: una consulta al proveedor (`reconcile_lookup`) o una persona
   (`resolve_by_hand`). Ninguna otra operación, y menos el barrido o la reconciliación de eventos, lo toca (ADR 0029).

Si una semilla falla, el mensaje trae la semilla y las últimas operaciones: se reproduce tal cual. Una versión corre
sobre SQLite y otra sobre un PostgreSQL efímero de verdad (donde viven los índices parciales, los triggers y las
restricciones compuestas que el SQLite del resto de las pruebas no ejerce igual).
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
from m45_invariants_test_support import LedgerWatch, check_revenue_invariants
from pg_test_support import ephemeral_postgres
from sqlalchemy import select

from app.db.models.external_action import ExternalAction
from app.db.models.revenue import RevenueLedgerEntry

SEEDS = list(range(40))
PG_SEEDS = list(range(10))

#: Las únicas operaciones que pueden cerrar un resultado desconocido: preguntarle al proveedor, o que lo decida una
#: persona. Todo lo demás —incluidos el barrido y la reconciliación de eventos— debe dejarlo como estaba.
CLOSERS = {"reconcile_lookup", "resolve_by_hand"}


def _unknown(world) -> dict[str, str]:
    with world.session() as db:
        return {
            a.id: a.status for a in db.scalars(select(ExternalAction).where(ExternalAction.status == "UNKNOWN_OUTCOME"))
        }


def _status_of(world, action_ids) -> dict[str, str]:
    with world.session() as db:
        return {
            a.id: a.status for a in db.scalars(select(ExternalAction).where(ExternalAction.id.in_(list(action_ids))))
        }


def _step(world, watch: LedgerWatch, seed, step: int, name: str, operation) -> list[str]:
    before = _unknown(world)
    run_operation(world, name, operation)

    broken = verdict(world, seed, f"after step {step} ({name})")
    with world.session() as db:
        broken += [f"seed {seed} step {step} ({name}): {item}" for item in check_revenue_invariants(db)]
        broken += [f"seed {seed} step {step} ({name}): {item}" for item in watch.check(db)]

    if name not in CLOSERS and before:
        after = _status_of(world, before)
        moved = {
            action_id: (was, after.get(action_id)) for action_id, was in before.items() if after.get(action_id) != was
        }
        if moved:
            broken.append(
                f"seed {seed} step {step} ({name}): an UNKNOWN_OUTCOME was closed by an operation that is neither a "
                f"lookup nor a person: {moved}"
            )
    if broken:
        broken.append("operations: " + " > ".join(world.log[-20:]))
    return broken


def _walk(seed: int, engine=None, steps: int = STEPS) -> tuple[object, LedgerWatch, object]:
    world, built = make_world(seed, engine)
    watch = LedgerWatch()
    weights = [weight for weight, _, _ in OPERATIONS]
    for step in range(steps):
        _, name, operation = world.rnd.choices(OPERATIONS, weights=weights)[0]
        world.log.append(name)
        broken = _step(world, watch, seed, step, name, operation)
        assert not broken, "\n".join(broken)
    return world, watch, built


@pytest.mark.parametrize("seed", SEEDS)
def test_a_random_walk_keeps_the_verified_money_coherent_at_every_step(seed: int):
    world, _, engine = _walk(seed)
    engine.dispose()


@pytest.mark.parametrize("seed", PG_SEEDS)
def test_the_same_walk_on_a_real_postgresql_keeps_the_verified_money_coherent(seed: int):
    with ephemeral_postgres() as engine:
        _walk(5000 + seed, engine)


@pytest.mark.parametrize("seed", SEEDS[:12])
def test_after_the_tools_that_exist_run_the_ledger_still_matches_and_nothing_was_rewritten(seed: int):
    """Tras caminar, barrer, reconciliar eventos y resolver a mano (lo que existe), el dinero verificado sigue
    cuadrando, y un barrido más no mueve nada del registro."""
    world, watch, engine = _walk(2000 + seed)
    try:
        run_operation(world, "reconcile_events", reconcile_events)
        run_operation(world, "sweep", sweep)
        for _ in range(40):
            if not _unknown(world):
                break
            run_operation(world, "resolve_by_hand", resolve_by_hand)
        run_operation(world, "reconcile_events", reconcile_events)

        with world.session() as db:
            broken = check_revenue_invariants(db) + watch.check(db)
            count_before = len(list(db.scalars(select(RevenueLedgerEntry))))
        assert not broken, f"seed {2000 + seed}: " + "\n".join(broken)

        run_operation(world, "reconcile_events", reconcile_events)
        run_operation(world, "sweep", sweep)
        with world.session() as db:
            assert len(list(db.scalars(select(RevenueLedgerEntry)))) == count_before, "a quiet sweep moved the ledger"
            assert watch.check(db) == []
    finally:
        engine.dispose()


def test_the_walks_really_put_money_in_the_ledger_and_take_it_back():
    """Una caminata que nunca llega al dinero no prueba nada: entre todas las semillas hay capturas verificadas,
    dinero en revisión, reembolsos asentados y entradas en el registro."""
    seen = {"entries": 0, "captures": 0, "refunds": 0, "review": 0, "paid_orders": 0}
    for seed in SEEDS[:20]:
        world, _, engine = _walk(seed)
        try:
            with world.session() as db:
                entries = list(db.scalars(select(RevenueLedgerEntry)))
                seen["entries"] += len(entries)
                seen["captures"] += sum(
                    1 for e in entries if e.kind == "CAPTURE" and e.classification == "ORDER_PAYMENT"
                )
                seen["refunds"] += sum(1 for e in entries if e.kind == "REFUND")
                seen["review"] += sum(1 for e in entries if e.classification != "ORDER_PAYMENT")
        finally:
            engine.dispose()
    assert seen["entries"] and seen["captures"] and seen["refunds"] and seen["review"], (
        f"the walks never reached the money: {seen}"
    )
