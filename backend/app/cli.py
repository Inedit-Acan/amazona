"""Management commands run by a human on the machine that owns the database.

There is deliberately no HTTP endpoint that grants roles: the first OWNER has to
exist before anyone can authenticate as one, and an endpoint able to create that
first OWNER would be an endpoint able to escalate anybody (Milestone 29,
ADR 0007).

    AMAZONA_BOOTSTRAP=1 python -m app.cli grant-role --email you@example.com --role OWNER

The budget the system may spend is authorised the same way: it is never created by
the system itself (hardening pre-M44, ADR 0023).

    AMAZONA_BOOTSTRAP=1 python -m app.cli authorise-budget --hard-limit 500 [--soft-limit 400]
    python -m app.cli show-budget

An external action whose outcome is unknown (the provider may have executed it and the answer was lost) is
never closed by the system on a guess. A person checks it, then says what happened (ADR 0024):

    python -m app.cli show-actions [--open]
    AMAZONA_BOOTSTRAP=1 python -m app.cli reconcile-actions [--older-than-minutes 60]
    AMAZONA_BOOTSTRAP=1 python -m app.cli resolve-action --id ID (--succeeded | --failed) --reason "..."

A test order is created from the console too (Milestone 44, ADR 0028). It carries no personal data: the customer is
an opaque reference that starts with `sim_` in a simulation.

    AMAZONA_BOOTSTRAP=1 python -m app.cli create-test-order --product-id ID --quantity 2 --unit-price 19.99 \
        [--currency EUR] [--market eu] [--customer-ref sim_demo] [--quote-id ID] [--unit-cost 8.50]

A payment is never confirmed by a command that edits an order. In a simulation, the simulated provider emits a
signed event that goes through the same door and the same service as the webhook of a real gateway would
(ADR 0028 §1); an event that was stored and not applied (the process died in between) is applied again:

    AMAZONA_BOOTSTRAP=1 python -m app.cli simulate-payment --order-id ID --outcome succeeded \
        [--payment-id ID] [--amount 50.00]
    AMAZONA_BOOTSTRAP=1 python -m app.cli simulate-refund --refund-id ID --outcome succeeded [--amount 10.00]
    AMAZONA_BOOTSTRAP=1 python -m app.cli reconcile-payment-events [--older-than-minutes 5]

A provider event id is received once. Delivering it again with the *same content* is a repeated delivery and changes
nothing; with *different content* it is refused as a conflict: the original event is kept, no payment, order or refund
is touched, and the command ends with a clean message and exit code 3 (a refusal of the command itself is exit code 2).
The simulator stamps every event with the instant it was made, so to repeat the identical delivery of an event id give
the same `--occurred-at` (an ISO 8601 instant with its time zone):

    AMAZONA_BOOTSTRAP=1 python -m app.cli simulate-payment --order-id ID --outcome succeeded
        --event-id evt_1 --occurred-at 2026-10-03T10:00:00+00:00

Requires AMAZONA_BOOTSTRAP=1 in the environment so the command cannot be run by
accident, and writes an audit entry for every grant.
"""

import argparse
import datetime
import os
import secrets
import sys

from sqlalchemy.orm import Session

from app.actions.contract import OPEN_STATUSES
from app.actions.service import ExternalActionService, ExternalActionStateError
from app.auth.actor import ActorSource, RoleName
from app.budgets.service import BudgetLedgerService
from app.core.errors import ConflictError, ValidationError
from app.core.ids import new_correlation_id
from app.db.models.audit import AuditLog
from app.db.models.budget import Budget
from app.db.models.external_action import ExternalAction
from app.db.models.role import Role
from app.db.models.user import User
from app.db.session import get_session_factory
from app.money.money import Money
from app.orders.service import NewOrderLine, OrderService
from app.payments.domain import EventProcessing
from app.payments.ingress import PaymentIngress, ProviderEventConflictError
from app.payments.port import PaymentEventType
from app.payments.providers.simulated import SimulatedPaymentProvider
from app.payments.service import PaymentService

BOOTSTRAP_ENV = "AMAZONA_BOOTSTRAP"

#: The command refused to run (a flag, an unknown id, a bad value).
EXIT_REFUSED = 2
#: The request was valid but what it acts on does not allow it: the CLI's 409. Nothing was changed.
EXIT_CONFLICT = 3


class BootstrapError(RuntimeError):
    """The command refused to run. Never a stack trace for the operator."""


def _require_bootstrap_flag(what: str = "roles") -> None:
    if os.environ.get(BOOTSTRAP_ENV) != "1":
        raise BootstrapError(
            f"refusing to change {what} without {BOOTSTRAP_ENV}=1 in the environment"
        )


def cli_actor() -> str:
    return f"cli:{os.environ.get('USERNAME') or os.environ.get('USER') or 'unknown'}"


def parse_occurred_at(value: str | None) -> datetime.datetime | None:
    """El instante que se le fija a un evento simulado, o `None` (el de ahora). Sin zona horaria no se acepta: un
    instante «ingenuo» no dice cuándo ocurrió."""
    if value is None:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError as exc:
        raise BootstrapError("--occurred-at must be an ISO 8601 instant such as 2026-10-03T10:00:00+00:00") from exc
    if parsed.tzinfo is None:
        raise BootstrapError("--occurred-at needs a time zone, for example 2026-10-03T10:00:00+00:00")
    return parsed


def authorise_budget(db: Session, *, hard_limit: float, soft_limit: float | None = None) -> Budget:
    """Autoriza (o cambia) el presupuesto con el que el sistema puede gastar. Es un acto del
    propietario y queda en la auditoría con el antes y el después: el sistema no crea ni
    inventa un presupuesto por su cuenta, y sin uno un gasto real se deniega."""
    try:
        return BudgetLedgerService(db).authorise_budget(
            hard_limit=hard_limit, soft_limit=soft_limit, actor=cli_actor()
        )
    except ValidationError as exc:
        raise BootstrapError(str(exc)) from exc


def list_actions(db: Session, *, only_open: bool = False) -> list[ExternalAction]:
    query = db.query(ExternalAction)
    if only_open:
        query = query.filter(ExternalAction.status.in_([status.value for status in OPEN_STATUSES]))
    return query.order_by(ExternalAction.created_at, ExternalAction.sequence).all()


def reconcile_actions(db: Session, *, older_than_minutes: int) -> dict[str, list[str]]:
    """El barrido de operaciones huérfanas: libera lo que nunca salió, marca como desconocido lo que
    pudo salir. `older_than_minutes` tiene que superar el arriendo de un trabajo: es la prueba de que su
    ejecutor ya no está."""
    if older_than_minutes < 1:
        raise BootstrapError("--older-than-minutes must be at least 1")
    return ExternalActionService(db).reconcile_interrupted(older_than=datetime.timedelta(minutes=older_than_minutes))


def resolve_action(db: Session, *, action_id: str, succeeded: bool, reason: str) -> ExternalAction:
    """Una persona cierra un resultado desconocido tras comprobarlo por su cuenta. Queda quién, cuándo y por qué."""
    action = db.get(ExternalAction, action_id)
    if action is None:
        raise BootstrapError(f"external action {action_id} not found")
    try:
        ExternalActionService(db).resolve(action, succeeded=succeeded, actor=cli_actor(), reason=reason)
    except (ValidationError, ExternalActionStateError) as exc:
        raise BootstrapError(str(exc)) from exc
    return action


def grant_role(db: Session, *, email: str, role_name: str, force: bool = False) -> User:
    try:
        role_value = RoleName(role_name.upper())
    except ValueError as exc:
        known = ", ".join(r.value for r in RoleName)
        raise BootstrapError(f"unknown role {role_name!r}; known roles: {known}") from exc

    role = db.query(Role).filter_by(name=role_value.value).one_or_none()
    if role is None:
        raise BootstrapError(
            f"role {role_value} is missing from the database; run `alembic upgrade head` first"
        )

    if role_value is RoleName.OWNER and not force:
        existing_owner = (
            db.query(User).filter(User.role_id == role.id, User.email != email).first()
        )
        if existing_owner is not None:
            raise BootstrapError(
                f"{existing_owner.email} is already OWNER; pass --force to add another one"
            )

    user = db.query(User).filter_by(email=email).one_or_none()
    before = {"role": None} if user is None else {"role": role_name_of(db, user)}
    if user is None:
        user = User(email=email, role_id=role.id)
        db.add(user)
    else:
        user.role_id = role.id

    db.flush()
    db.add(
        AuditLog(
            actor=f"cli:{os.environ.get('USERNAME') or os.environ.get('USER') or 'unknown'}",
            actor_role=RoleName.OWNER,
            actor_source=ActorSource.CLI,
            action="user.grant_role",
            resource=f"user:{user.id}",
            before=before,
            after={"role": role_value.value, "email": email},
            correlation_id=new_correlation_id(),
        )
    )
    db.commit()
    db.refresh(user)
    return user


def role_name_of(db: Session, user: User) -> str | None:
    if user.role_id is None:
        return None
    role = db.get(Role, user.role_id)
    return role.name if role else None


def create_test_order(
    db: Session,
    *,
    product_id: str,
    quantity: int,
    unit_price: str,
    currency: str = "EUR",
    market: str = "eu",
    customer_ref: str | None = None,
    quote_id: str | None = None,
    unit_cost: str | None = None,
):
    """Un pedido de prueba con una línea. Pasa por `OrderService`, como el de la API: mismas reglas, mismas
    validaciones. En una simulación la referencia de cliente se genera sola (`sim_…`); fuera de ella hay que dar
    una y no puede empezar por `sim_`."""
    from app.core.config import get_settings

    if customer_ref is None:
        if not get_settings().operating_in_simulation:
            raise BootstrapError("outside a simulation a test order needs an explicit --customer-ref")
        customer_ref = f"sim_{secrets.token_hex(6)}"
    line = NewOrderLine(
        product_id=product_id,
        quantity=quantity,
        unit_price=Money.of(unit_price, currency),
        supplier_quote_id=quote_id,
        declared_unit_cost=Money.of(unit_cost, currency) if unit_cost is not None else None,
    )
    return OrderService(db).create(
        customer_ref=customer_ref, market=market, lines=[line], actor=cli_actor(), correlation_id=new_correlation_id()
    )


SIMULATED_OUTCOMES = {
    "succeeded": PaymentEventType.PAYMENT_SUCCEEDED,
    "failed": PaymentEventType.PAYMENT_FAILED,
    "expired": PaymentEventType.PAYMENT_EXPIRED,
    "attempt-failed": PaymentEventType.PAYMENT_ATTEMPT_FAILED,
}


def simulate_payment(
    db: Session,
    *,
    outcome: str,
    order_id: str | None = None,
    payment_id: str | None = None,
    amount: str | None = None,
    event_id: str | None = None,
    occurred_at: datetime.datetime | None = None,
):
    """Emite un evento de pago **simulado** y lo entrega a la puerta, como lo haría el webhook de una pasarela.

    No toca pedidos ni cobros: el simulador firma el evento con su clave efímera, la puerta lo verifica y lo guarda,
    y `PaymentService` lo aplica. Solo existe en una simulación (el proveedor activo tiene que ser el simulado)."""
    from sqlalchemy import select

    from app.core.config import get_settings
    from app.core.errors import NotFoundError
    from app.db.models.payment import Payment
    from app.integrations.ports import IntegrationDomain
    from app.integrations.registry import ProviderNotAvailableError, ProviderRegistry

    try:
        provider = ProviderRegistry(get_settings()).resolve(IntegrationDomain.PAYMENTS)
    except ProviderNotAvailableError as exc:
        raise BootstrapError(f"no payment provider to emit events: {exc}") from exc
    if not isinstance(provider, SimulatedPaymentProvider):
        raise BootstrapError("only the simulated payment provider can emit events: a real gateway sends its own")
    if (order_id is None) == (payment_id is None):
        raise BootstrapError("say which payment: --payment-id, or --order-id for its latest attempt")
    if payment_id is not None:
        payment = db.get(Payment, payment_id)
    else:
        payment = db.scalars(
            select(Payment).where(Payment.order_id == order_id).order_by(Payment.attempt_number.desc())
        ).first()
    if payment is None:
        raise NotFoundError("no such payment")
    money = Money.of(amount if amount is not None else str(payment.amount), payment.currency)
    headers, raw = provider.simulate_event(
        SIMULATED_OUTCOMES[outcome],
        provider_payment_ref=payment.provider_payment_ref,
        client_reference=payment.id,
        amount=money if outcome == "succeeded" else None,
        failure_code="simulated" if outcome in ("failed", "attempt-failed") else None,
        event_id=event_id,
        occurred_at=occurred_at,
    )
    return PaymentIngress(db, provider=provider).receive(provider.name, headers, raw)


SIMULATED_REFUND_OUTCOMES = {
    "succeeded": PaymentEventType.REFUND_SUCCEEDED,
    "failed": PaymentEventType.REFUND_FAILED,
}


def simulate_refund(
    db: Session,
    *,
    refund_id: str,
    outcome: str,
    amount: str | None = None,
    event_id: str | None = None,
    occurred_at: datetime.datetime | None = None,
):
    """Emite el evento **simulado** con el que el proveedor confirma (o niega) un reembolso que pedimos, por la misma
    puerta que un webhook real. No toca reembolsos ni cobros: `PaymentService` lo aplica."""
    from app.core.config import get_settings
    from app.core.errors import NotFoundError
    from app.db.models.payment import Payment, Refund
    from app.integrations.ports import IntegrationDomain
    from app.integrations.registry import ProviderNotAvailableError, ProviderRegistry

    try:
        provider = ProviderRegistry(get_settings()).resolve(IntegrationDomain.PAYMENTS)
    except ProviderNotAvailableError as exc:
        raise BootstrapError(f"no payment provider to emit events: {exc}") from exc
    if not isinstance(provider, SimulatedPaymentProvider):
        raise BootstrapError("only the simulated payment provider can emit events: a real gateway sends its own")
    refund = db.get(Refund, refund_id)
    if refund is None:
        raise NotFoundError("no such refund")
    payment = db.get(Payment, refund.payment_id)
    assert payment is not None
    headers, raw = provider.simulate_event(
        SIMULATED_REFUND_OUTCOMES[outcome],
        provider_payment_ref=payment.provider_payment_ref,
        provider_refund_ref=refund.provider_refund_ref,
        client_reference=refund.id,
        amount=Money.of(amount if amount is not None else str(refund.amount), refund.currency),
        failure_code="simulated" if outcome == "failed" else None,
        event_id=event_id,
        occurred_at=occurred_at,
    )
    return PaymentIngress(db, provider=provider).receive(provider.name, headers, raw)


def reconcile_payment_events(db: Session, *, older_than_minutes: int) -> dict[str, int]:
    """Aplica de nuevo los eventos que se guardaron y no se aplicaron (el proceso cayó entre las dos transacciones).
    Nunca aplica uno reciente: podría estar aplicándose ahora mismo."""
    from sqlalchemy import select

    from app.db.models.payment import PaymentEvent

    if older_than_minutes < 1:
        raise ValidationError("the threshold must be at least one minute")
    limit = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=older_than_minutes)
    stuck = list(
        db.scalars(
            select(PaymentEvent)
            .where(PaymentEvent.processing_status == EventProcessing.RECEIVED.value, PaymentEvent.received_at < limit)
            .order_by(PaymentEvent.received_at)
        )
    )
    counts: dict[str, int] = {}
    for event in stuck:
        outcome = PaymentService(db).apply(event.id)
        counts[outcome.lower()] = counts.get(outcome.lower(), 0) + 1
    return counts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    grant = commands.add_parser("grant-role", help="give a person a role, creating the user if needed")
    grant.add_argument("--email", required=True)
    grant.add_argument("--role", required=True, help=", ".join(r.value for r in RoleName))
    grant.add_argument("--force", action="store_true", help="allow a second OWNER")

    commands.add_parser("list-users", help="show every user and its role")

    budget = commands.add_parser(
        "authorise-budget", help="authorise (or change) the budget the system may spend; audited"
    )
    budget.add_argument("--hard-limit", required=True, type=float, help="the most that can be reserved and spent")
    budget.add_argument("--soft-limit", type=float, help="a warning threshold below the hard limit")
    commands.add_parser("show-budget", help="show the authorised budget and what has been used")

    actions = commands.add_parser("show-actions", help="list the external actions and where each one stands")
    actions.add_argument("--open", action="store_true", help="only those not yet closed")
    sweep = commands.add_parser(
        "reconcile-actions", help="release reservations whose request never left; mark the rest as unknown"
    )
    sweep.add_argument("--older-than-minutes", type=int, default=60, help="must exceed a job lease (default 60)")
    resolve = commands.add_parser("resolve-action", help="close an action of unknown outcome after checking it")
    resolve.add_argument("--id", required=True)
    outcome = resolve.add_mutually_exclusive_group(required=True)
    outcome.add_argument("--succeeded", action="store_true", help="the effect did happen: commit the reservation")
    outcome.add_argument("--failed", action="store_true", help="the effect did not happen: release the reservation")
    resolve.add_argument("--reason", required=True, help="what you checked and where")

    order = commands.add_parser("create-test-order", help="create an order with one line, with no personal data")
    order.add_argument("--product-id", required=True)
    order.add_argument("--quantity", required=True, type=int)
    order.add_argument("--unit-price", required=True, help="a decimal such as 19.99, never a float literal in code")
    order.add_argument("--currency", default="EUR")
    order.add_argument("--market", default="eu")
    order.add_argument("--customer-ref", help="an opaque reference; sim_… is generated in a simulation")
    order.add_argument("--quote-id", help="the supplier quote the line would be bought from")
    order.add_argument("--unit-cost", help="the supplier cost per unit, if you know it; otherwise it stays unknown")

    simulate = commands.add_parser(
        "simulate-payment", help="emit a signed simulated payment event through the same door as a real webhook"
    )
    simulate.add_argument("--order-id", help="the order; its latest payment attempt is used")
    simulate.add_argument("--payment-id", help="a specific payment attempt")
    simulate.add_argument("--outcome", required=True, choices=sorted(SIMULATED_OUTCOMES))
    simulate.add_argument("--amount", help="the captured amount (default: the amount of the payment)")
    simulate.add_argument(
        "--event-id", help="a fixed provider event id; using it again with different content is refused as a conflict"
    )
    simulate.add_argument(
        "--occurred-at",
        help="a fixed instant (ISO 8601 with time zone): with the same --event-id it repeats the same delivery",
    )
    sim_refund = commands.add_parser(
        "simulate-refund", help="emit a signed simulated refund event through the same door as a real webhook"
    )
    sim_refund.add_argument("--refund-id", required=True)
    sim_refund.add_argument("--outcome", required=True, choices=sorted(SIMULATED_REFUND_OUTCOMES))
    sim_refund.add_argument("--amount", help="the refunded amount (default: the amount of the refund)")
    sim_refund.add_argument("--event-id", help="a fixed provider event id")
    sim_refund.add_argument(
        "--occurred-at",
        help="a fixed instant (ISO 8601 with time zone): with the same --event-id it repeats the same delivery",
    )
    stuck = commands.add_parser("reconcile-payment-events", help="apply the events that were stored and never applied")
    stuck.add_argument("--older-than-minutes", type=int, default=5)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db = get_session_factory()()
    try:
        if args.command == "grant-role":
            _require_bootstrap_flag()
            user = grant_role(db, email=args.email, role_name=args.role, force=args.force)
            print(f"{user.email} is now {args.role.upper()}")
        elif args.command == "authorise-budget":
            _require_bootstrap_flag("the budget")
            budget = authorise_budget(db, hard_limit=args.hard_limit, soft_limit=args.soft_limit)
            print(f"budget authorised: hard limit {float(budget.hard_limit):.2f}")
        elif args.command == "show-budget":
            snapshot = BudgetLedgerService(db).snapshot()
            if snapshot is None:
                print("no budget authorised: real spending is denied until the owner authorises one")
            else:
                print(
                    f"hard limit {snapshot.hard_limit:.2f} | reserved {snapshot.reserved:.2f} | "
                    f"committed {snapshot.committed:.2f} | spent {snapshot.spent:.2f}"
                )
        elif args.command == "show-actions":
            rows = list_actions(db, only_open=args.open)
            if not rows:
                print("no open external actions" if args.open else "no external actions")
            for action in rows:
                amount = f"{float(action.amount):.2f}" if action.amount is not None else "-"
                print(
                    f"{action.id} {action.status:16} #{action.sequence} {action.provider}/{action.operation} "
                    f"amount {amount} {action.reference}"
                )
        elif args.command == "reconcile-actions":
            _require_bootstrap_flag("external actions")
            swept = reconcile_actions(db, older_than_minutes=args.older_than_minutes)
            print(
                f"released (never sent): {len(swept['released'])} | "
                f"now unknown (may have been sent): {len(swept['unknown'])}"
            )
            for action_id in swept["unknown"]:
                print(f"  check by hand, then resolve-action: {action_id}")
        elif args.command == "resolve-action":
            _require_bootstrap_flag("external actions")
            closed = resolve_action(db, action_id=args.id, succeeded=args.succeeded, reason=args.reason)
            print(f"{closed.id} is now {closed.status}")
        elif args.command == "create-test-order":
            _require_bootstrap_flag("orders")
            created = create_test_order(
                db,
                product_id=args.product_id,
                quantity=args.quantity,
                unit_price=args.unit_price,
                currency=args.currency,
                market=args.market,
                customer_ref=args.customer_ref,
                quote_id=args.quote_id,
                unit_cost=args.unit_cost,
            )
            print(f"order {created.id} created for {created.customer_ref}: {created.amount_due} {created.currency}")
        elif args.command == "simulate-payment":
            _require_bootstrap_flag("payments")
            result = simulate_payment(
                db,
                outcome=args.outcome,
                order_id=args.order_id,
                payment_id=args.payment_id,
                amount=args.amount,
                event_id=args.event_id,
                occurred_at=parse_occurred_at(args.occurred_at),
            )
            repeated = " (a repeated delivery)" if result.duplicate else ""
            print(f"event {result.event_id}: {result.outcome}{repeated}")
        elif args.command == "simulate-refund":
            _require_bootstrap_flag("payments")
            refund_result = simulate_refund(
                db,
                refund_id=args.refund_id,
                outcome=args.outcome,
                amount=args.amount,
                event_id=args.event_id,
                occurred_at=parse_occurred_at(args.occurred_at),
            )
            repeated = " (a repeated delivery)" if refund_result.duplicate else ""
            print(f"event {refund_result.event_id}: {refund_result.outcome}{repeated}")
        elif args.command == "reconcile-payment-events":
            _require_bootstrap_flag("payments")
            applied = reconcile_payment_events(db, older_than_minutes=args.older_than_minutes)
            print("applied: " + (", ".join(f"{k} {v}" for k, v in sorted(applied.items())) or "nothing to apply"))
        elif args.command == "list-users":
            users = db.query(User).order_by(User.email).all()
            if not users:
                print("no users yet")
            for user in users:
                linked = "linked" if user.subject else "never signed in"
                print(f"{user.email:40} {role_name_of(db, user) or '(no role)':10} {linked}")
    except BootstrapError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except ProviderEventConflictError as exc:
        # El identificador ya se recibió con otro contenido: el original se conserva y no se tocó nada. Ni el cuerpo ni
        # su hash salen por la consola.
        print(
            f"error: provider event {exc.provider_event_id!r} was already received with different content; "
            "the original event is kept and nothing was changed. Use a new --event-id for a different event, "
            "or repeat the identical delivery with the same --event-id, --occurred-at, --amount and --outcome.",
            file=sys.stderr,
        )
        return EXIT_CONFLICT
    except ConflictError as exc:
        # El 409 de la consola: lo pedido es válido pero lo que toca no está en un estado que lo permita.
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_CONFLICT
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
