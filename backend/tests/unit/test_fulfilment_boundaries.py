"""Las fronteras del fulfillment, hechas cumplir por pruebas (Milestone 44, ADR 0028 §6).

Una convención se olvida; una prueba que recorre el código, no. Cuatro promesas:

1. **Solo `orders/allocation.py` mueve `allocated_quantity`**, y solo `release_allocation()` lo reduce. Devolver
   unidades de un fulfillment que compró permitiría asignarlas a otro y comprarlas dos veces.
2. Solo `release_allocation()` cierra un fulfillment como `CANCELLED` o `FAILED`: ni el servicio ni el observador de la
   acción lo escriben por su cuenta.
3. Nadie borra un fulfillment ni sus líneas: lo que pasó queda.
4. Solo el servicio de fulfillment cierra un pedido (`COMPLETED`).
"""

import re
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"
ALLOCATION = "orders/allocation.py"


def python_files() -> list[Path]:
    return sorted(p for p in APP.rglob("*.py") if "__pycache__" not in p.parts)


def relative(path: Path) -> str:
    return path.relative_to(APP).as_posix()


def files_matching(pattern: str) -> set[str]:
    regex = re.compile(pattern, re.DOTALL)
    return {relative(p) for p in python_files() if regex.search(p.read_text(encoding="utf-8"))}


def test_only_the_allocation_module_writes_the_units_assigned_to_fulfillments():
    writers = files_matching(r"update\(\s*OrderItem\s*\)")

    assert writers == {ALLOCATION}, (
        f"{sorted(writers - {ALLOCATION})} write order items: `allocated_quantity` is moved with a single "
        "check-and-write statement in orders/allocation.py and nowhere else"
    )


def test_nobody_does_arithmetic_on_the_allocation_outside_the_allocation_module():
    # `allocated_quantity +/- …` en una expresión SQL o `x.allocated_quantity = / += / -= …` en Python.
    arithmetic = files_matching(r"allocated_quantity\s*[-+]|\.allocated_quantity\s*(?:[-+]?=)(?!=)")

    assert arithmetic == {ALLOCATION}, sorted(arithmetic - {ALLOCATION})


def test_only_release_allocation_reduces_the_allocation():
    source = (APP / ALLOCATION).read_text(encoding="utf-8")
    reductions = re.findall(r"allocated_quantity\s*-\s*", source)
    function_bodies = re.split(r"\ndef ", source)

    assert len(reductions) == 1, "the allocation module reduces the allocation in exactly one place"
    owners = [body.split("(")[0] for body in function_bodies if re.search(r"allocated_quantity\s*-\s*", body)]
    assert owners == ["release_allocation"], owners
    # La reducción solo se alcanza después de ganar el compare-and-set del fulfillment (nunca comprado).
    release = next(body for body in function_bodies if body.startswith("release_allocation"))
    assert release.index("claimed.rowcount") < release.index("allocated_quantity - quantity")
    for guard in ("FulfillmentStatus.READY.value", "purchased_at.is_(None)", "unknown_phase.is_(None)"):
        assert guard in release, f"the compare-and-set of release_allocation lost its condition {guard}"


def test_only_release_allocation_closes_a_fulfillment_as_cancelled_or_failed():
    projection = (APP / "orders" / "fulfilment_projection.py").read_text(encoding="utf-8")
    assert not re.search(r"FulfillmentStatus\.(?:FAILED|CANCELLED)", projection), (
        "the observer of an action never abandons a fulfillment: that is a decision of a person"
    )
    service = (APP / "orders" / "fulfilment.py").read_text(encoding="utf-8")
    assert service.count("update(Fulfillment)") == 1, "the service writes a fulfillment in one place: the delivery"
    assert "SHIPPED.value" in service.split("update(Fulfillment)")[1].split(")")[0]
    assert service.count("allocation.release_allocation(") == 1, "cancel and fail share one way back to the pool"


def test_nothing_deletes_a_fulfillment_or_its_lines():
    deleters = files_matching(r"delete\(\s*Fulfillment(?:Item)?\s*\)|\.delete\(\s*(?:fulfillment|item)\b")

    assert deleters == set(), sorted(deleters)


def test_only_the_fulfilment_service_completes_an_order():
    writers = files_matching(r"\.values\([^)]*status=OrderStatus\.COMPLETED")

    assert writers == {"orders/fulfilment.py"}, sorted(writers)


def test_the_order_is_locked_as_a_mutex_that_foreign_key_checks_do_not_wait_for():
    """`FOR UPDATE` sobre el pedido choca con el `FOR KEY SHARE` de las comprobaciones de clave foránea que
    PostgreSQL repite al actualizar dos veces una fila hija en una transacción: eso produjo un interbloqueo real entre
    comprar y cancelar. Todo bloqueo del pedido es `FOR NO KEY UPDATE`."""
    locks = []
    for path in python_files():
        for match in re.finditer(
            r"select\(Order\)\s*(?:\.\w+\([^)]*\)\s*)*?\.with_for_update\(([^)]*)\)",
            path.read_text(encoding="utf-8"),
        ):
            locks.append((relative(path), match.group(1)))

    assert len(locks) >= 5, "the lock sites of the order moved: update this test, do not delete it"
    assert [site for site, arguments in locks if "key_share=True" not in arguments] == []
