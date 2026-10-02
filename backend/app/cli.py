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
from app.core.errors import ValidationError
from app.core.ids import new_correlation_id
from app.db.models.audit import AuditLog
from app.db.models.budget import Budget
from app.db.models.external_action import ExternalAction
from app.db.models.role import Role
from app.db.models.user import User
from app.db.session import get_session_factory
from app.money.money import Money
from app.orders.service import NewOrderLine, OrderService

BOOTSTRAP_ENV = "AMAZONA_BOOTSTRAP"


class BootstrapError(RuntimeError):
    """The command refused to run. Never a stack trace for the operator."""


def _require_bootstrap_flag(what: str = "roles") -> None:
    if os.environ.get(BOOTSTRAP_ENV) != "1":
        raise BootstrapError(
            f"refusing to change {what} without {BOOTSTRAP_ENV}=1 in the environment"
        )


def cli_actor() -> str:
    return f"cli:{os.environ.get('USERNAME') or os.environ.get('USER') or 'unknown'}"


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
        elif args.command == "list-users":
            users = db.query(User).order_by(User.email).all()
            if not users:
                print("no users yet")
            for user in users:
                linked = "linked" if user.subject else "never signed in"
                print(f"{user.email:40} {role_name_of(db, user) or '(no role)':10} {linked}")
    except BootstrapError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
