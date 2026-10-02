"""La matriz de caídas: cinco puntos × cuatro dominios (Milestone 44, ADR 0024 y ADR 0028 §3).

Una operación externa cruza cinco puntos entre que nace y que su resultado queda en el dominio. Si el proceso muere en
cada uno de ellos —y las pruebas lo matan de verdad: una excepción que no es `Exception` atraviesa todos los `except`
del código, como una caída—, el estado tiene que ser **uno de los definidos** y la recuperación, la que existe:

    A  antes de `begin_call`                       nada salió: la acción sigue `PENDING`, el dominio dice «nada enviado»
    B  justo después de `begin_call`               pudo salir y no salió: `CALLING`, el dominio dice «posiblemente
    enviado» C  respuesta del proveedor, sin persistir      salió y hay efecto: para la base de datos es igual que B D
    acción persistida, sin proyectar            la acción y el dominio van en **la misma transacción**: no existe E
    dominio proyectado, sin cerrar              «a medias»: la caída lo deshace todo y queda igual que C

Para cada punto y dominio (cobro, reembolso, compra, envío) se afirma el estado final, qué queda reservado, qué puede
reintentarse, qué necesita reconciliación y qué **nunca** se repite: el proveedor recibe **como mucho una** llamada, y
los invariantes globales se cumplen en cada etapa.
"""

import datetime

import pytest
from fulfilment_test_support import (
    REQUESTER as FULFILMENT_REQUESTER,
)
from fulfilment_test_support import (
    ScriptedFulfilmentProvider,
    create_fulfillment,
    paid_order,
    service,
)
from m44_invariants_test_support import check_invariants, provider_calls_never_exceed_the_frontier
from order_test_support import add_product, make_engine, session_factory
from payment_test_support import (
    REQUESTER,
    SIMULATION,
    ScriptedPaymentProvider,
    add_order,
    deliver,
    start_attempt,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.actions.service import ExternalActionService
from app.budgets.service import BudgetLedgerService
from app.core.errors import ConflictError
from app.db.models.external_action import ExternalAction
from app.db.models.fulfillment import Fulfillment
from app.db.models.payment import Payment, Refund
from app.money.money import Money
from app.orders.fulfilment_projection import fulfilment_reference
from app.orders.payment_attempts import PaymentAttemptService
from app.orders.refunds import RefundService
from app.payments.port import PaymentEventType
from app.payments.projection import payment_reference
from app.payments.refund_projection import refund_reference

LONG_AGO = datetime.timedelta(seconds=-1)


class ProcessDied(BaseException):
    """La muerte del proceso: no es una `Exception`, así que ningún `except Exception` del código la traga."""


# --- Los cuatro dominios, con el mismo gesto -----------------------------------------------------------------------


class Domain:
    name = ""
    #: Estados del dominio en cada situación del recorrido.
    NOT_SENT = ""
    SENT = ""
    ACCEPTED = ""
    RELEASED = ""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.baseline = 0

    # Se implementan en cada dominio.
    def arrange(self) -> None: ...
    def trigger(self) -> None: ...
    def reference(self) -> str: ...
    def status(self) -> str: ...
    def reserved(self) -> float: ...
    def failed_attempts(self) -> int: ...
    def retry(self) -> None: ...
    def provider(self): ...

    def effects(self) -> int:
        """Cuántas veces ejecutó el proveedor **esta** operación (sin contar la preparación)."""
        return len(self.provider().calls) - self.baseline

    def action(self) -> ExternalAction | None:
        self.db.expire_all()
        return self.db.scalars(
            select(ExternalAction)
            .where(ExternalAction.reference == self.reference())
            .order_by(ExternalAction.sequence.desc())
        ).first()

    def adapter(self):
        return self.provider()


class PaymentDomain(Domain):
    name = "payment"
    NOT_SENT, SENT, ACCEPTED, RELEASED = "REQUESTED", "OPENING", "OPEN", "FAILED"

    def arrange(self) -> None:
        self._provider = ScriptedPaymentProvider()
        self.order_id = add_order(self.db, add_product(self.db)).id
        self.baseline = 0

    def provider(self):
        return self._provider

    def trigger(self) -> None:
        PaymentAttemptService(self.db, settings=SIMULATION, provider=self._provider).start(
            self.order_id, requester=REQUESTER
        )

    def _payment(self) -> Payment:
        self.db.expire_all()
        return self.db.scalars(
            select(Payment).where(Payment.order_id == self.order_id).order_by(Payment.attempt_number.desc())
        ).first()  # type: ignore[return-value]

    def reference(self) -> str:
        return payment_reference(self._payment().id)

    def status(self) -> str:
        return self._payment().status

    def reserved(self) -> float:
        return 0.0  # abrir un cobro no aparta dinero

    def failed_attempts(self) -> int:
        return 0

    def retry(self) -> None:
        self.trigger()


class RefundDomain(Domain):
    name = "refund"
    NOT_SENT, SENT, ACCEPTED, RELEASED = "REQUESTED", "SENDING", "SENDING", "FAILED"

    def arrange(self) -> None:
        self._provider = ScriptedPaymentProvider()
        order = add_order(self.db, add_product(self.db))
        payment = start_attempt(self.db, order, self._provider)
        deliver(self.db, self._provider, PaymentEventType.PAYMENT_SUCCEEDED, payment)
        self.payment_id = payment.id
        self.baseline = len(self._provider.calls)

    def provider(self):
        return self._provider

    def trigger(self) -> None:
        RefundService(self.db, settings=SIMULATION, provider=self._provider).request(
            self.payment_id, amount=Money.of("10.00", "EUR"), reason="customer_request", requester=REQUESTER
        )

    def _refund(self) -> Refund:
        self.db.expire_all()
        return self.db.scalars(
            select(Refund).where(Refund.payment_id == self.payment_id).order_by(Refund.requested_at.desc())
        ).first()  # type: ignore[return-value]

    def reference(self) -> str:
        return refund_reference(self._refund().id)

    def status(self) -> str:
        return self._refund().status

    def reserved(self) -> float:
        self.db.expire_all()
        return float(self.db.get(Payment, self.payment_id).refund_committed_amount)  # type: ignore[union-attr]

    def failed_attempts(self) -> int:
        return 0

    def retry(self) -> None:
        self.trigger()


class FulfilmentDomain(Domain):
    phase = ""

    def arrange(self) -> None:
        self._provider = ScriptedFulfilmentProvider()
        order = paid_order(self.db)
        BudgetLedgerService(self.db).authorise_budget(hard_limit=1000.0, actor="owner@amazona.local")
        self.fulfillment_id = create_fulfillment(self.db, order, self._provider).id
        if self.phase == "ship":
            service(self.db, self._provider).purchase(self.fulfillment_id, requester=FULFILMENT_REQUESTER)
        self.baseline = len(self._provider.calls)

    def provider(self):
        return self._provider

    def trigger(self) -> None:
        operation = service(self.db, self._provider)
        if self.phase == "purchase":
            operation.purchase(self.fulfillment_id, requester=FULFILMENT_REQUESTER)
        else:
            operation.ship(self.fulfillment_id, requester=FULFILMENT_REQUESTER)

    def _fulfillment(self) -> Fulfillment:
        self.db.expire_all()
        return self.db.get(Fulfillment, self.fulfillment_id)  # type: ignore[return-value]

    def reference(self) -> str:
        return fulfilment_reference(self.fulfillment_id, self.phase)

    def status(self) -> str:
        return self._fulfillment().status

    def failed_attempts(self) -> int:
        return self._fulfillment().failed_attempts

    def retry(self) -> None:
        self.trigger()


class PurchaseDomain(FulfilmentDomain):
    name = "purchase"
    phase = "purchase"
    NOT_SENT, SENT, ACCEPTED, RELEASED = "READY", "PURCHASING", "PURCHASED", "READY"

    def reserved(self) -> float:
        snapshot = BudgetLedgerService(self.db).snapshot()
        return snapshot.reserved if snapshot else 0.0


class ShipDomain(FulfilmentDomain):
    name = "ship"
    phase = "ship"
    NOT_SENT, SENT, ACCEPTED, RELEASED = "PURCHASED", "SHIPPING", "SHIPPED", "PURCHASED"

    def reserved(self) -> float:
        snapshot = BudgetLedgerService(self.db).snapshot()
        return snapshot.reserved if snapshot else 0.0


DOMAINS = [PaymentDomain, RefundDomain, PurchaseDomain, ShipDomain]
#: Lo que se aparta mientras la operación está abierta (la compra aparta su coste: 4 × 6.00 + 2 × 2.50).
RESERVED_WHILE_OPEN = {"payment": 0.0, "refund": 10.0, "purchase": 29.0, "ship": 0.0}


# --- Inyección de caídas --------------------------------------------------------------------------------------------


def die(*_args, **_kwargs):
    raise ProcessDied("the process died here")


def inject(point: str, domain: Domain, monkeypatch) -> None:
    provider = domain.provider()
    real_execute = provider.execute
    real_notify = ExternalActionService._notify

    if point == "A":  # antes de `begin_call`
        monkeypatch.setattr(ExternalActionService, "begin_call", die)
    elif point == "B":  # justo después de `begin_call`, antes de que la petición llegue al proveedor
        monkeypatch.setattr(provider, "execute", die)
    elif point == "C":  # el proveedor ejecutó y respondió; el proceso muere antes de persistir el resultado

        def executed_then_died(request):
            real_execute(request)
            raise ProcessDied("the provider executed and the process died before persisting")

        monkeypatch.setattr(provider, "execute", executed_then_died)
    elif point == "D":  # la acción cambió de estado en la transacción; muere antes de seguir
        monkeypatch.setattr(ExternalActionService, "_move_ledger", die)
    elif point == "E":  # el dominio ya se proyectó en la transacción; muere antes de confirmarla

        def projected_then_died(self, action, previous, current, response=None):
            real_notify(self, action, previous, current, response)
            if current == "SUCCEEDED":
                raise ProcessDied("the domain was projected and the process died before the commit")

        monkeypatch.setattr(ExternalActionService, "_notify", projected_then_died)
    else:  # pragma: no cover
        raise AssertionError(point)


@pytest.fixture()
def db():
    engine = make_engine()
    session = session_factory(engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def healthy(domain: Domain, where: str) -> None:
    broken = check_invariants(domain.db) + provider_calls_never_exceed_the_frontier(
        domain.db, len(domain.provider().calls)
    )
    assert not broken, f"{domain.name} {where}: {broken}"


def sweep(domain: Domain) -> dict:
    return ExternalActionService(domain.db).reconcile_interrupted(older_than=LONG_AGO)


def crashed(domain: Domain, point: str, monkeypatch) -> None:
    inject(point, domain, monkeypatch)
    with pytest.raises(ProcessDied):
        domain.trigger()
    monkeypatch.undo()
    domain.db.rollback()  # el proceso murió: lo que no estaba confirmado se pierde
    healthy(domain, f"after dying at {point}")


# --- A: antes de la frontera -----------------------------------------------------------------------------------


@pytest.mark.parametrize("domain_class", DOMAINS, ids=lambda c: c.name)
def test_A_dying_before_the_call_sent_nothing_and_the_sweep_releases_what_was_set_aside(domain_class, db, monkeypatch):
    domain = domain_class(db)
    domain.arrange()

    crashed(domain, "A", monkeypatch)

    assert domain.status() == domain.NOT_SENT, "nothing was sent: the domain says so"
    assert domain.action().status == "PENDING" and domain.effects() == 0
    assert domain.reserved() == RESERVED_WHILE_OPEN[domain.name], (
        "what was set aside stays until someone knows it never left"
    )

    swept = sweep(domain)

    assert len(swept["released"]) == 1 and swept["unknown"] == []
    assert domain.action().status == "FAILED_CONFIRMED"
    assert domain.status() == domain.RELEASED
    assert domain.reserved() == 0.0, "the reservation went back: the request never left"
    assert domain.failed_attempts() == 0, "an attempt that never left is not a failure"
    healthy(domain, "after the sweep")

    domain.retry()  # lo que nunca salió se puede volver a intentar, y sale una sola vez
    assert domain.effects() == 1
    healthy(domain, "after the retry")


# --- B: justo después de la frontera
# -------------------------------------------------------------------------------------


class OpaqueAdapter:
    """Un adaptador que solo sabe ejecutar: ni consulta ni idempotencia. Lo único honesto que puede decir sobre una
    operación de resultado desconocido es «no lo sé»."""

    supports_idempotency = False

    def __init__(self, inner) -> None:
        self._inner = inner
        self.name = inner.name

    def execute(self, request):
        return self._inner.execute(request)


def died_right_after_the_frontier(domain_class, db, monkeypatch) -> Domain:
    domain = domain_class(db)
    domain.arrange()

    crashed(domain, "B", monkeypatch)

    assert domain.status() == domain.SENT, "past the frontier: it may have left"
    assert domain.action().status == "CALLING" and domain.effects() == 0
    assert domain.reserved() == RESERVED_WHILE_OPEN[domain.name]
    calls = len(domain.provider().calls)
    if domain.name != "refund":
        # Reintentar el cobro, la compra o el envío es **la misma** operación: no se repite a ciegas. (Pedir otro
        # reembolso no es un reintento: es otra intención, y mientras quepa en lo cobrado se aparta otro importe.)
        with pytest.raises(ConflictError):
            domain.retry()
        assert len(domain.provider().calls) == calls

    sweep(domain)

    assert domain.action().status == "UNKNOWN_OUTCOME"
    assert domain.status() == "UNKNOWN_OUTCOME"
    assert domain.reserved() == RESERVED_WHILE_OPEN[domain.name], "an unknown outcome releases nothing"
    with pytest.raises(ConflictError):
        domain.retry()  # un resultado desconocido bloquea la siguiente operación del mismo sitio (también un reembolso)
    assert len(domain.provider().calls) == calls
    healthy(domain, "after the sweep")
    return domain


@pytest.mark.parametrize("domain_class", DOMAINS, ids=lambda c: c.name)
def test_B_a_provider_that_can_look_it_up_and_has_no_such_operation_closes_it_as_never_executed(
    domain_class, db, monkeypatch
):
    domain = died_right_after_the_frontier(domain_class, db, monkeypatch)

    # Un adaptador que sabe consultar y dice «no tengo esa operación» **sabe** que no hubo efecto (ADR 0024): no es una
    # suposición, es la respuesta del proveedor a la clave de la operación.
    status = ExternalActionService(db).reconcile(domain.action(), domain.adapter(), {})

    assert status.value == "FAILED_CONFIRMED"
    assert domain.status() == domain.RELEASED and domain.reserved() == 0.0
    assert domain.failed_attempts() == (0 if domain.name in ("payment", "refund") else 1)
    assert domain.effects() == 0
    healthy(domain, "after the negative lookup")


@pytest.mark.parametrize("domain_class", DOMAINS, ids=lambda c: c.name)
def test_B_an_adapter_that_cannot_look_it_up_leaves_it_unknown_until_a_person_decides(domain_class, db, monkeypatch):
    domain = died_right_after_the_frontier(domain_class, db, monkeypatch)

    status = ExternalActionService(db).reconcile(domain.action(), OpaqueAdapter(domain.provider()), {})

    assert status.value == "UNKNOWN_OUTCOME", "never turned into a safe failure on a guess"
    assert domain.status() == "UNKNOWN_OUTCOME"
    assert domain.reserved() == RESERVED_WHILE_OPEN[domain.name]

    ExternalActionService(db).resolve(domain.action(), succeeded=False, actor="owner@amazona.local", reason="checked")

    assert domain.status() == domain.RELEASED and domain.reserved() == 0.0
    assert domain.failed_attempts() == (0 if domain.name in ("payment", "refund") else 1)
    assert domain.effects() == 0
    healthy(domain, "after the human resolution")


# --- C, D, E: el proveedor ejecutó; el resultado no llegó a quedar
# -------------------------------------------------------


@pytest.mark.parametrize("point", ["C", "D", "E"])
@pytest.mark.parametrize("domain_class", DOMAINS, ids=lambda c: c.name)
def test_C_D_E_when_the_provider_executed_the_database_never_says_half_done(domain_class, point, db, monkeypatch):
    domain = domain_class(db)
    domain.arrange()

    crashed(domain, point, monkeypatch)

    # C, D y E son **el mismo estado** para la base de datos: la acción y el dominio van en la misma transacción, así
    # que una caída entre la persistencia y la proyección (D), o entre la proyección y el cierre (E), lo deshace todo.
    assert domain.action().status == "CALLING", f"{point}: the result of the call never became the action's state"
    assert domain.status() == domain.SENT, f"{point}: the domain did not move ahead of its action"
    assert domain.effects() == 1, f"{point}: the provider did execute"
    assert domain.reserved() == RESERVED_WHILE_OPEN[domain.name]
    assert domain.action().applied_at is None

    sweep(domain)
    assert domain.action().status == "UNKNOWN_OUTCOME" and domain.status() == "UNKNOWN_OUTCOME"
    assert domain.reserved() == RESERVED_WHILE_OPEN[domain.name]

    status = ExternalActionService(db).reconcile(domain.action(), domain.adapter(), {})

    assert status.value == "SUCCEEDED", "the lookup finds the operation the provider did execute"
    assert domain.status() == domain.ACCEPTED
    assert domain.effects() == 1, "the lookup asked; it did not execute again"
    if domain.name == "refund":
        assert domain.reserved() == 10.0, "accepted is not refunded: the reservation stays until a verified fact"
    if domain.name == "purchase":
        snapshot = BudgetLedgerService(db).snapshot()
        assert (
            snapshot is not None
            and snapshot.reserved == pytest.approx(0.0)
            and snapshot.committed == pytest.approx(29.0)
        )
    healthy(domain, f"after reconciling {point}")


@pytest.mark.parametrize("domain_class", DOMAINS, ids=lambda c: c.name)
def test_a_second_worker_cannot_repeat_what_the_dead_one_may_have_sent(domain_class, db, monkeypatch):
    """Otro proceso que llega después de la caída: no puede ejecutar la operación otra vez; solo la reconciliación o una
    persona la cierran. El proveedor sigue con una sola ejecución."""
    domain = domain_class(db)
    domain.arrange()
    crashed(domain, "C", monkeypatch)
    sweep(domain)
    calls = len(domain.provider().calls)

    with pytest.raises(ConflictError):
        domain.retry()
    again = ExternalActionService(db).reconcile(domain.action(), domain.adapter(), {})
    after = ExternalActionService(db).reconcile(domain.action(), domain.adapter(), {})

    assert again.value == "SUCCEEDED" and after.value == "SUCCEEDED", "the second reconciliation changes nothing"
    assert len(domain.provider().calls) == calls
    healthy(domain, "after two workers")
