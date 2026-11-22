"""Payments and deliveries schema on the isolated test database.

DATABASE_SCHEMA.md §8.2, §9.2, §9.3; DEC-116, DEC-121, DEC-134.
Each test runs inside a rolled-back transaction (`db_session`).
Lifecycle and assignment rules are service-layer rules and are not tested
here; only what the database itself enforces.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import DataError, IntegrityError, InvalidRequestError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.modules.delivery.models import CourierAssignment, Delivery, DeliveryZone
from app.modules.orders.models import Order
from app.modules.payments.models import Payment, PaymentMethod
from app.modules.users.models import User

pytestmark = pytest.mark.db

TABLES = ("payments", "deliveries", "courier_assignments")


# --------------------------------------------------------------------------- helpers


def _add(session: Session, *objects: object) -> None:
    session.add_all(objects)
    session.flush()


def _expect_integrity_error(session: Session, *objects: object) -> None:
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add_all(objects)
        session.flush()


def _expect_sql_error(session: Session, sql: str, **params: object) -> str:
    with pytest.raises(IntegrityError) as excinfo, session.begin_nested():
        session.execute(text(sql), params)
    return str(excinfo.value.orig)


def _count(session: Session, table: str, column: str, value: object) -> int:
    return session.execute(
        text(f"SELECT count(*) FROM {table} WHERE {column} = :v"),  # noqa: S608 - test literals
        {"v": value},
    ).scalar_one()


def _now() -> datetime:
    return datetime.now(UTC)


def _user(session: Session, name: str) -> User:
    user = User(email=f"{name}@example.kg", password_hash="h", full_name=name.title())
    _add(session, user)
    return user


def _order(session: Session, user: User, **values: object) -> Order:
    defaults: dict[str, object] = {
        "user_id": user.id,
        "language_code": "ru",
        "delivery_type": "delivery",
        "payment_method_code": "cash",
        "subtotal": Decimal("600.00"),
        "delivery_fee": Decimal("100.00"),
        "total_amount": Decimal("700.00"),
        "customer_name": "Айбек",
        "customer_phone": "+996700123456",
        "delivery_address_text": "ул. Ленина, 1",
        "delivery_latitude": Decimal("40.5283000"),
        "delivery_longitude": Decimal("72.7985000"),
    }
    order = Order(**(defaults | values))
    _add(session, order)
    return order


def _method(session: Session) -> PaymentMethod:
    # Unique code per test: independent of any seeded rows.
    method = PaymentMethod(code=f"test_{uuid.uuid4().hex[:12]}")
    _add(session, method)
    return method


def _payment(order: Order, method: PaymentMethod, **values: object) -> Payment:
    defaults: dict[str, object] = {
        "order_id": order.id,
        "payment_method_id": method.id,
        "amount": Decimal("700.00"),
        "status": "pending",
    }
    return Payment(**(defaults | values))


def _assignment(order: Order, courier: User, **values: object) -> CourierAssignment:
    defaults: dict[str, object] = {
        "order_id": order.id,
        "courier_id": courier.id,
        "assignment_type": "manual",
        "assigned_at": _now(),
    }
    return CourierAssignment(**(defaults | values))


@pytest.fixture
def ctx(db_session: Session) -> tuple[Session, Order, PaymentMethod, User]:
    customer = _user(db_session, "customer")
    courier = _user(db_session, "courier")
    return db_session, _order(db_session, customer), _method(db_session), courier


# --------------------------------------------------------------------------- structure

EXPECTED_COLUMNS = {
    "payments": {
        "id": False, "order_id": False, "payment_method_id": False, "amount": False,
        "currency": False, "status": False, "transaction_reference": True,
        "is_simulated": False, "paid_at": True, "refunded_at": True,
        "created_at": False, "updated_at": False,
    },
    "deliveries": {
        "id": False, "order_id": False, "delivery_zone_id": True, "delivery_comment": True,
        "delivered_at": True, "created_at": False, "updated_at": False,
    },
    "courier_assignments": {
        "id": False, "order_id": False, "courier_id": False, "assigned_by": True,
        "assignment_type": False, "status": False, "assigned_at": False,
        "accepted_at": True, "declined_at": True, "decline_reason": True,
        "completed_at": True,
    },
}  # fmt: skip


@pytest.mark.parametrize("table", TABLES)
def test_columns_and_nullability(db_session: Session, table: str) -> None:
    columns = {
        column["name"]: column["nullable"]
        for column in inspect(db_session.connection()).get_columns(table)
    }
    assert columns == EXPECTED_COLUMNS[table]


def test_column_types_and_defaults(db_session: Session) -> None:
    rows = db_session.execute(
        text(
            "SELECT table_name || '.' || column_name, udt_name, character_maximum_length, "
            "numeric_precision, numeric_scale, column_default FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = ANY(:tables)"
        ),
        {"tables": list(TABLES)},
    ).all()
    info = {name: tuple(rest) for name, *rest in rows}

    assert info["payments.amount"][:4] == ("numeric", None, 12, 2)
    assert info["payments.amount"][4] is None
    assert info["payments.currency"] == ("varchar", 3, None, None, "'KGS'::character varying")
    # NOT NULL without default: the service always sets the status (§8.2).
    assert info["payments.status"] == ("varchar", 20, None, None, None)
    assert info["payments.transaction_reference"][:2] == ("varchar", 120)
    assert info["payments.is_simulated"] == ("bool", None, None, None, "false")
    assert info["deliveries.delivery_comment"][0] == "text"
    assert info["courier_assignments.assignment_type"] == ("varchar", 20, None, None, None)
    assert info["courier_assignments.status"] == (
        "varchar", 20, None, None, "'active'::character varying",
    )  # fmt: skip
    # NOT NULL without default (§9.3).
    assert info["courier_assignments.assigned_at"] == ("timestamptz", None, None, None, None)
    assert info["courier_assignments.decline_reason"][0] == "text"
    for column in (
        "payments.paid_at", "payments.refunded_at", "deliveries.delivered_at",
        "courier_assignments.accepted_at", "courier_assignments.declined_at",
        "courier_assignments.completed_at",
    ):  # fmt: skip
        assert info[column] == ("timestamptz", None, None, None, None), column
    for table in ("payments", "deliveries"):
        for column in ("created_at", "updated_at"):
            assert info[f"{table}.{column}"] == ("timestamptz", None, None, None, "now()")
    for table in TABLES:
        assert info[f"{table}.id"] == ("uuid", None, None, None, "gen_random_uuid()")


def test_constraint_names(db_session: Session) -> None:
    names = set(
        db_session.execute(
            text(
                "SELECT conname FROM pg_constraint WHERE connamespace = 'public'::regnamespace "
                "AND conrelid::regclass::text = ANY(:tables)"
            ),
            {"tables": list(TABLES)},
        ).scalars()
    )
    expected = {f"pk_{table}" for table in TABLES} | {
        "fk_payments_order_id_orders",
        "fk_payments_payment_method_id_payment_methods",
        "ck_payments_amount_non_negative",
        "ck_payments_currency_kgs",
        "ck_payments_status",
        "fk_deliveries_order_id_orders",
        "fk_deliveries_delivery_zone_id_delivery_zones",
        "uq_deliveries_order_id",
        "fk_courier_assignments_order_id_orders",
        "fk_courier_assignments_courier_id_users",
        "fk_courier_assignments_assigned_by_users",
        "ck_courier_assignments_assignment_type",
        "ck_courier_assignments_status",
        "ck_courier_assignments_declined_at_matches_status",
        "ck_courier_assignments_declined_not_accepted",
    }
    assert all(len(name) <= 63 for name in expected)
    assert names == expected


def test_foreign_keys_and_delete_rules(db_session: Session) -> None:
    rows = db_session.execute(
        text(
            "SELECT conname, confdeltype FROM pg_constraint "
            "WHERE contype = 'f' AND conrelid::regclass::text = ANY(:tables)"
        ),
        {"tables": list(TABLES)},
    ).all()
    # r = RESTRICT, n = SET NULL
    assert dict(rows) == {
        "fk_payments_order_id_orders": "r",
        "fk_payments_payment_method_id_payment_methods": "r",
        "fk_deliveries_order_id_orders": "r",
        "fk_deliveries_delivery_zone_id_delivery_zones": "n",
        "fk_courier_assignments_order_id_orders": "r",
        "fk_courier_assignments_courier_id_users": "r",
        "fk_courier_assignments_assigned_by_users": "n",
    }


def test_indexes(db_session: Session) -> None:
    indexes = dict(
        db_session.execute(
            text(
                "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' "
                "AND tablename = ANY(:tables) AND indexname NOT LIKE 'pk\\_%'"
            ),
            {"tables": list(TABLES)},
        ).all()
    )

    def ddl(name: str, table: str, rest: str, unique: bool = False) -> str:
        kind = "UNIQUE INDEX" if unique else "INDEX"
        return f"CREATE {kind} {name} ON public.{table} USING btree {rest}"

    def status_is(value: str) -> str:
        return f"(order_id) WHERE ((status)::text = '{value}'::text)"

    expected = {
        ("ix_payments_order_id_created_at", "payments", "(order_id, created_at)", False),
        ("uq_payments_order_id_succeeded", "payments", status_is("succeeded"), True),
        ("uq_payments_order_id_pending", "payments", status_is("pending"), True),
        ("ix_payments_payment_method_id", "payments", "(payment_method_id)", False),  # DEC-134
        ("uq_deliveries_order_id", "deliveries", "(order_id)", True),
        ("ix_deliveries_delivery_zone_id", "deliveries", "(delivery_zone_id)", False),  # DEC-134
        ("uq_courier_assignments_order_id_active", "courier_assignments",
         status_is("active"), True),
        ("ix_courier_assignments_courier_id_status", "courier_assignments",
         "(courier_id, status)", False),
        ("ix_courier_assignments_order_id_courier_id", "courier_assignments",
         "(order_id, courier_id)", False),
        ("ix_courier_assignments_assigned_by", "courier_assignments",
         "(assigned_by)", False),  # DEC-134
    }  # fmt: skip
    assert indexes == {
        name: ddl(name, table, rest, unique) for name, table, rest, unique in expected
    }


# --------------------------------------------------------------------------- payments


def test_payment_defaults_and_money(ctx: tuple[Session, Order, PaymentMethod, User]) -> None:
    session, order, method, _ = ctx
    payment = _payment(order, method, amount=Decimal("700.5"))
    _add(session, payment)
    session.refresh(payment)
    assert payment.currency == "KGS"
    assert payment.is_simulated is False
    assert payment.transaction_reference is None
    assert payment.paid_at is None and payment.refunded_at is None
    assert payment.created_at.tzinfo is not None
    assert isinstance(payment.amount, Decimal)
    assert str(payment.amount) == "700.50"


def test_payment_amount_overflow_is_rejected(
    ctx: tuple[Session, Order, PaymentMethod, User],
) -> None:
    session, order, method, _ = ctx
    with pytest.raises(DataError), session.begin_nested():
        session.add(_payment(order, method, amount=Decimal("10000000000.00")))
        session.flush()
    _add(session, _payment(order, method, amount=Decimal("9999999999.99")))


@pytest.mark.parametrize(
    "values",
    [
        {"status": "paid"},
        {"status": None},  # NOT NULL, no default
        {"currency": "USD"},
        {"amount": Decimal("-0.01")},
        {"amount": None},
    ],
)
def test_invalid_payment_values_are_rejected(
    ctx: tuple[Session, Order, PaymentMethod, User], values: dict
) -> None:
    session, order, method, _ = ctx
    _expect_integrity_error(session, _payment(order, method, **values))


def test_all_payment_statuses_are_accepted(
    ctx: tuple[Session, Order, PaymentMethod, User],
) -> None:
    session, order, method, _ = ctx
    statuses = ("pending", "succeeded", "failed", "refunded", "cancelled")
    _add(session, *(_payment(order, method, status=status) for status in statuses))
    assert _count(session, "payments", "order_id", order.id) == len(statuses)


def test_one_succeeded_payment_per_order(ctx: tuple[Session, Order, PaymentMethod, User]) -> None:
    session, order, method, _ = ctx
    _add(session, _payment(order, method, status="succeeded", paid_at=_now()))
    _expect_integrity_error(session, _payment(order, method, status="succeeded"))


def test_one_pending_payment_per_order_and_retry_after_failure(
    ctx: tuple[Session, Order, PaymentMethod, User],
) -> None:
    session, order, method, _ = ctx
    first = _payment(order, method, is_simulated=True)
    _add(session, first)
    _expect_integrity_error(session, _payment(order, method))

    # Failed attempt → new pending attempt (DEC-46): failed first, then insert.
    first.status = "failed"
    session.flush()
    _add(session, _payment(order, method, is_simulated=True))
    assert _count(session, "payments", "order_id", order.id) == 2


def test_terminal_payment_statuses_may_repeat(
    ctx: tuple[Session, Order, PaymentMethod, User],
) -> None:
    session, order, method, _ = ctx
    _add(
        session,
        *(_payment(order, method, status=status) for status in ("failed", "failed", "failed")),
        *(_payment(order, method, status="refunded", refunded_at=_now()) for _ in range(2)),
        *(_payment(order, method, status="cancelled") for _ in range(2)),
    )
    assert _count(session, "payments", "order_id", order.id) == 7


def test_partial_uniques_are_per_order(db_session: Session) -> None:
    customer = _user(db_session, "two")
    first, second = _order(db_session, customer), _order(db_session, customer)
    method = _method(db_session)
    _add(
        db_session,
        *(_payment(o, method, status=s) for o in (first, second) for s in ("pending", "succeeded")),
    )


def test_payment_restricts_order_and_method_deletion(
    ctx: tuple[Session, Order, PaymentMethod, User],
) -> None:
    session, order, method, _ = ctx
    _add(session, _payment(order, method))
    message = _expect_sql_error(session, "DELETE FROM orders WHERE id = :id", id=order.id)
    assert "fk_payments_order_id_orders" in message
    message = _expect_sql_error(session, "DELETE FROM payment_methods WHERE id = :id", id=method.id)
    assert "fk_payments_payment_method_id_payment_methods" in message
    assert _count(session, "orders", "id", order.id) == 1
    assert _count(session, "payment_methods", "id", method.id) == 1


def test_unused_payment_method_can_be_deleted(db_session: Session) -> None:
    method = _method(db_session)
    db_session.execute(text("DELETE FROM payment_methods WHERE id = :id"), {"id": method.id})
    assert _count(db_session, "payment_methods", "id", method.id) == 0


# --------------------------------------------------------------------------- deliveries


def test_delivery_defaults_and_one_per_order(
    ctx: tuple[Session, Order, PaymentMethod, User],
) -> None:
    session, order, _, _ = ctx
    delivery = Delivery(order_id=order.id, delivery_comment="Домофон 12")
    _add(session, delivery)
    session.refresh(delivery)
    assert delivery.delivery_zone_id is None
    assert delivery.delivered_at is None
    assert delivery.created_at.tzinfo is not None
    _expect_integrity_error(session, Delivery(order_id=order.id))


def test_delivery_requires_order(db_session: Session) -> None:
    _expect_integrity_error(db_session, Delivery(order_id=None))
    _expect_integrity_error(db_session, Delivery(order_id=uuid.uuid4()))  # FK


def test_deleting_zone_keeps_delivery(ctx: tuple[Session, Order, PaymentMethod, User]) -> None:
    session, order, _, _ = ctx
    zone = DeliveryZone(name="Зона", delivery_fee=Decimal("100.00"), is_active=False)
    _add(session, zone)
    delivery = Delivery(order_id=order.id, delivery_zone_id=zone.id)
    _add(session, delivery)

    session.execute(text("DELETE FROM delivery_zones WHERE id = :id"), {"id": zone.id})
    session.expire_all()
    assert session.get(Delivery, delivery.id).delivery_zone_id is None
    # The fee snapshot stays in the order (DEC-16).
    assert session.get(Order, order.id).delivery_fee == Decimal("100.00")


def test_delivery_restricts_order_deletion(
    ctx: tuple[Session, Order, PaymentMethod, User],
) -> None:
    session, order, _, _ = ctx
    _add(session, Delivery(order_id=order.id))
    message = _expect_sql_error(session, "DELETE FROM orders WHERE id = :id", id=order.id)
    assert "fk_deliveries_order_id_orders" in message


# --------------------------------------------------------------------------- courier assignments


def test_assignment_defaults(ctx: tuple[Session, Order, PaymentMethod, User]) -> None:
    session, order, _, courier = ctx
    assignment = _assignment(order, courier)
    _add(session, assignment)
    session.refresh(assignment)
    assert assignment.status == "active"
    assert assignment.assigned_by is None
    assert assignment.accepted_at is None and assignment.completed_at is None


@pytest.mark.parametrize(
    "values",
    [
        {"assignment_type": "auto"},
        {"assignment_type": None},
        {"status": "accepted"},
        {"assigned_at": None},  # NOT NULL, no default
        {"status": "declined"},  # declined without declined_at
        {"status": "active", "declined_at": datetime(2026, 1, 1, tzinfo=UTC)},
        {"status": "cancelled", "declined_at": datetime(2026, 1, 1, tzinfo=UTC)},
        {  # declined after acceptance
            "status": "declined",
            "declined_at": datetime(2026, 1, 1, tzinfo=UTC),
            "accepted_at": datetime(2026, 1, 1, tzinfo=UTC),
        },
    ],
)
def test_invalid_assignment_values_are_rejected(
    ctx: tuple[Session, Order, PaymentMethod, User], values: dict
) -> None:
    session, order, _, courier = ctx
    _expect_integrity_error(session, _assignment(order, courier, **values))


def test_valid_assignment_states_are_accepted(
    ctx: tuple[Session, Order, PaymentMethod, User],
) -> None:
    session, order, _, courier = ctx
    _add(
        session,
        _assignment(order, courier, assignment_type="automatic", status="declined",
                    declined_at=_now(), decline_reason="Далеко"),
        _assignment(order, courier, status="declined", declined_at=_now()),  # reason optional
        _assignment(order, courier, status="cancelled", accepted_at=_now()),
        _assignment(order, courier, status="completed", accepted_at=_now(),
                    completed_at=_now()),
        _assignment(order, courier, accepted_at=_now()),  # active and accepted
    )  # fmt: skip
    assert _count(session, "courier_assignments", "order_id", order.id) == 5


def test_one_active_assignment_per_order_and_reassignment(
    ctx: tuple[Session, Order, PaymentMethod, User],
) -> None:
    session, order, _, courier = ctx
    other = _user(session, "courier2")
    first = _assignment(order, courier)
    _add(session, first)
    _expect_integrity_error(session, _assignment(order, other))

    # Reassignment (DEC-51): current active → cancelled, then a new one.
    first.status = "cancelled"
    session.flush()
    second = _assignment(order, other)
    _add(session, second)

    # Decline (DEC-92): declined → admin assigns another courier.
    second.status = "declined"
    second.declined_at = _now()
    session.flush()
    _add(session, _assignment(order, courier))
    assert _count(session, "courier_assignments", "order_id", order.id) == 3


def test_courier_may_have_several_active_assignments(db_session: Session) -> None:
    """The per-courier limit is a service rule (max_active_orders), not a constraint."""
    customer = _user(db_session, "many")
    courier = _user(db_session, "busy")
    orders = [_order(db_session, customer) for _ in range(2)]
    _add(db_session, *(_assignment(order, courier) for order in orders))


def test_assignment_restricts_order_and_courier_deletion(
    ctx: tuple[Session, Order, PaymentMethod, User],
) -> None:
    session, order, _, courier = ctx
    _add(session, _assignment(order, courier, status="completed", completed_at=_now()))
    message = _expect_sql_error(session, "DELETE FROM orders WHERE id = :id", id=order.id)
    assert "fk_courier_assignments_order_id_orders" in message
    message = _expect_sql_error(session, "DELETE FROM users WHERE id = :id", id=courier.id)
    assert "fk_courier_assignments_courier_id_users" in message
    assert _count(session, "users", "id", courier.id) == 1


def test_deleting_assigner_sets_assigned_by_null(
    ctx: tuple[Session, Order, PaymentMethod, User],
) -> None:
    session, order, _, courier = ctx
    admin = _user(session, "admin")
    assignment = _assignment(order, courier, assigned_by=admin.id)
    _add(session, assignment)

    session.execute(text("DELETE FROM users WHERE id = :id"), {"id": admin.id})
    session.expire_all()
    kept = session.get(CourierAssignment, assignment.id)
    assert kept is not None
    assert kept.assigned_by is None
    assert kept.courier_id == courier.id


def test_orm_delete_of_order_with_children_is_rejected(
    ctx: tuple[Session, Order, PaymentMethod, User],
) -> None:
    """passive_deletes='all': the ORM leaves children alone and RESTRICT rejects."""
    session, order, method, courier = ctx
    _add(session, _payment(order, method), Delivery(order_id=order.id), _assignment(order, courier))
    session.expunge_all()
    loaded = session.get(Order, order.id)
    with pytest.raises(IntegrityError), session.begin_nested():
        session.delete(loaded)
        session.flush()


# --------------------------------------------------------------------------- relationships


def test_relationships_require_explicit_loading(
    ctx: tuple[Session, Order, PaymentMethod, User],
) -> None:
    session, order, method, courier = ctx
    admin = _user(session, "assigner")
    zone = DeliveryZone(name="Зона", delivery_fee=Decimal("100.00"), is_active=False)
    _add(session, zone)
    payment = _payment(order, method, status="failed")
    delivery = Delivery(order_id=order.id, delivery_zone_id=zone.id)
    assignment = _assignment(order, courier, assigned_by=admin.id)
    _add(session, payment, _payment(order, method), delivery, assignment)
    session.expunge_all()

    lazy_order = session.get(Order, order.id)
    for attribute in ("payments", "delivery", "courier_assignments"):
        with pytest.raises(InvalidRequestError, match="lazy='raise'"):
            getattr(lazy_order, attribute)
    checks = (
        (Payment, payment.id, ("order", "payment_method")),
        (Delivery, delivery.id, ("order", "zone")),
        (CourierAssignment, assignment.id, ("order", "courier", "assigner")),
    )
    for model, pk, attributes in checks:
        instance = session.get(model, pk)
        for attribute in attributes:
            with pytest.raises(InvalidRequestError, match="lazy='raise'"):
                getattr(instance, attribute)
    session.expunge_all()

    loaded = session.scalars(
        select(Order)
        .where(Order.id == order.id)
        .options(
            selectinload(Order.payments).joinedload(Payment.payment_method),
            joinedload(Order.delivery).joinedload(Delivery.zone),
            selectinload(Order.courier_assignments).options(
                joinedload(CourierAssignment.courier), joinedload(CourierAssignment.assigner)
            ),
        )
    ).one()
    assert sorted(p.status for p in loaded.payments) == ["failed", "pending"]
    assert {p.payment_method.code for p in loaded.payments} == {method.code}
    assert loaded.delivery is not None
    assert loaded.delivery.zone is not None and loaded.delivery.zone.name == "Зона"
    [active] = loaded.courier_assignments
    assert active.courier.email == "courier@example.kg"
    assert active.assigner is not None and active.assigner.email == "assigner@example.kg"


def test_order_without_delivery_loads_none(db_session: Session) -> None:
    customer = _user(db_session, "pickup")
    order = _order(
        db_session, customer, delivery_type="pickup", subtotal=Decimal("500.00"),
        delivery_fee=Decimal("0"), total_amount=Decimal("500.00"), delivery_address_text=None,
        delivery_latitude=None, delivery_longitude=None,
    )  # fmt: skip
    db_session.expunge_all()
    loaded = db_session.scalars(
        select(Order)
        .where(Order.id == order.id)
        .options(
            joinedload(Order.delivery),
            selectinload(Order.payments),
            selectinload(Order.courier_assignments),
        )
    ).one()
    assert loaded.delivery is None
    assert loaded.payments == []
    assert loaded.courier_assignments == []
