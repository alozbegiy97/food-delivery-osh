"""Orders schema on the isolated test database.

DATABASE_SCHEMA.md §7, §14.2; DEC-14/123, DEC-62, DEC-131…DEC-133.
Each test runs inside a rolled-back transaction (`db_session`). Note: the
order-number sequence is not transactional, so `setval` in these tests
moves `order_number_seq` of db-test only.
"""

import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import DataError, IntegrityError, InvalidRequestError
from sqlalchemy.orm import Session, selectinload

from app.modules.catalog.enums import SelectionType
from app.modules.catalog.models import Category, Modifier, ModifierGroup, Product, ProductVariant
from app.modules.orders.models import (
    CancellationRequest,
    IdempotencyKey,
    Order,
    OrderItem,
    OrderItemModifier,
    OrderStatusHistory,
)
from app.modules.users.models import User

pytestmark = pytest.mark.db

TABLES = (
    "orders",
    "order_items",
    "order_item_modifiers",
    "order_status_history",
    "cancellation_requests",
    "idempotency_keys",
)


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


def _delete_user(session: Session, user: User) -> None:
    session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user.id})


def _count(session: Session, table: str, column: str, value: object) -> int:
    return session.execute(
        text(f"SELECT count(*) FROM {table} WHERE {column} = :v"),  # noqa: S608 - test literals
        {"v": value},
    ).scalar_one()


def _user(session: Session, name: str) -> User:
    user = User(email=f"{name}@example.kg", password_hash="h", full_name=name.title())
    _add(session, user)
    return user


def _pickup_order(user: User, **values: object) -> Order:
    defaults: dict[str, object] = {
        "user_id": user.id,
        "language_code": "ru",
        "delivery_type": "pickup",
        "payment_method_code": "cash",
        "subtotal": Decimal("500.00"),
        "total_amount": Decimal("500.00"),
        "customer_name": "Айбек",
        "customer_phone": "+996700123456",
    }
    return Order(**(defaults | values))


def _delivery_order(user: User, **values: object) -> Order:
    defaults: dict[str, object] = {
        "delivery_type": "delivery",
        "subtotal": Decimal("600.00"),
        "delivery_fee": Decimal("100.00"),
        "total_amount": Decimal("700.00"),
        "delivery_address_text": "ул. Ленина, 1",
        "delivery_latitude": Decimal("40.5283000"),
        "delivery_longitude": Decimal("72.7985000"),
    }
    return _pickup_order(user, **(defaults | values))


def _order(session: Session, user: User, **values: object) -> Order:
    order = _pickup_order(user, **values)
    _add(session, order)
    return order


def _history(order: Order, **values: object) -> OrderStatusHistory:
    defaults: dict[str, object] = {"order_id": order.id, "new_status": "pending"}
    return OrderStatusHistory(**(defaults | values))


def _set_sequence(session: Session, last_value: int) -> None:
    session.execute(text("SELECT setval('order_number_seq', :v)"), {"v": last_value})


# --------------------------------------------------------------------------- structure

EXPECTED_COLUMNS = {
    "orders": {
        "id": False, "order_number": False, "user_id": False, "language_code": False,
        "delivery_type": False, "status": False, "payment_method_code": False,
        "subtotal": False, "delivery_fee": False, "total_amount": False, "currency": False,
        "customer_name": False, "customer_phone": False, "delivery_address_text": True,
        "delivery_latitude": True, "delivery_longitude": True, "delivery_entrance": True,
        "delivery_floor": True, "delivery_apartment": True, "customer_comment": True,
        "payment_due_at": True, "cancellation_reason_code": True, "cancelled_at": True,
        "created_at": False, "updated_at": False, "completed_at": True,
    },
    "order_items": {
        "id": False, "order_id": False, "product_id": True, "variant_id": True,
        "product_name": False, "variant_name": False, "sku": False, "unit_price": False,
        "quantity": False, "total_price": False, "special_instructions": True,
    },
    "order_item_modifiers": {
        "id": False, "order_item_id": False, "modifier_id": True, "group_name": False,
        "modifier_name": False, "quantity": False, "unit_price": False, "total_price": False,
    },
    "order_status_history": {
        "id": False, "order_id": False, "old_status": True, "new_status": False,
        "changed_by": True, "comment": True, "is_admin_override": False, "created_at": False,
    },
    "cancellation_requests": {
        "id": False, "order_id": False, "user_id": False, "reason": False, "status": False,
        "reviewed_by": True, "admin_comment": True, "created_at": False, "reviewed_at": True,
    },
    "idempotency_keys": {
        "id": False, "user_id": False, "scope": False, "key": False, "request_hash": False,
        "response_status": True, "response_body": True, "created_at": False,
        "expires_at": False,
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
    money = ("numeric", None, 12, 2)
    money_columns = (
        "orders.subtotal",
        "orders.delivery_fee",
        "orders.total_amount",
        "order_items.unit_price",
        "order_items.total_price",
        "order_item_modifiers.unit_price",
        "order_item_modifiers.total_price",
    )
    for column in money_columns:
        assert info[column][:4] == money, column
    assert info["orders.delivery_latitude"][:4] == ("numeric", None, 10, 7)
    assert info["orders.order_number"][:2] == ("varchar", 40)
    assert info["orders.order_number"][4] == "next_order_number()"
    assert info["orders.status"][4] == "'pending'::character varying"
    assert info["orders.currency"][4] == "'KGS'::character varying"
    assert info["orders.delivery_fee"][4] == "0"
    assert info["order_status_history.is_admin_override"][4] == "false"
    assert info["cancellation_requests.status"][4] == "'pending'::character varying"
    assert info["order_item_modifiers.quantity"][0] == "int2"
    assert info["order_item_modifiers.quantity"][4] is None  # NOT NULL without default
    assert info["order_items.quantity"][0] == "int4"
    assert info["idempotency_keys.response_body"][0] == "jsonb"
    assert info["idempotency_keys.response_status"][0] == "int2"
    assert info["idempotency_keys.key"][:2] == ("varchar", 128)
    assert info["idempotency_keys.request_hash"][:2] == ("varchar", 64)
    assert info["idempotency_keys.expires_at"][4] is None
    assert info["orders.payment_due_at"][0] == "timestamptz"


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
        "uq_orders_order_number",
        "fk_orders_user_id_users",
        *(f"ck_orders_{name}" for name in (
            "language_code", "delivery_type", "status", "currency_kgs", "customer_phone_format",
            "subtotal_non_negative", "delivery_fee_non_negative", "total_amount_non_negative",
            "total_is_sum", "cancellation_reason_code", "pickup_without_delivery_fields",
            "delivery_requires_address", "cancelled_has_reason", "cancelled_has_timestamp",
        )),
        "fk_order_items_order_id_orders",
        "fk_order_items_product_id_products",
        "fk_order_items_variant_id_product_variants",
        "ck_order_items_unit_price_non_negative",
        "ck_order_items_quantity_positive",
        "ck_order_items_total_price_non_negative",
        "fk_order_item_modifiers_order_item_id_order_items",
        "fk_order_item_modifiers_modifier_id_modifiers",
        "ck_order_item_modifiers_quantity_positive",
        "ck_order_item_modifiers_unit_price_non_negative",
        "ck_order_item_modifiers_total_price_non_negative",
        "fk_order_status_history_order_id_orders",
        "fk_order_status_history_changed_by_users",
        "ck_order_status_history_old_status",
        "ck_order_status_history_new_status",
        "ck_order_status_history_admin_override_author_comment",
        "ck_order_status_history_rejected_cancelled_require_comment",
        "fk_cancellation_requests_order_id_orders",
        "fk_cancellation_requests_user_id_users",
        "fk_cancellation_requests_reviewed_by_users",
        "ck_cancellation_requests_status",
        "fk_idempotency_keys_user_id_users",
        "uq_idempotency_keys_user_id_scope_key",
    }  # fmt: skip
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
    # c = CASCADE, r = RESTRICT, n = SET NULL
    assert dict(rows) == {
        "fk_orders_user_id_users": "r",
        "fk_order_items_order_id_orders": "c",
        "fk_order_items_product_id_products": "n",
        "fk_order_items_variant_id_product_variants": "n",
        "fk_order_item_modifiers_order_item_id_order_items": "c",
        "fk_order_item_modifiers_modifier_id_modifiers": "n",
        "fk_order_status_history_order_id_orders": "c",
        "fk_order_status_history_changed_by_users": "n",
        "fk_cancellation_requests_order_id_orders": "c",
        "fk_cancellation_requests_user_id_users": "r",
        "fk_cancellation_requests_reviewed_by_users": "n",
        "fk_idempotency_keys_user_id_users": "c",
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

    assert indexes == {
        "uq_orders_order_number": ddl("uq_orders_order_number", "orders", "(order_number)", True),
        "ix_orders_user_id_created_at": ddl(
            "ix_orders_user_id_created_at", "orders", "(user_id, created_at DESC)"
        ),
        "ix_orders_status_created_at": ddl(
            "ix_orders_status_created_at", "orders", "(status, created_at)"
        ),
        "ix_orders_payment_due_at_pending": ddl(
            "ix_orders_payment_due_at_pending",
            "orders",
            "(payment_due_at) WHERE (((status)::text = 'pending'::text) "
            "AND (payment_due_at IS NOT NULL))",
        ),
        "ix_order_items_order_id": ddl("ix_order_items_order_id", "order_items", "(order_id)"),
        "ix_order_items_product_id": ddl(
            "ix_order_items_product_id", "order_items", "(product_id)"
        ),
        "ix_order_items_variant_id": ddl(
            "ix_order_items_variant_id", "order_items", "(variant_id)"
        ),
        "ix_order_item_modifiers_order_item_id": ddl(
            "ix_order_item_modifiers_order_item_id", "order_item_modifiers", "(order_item_id)"
        ),
        "ix_order_item_modifiers_modifier_id": ddl(
            "ix_order_item_modifiers_modifier_id", "order_item_modifiers", "(modifier_id)"
        ),
        "ix_order_status_history_order_id_created_at": ddl(
            "ix_order_status_history_order_id_created_at",
            "order_status_history",
            "(order_id, created_at)",
        ),
        "ix_order_status_history_changed_by": ddl(
            "ix_order_status_history_changed_by", "order_status_history", "(changed_by)"
        ),
        "uq_cancellation_requests_order_id_pending": ddl(
            "uq_cancellation_requests_order_id_pending",
            "cancellation_requests",
            "(order_id) WHERE ((status)::text = 'pending'::text)",
            True,
        ),
        "ix_cancellation_requests_order_id": ddl(
            "ix_cancellation_requests_order_id", "cancellation_requests", "(order_id)"
        ),
        "ix_cancellation_requests_user_id": ddl(
            "ix_cancellation_requests_user_id", "cancellation_requests", "(user_id)"
        ),
        "ix_cancellation_requests_reviewed_by": ddl(
            "ix_cancellation_requests_reviewed_by", "cancellation_requests", "(reviewed_by)"
        ),
        "uq_idempotency_keys_user_id_scope_key": ddl(
            "uq_idempotency_keys_user_id_scope_key",
            "idempotency_keys",
            "(user_id, scope, key)",
            True,
        ),
        "ix_idempotency_keys_expires_at": ddl(
            "ix_idempotency_keys_expires_at", "idempotency_keys", "(expires_at)"
        ),
    }


# --------------------------------------------------------------------------- order number


def test_order_number_is_zero_padded_to_six_digits(db_session: Session) -> None:
    user = _user(db_session, "numbers")
    _set_sequence(db_session, 122)
    order = _order(db_session, user)
    db_session.refresh(order)
    assert order.order_number == "OSH-000123"
    assert re.fullmatch(r"OSH-\d{6,}", order.order_number)


def test_order_number_is_not_truncated_after_999999(db_session: Session) -> None:
    """DEC-123: 999999 -> 1000000 keeps all digits (lpad(n, 6) would cut it)."""
    user = _user(db_session, "rollover")
    _set_sequence(db_session, 999998)
    first = _order(db_session, user)
    second = _order(db_session, user)
    db_session.refresh(first)
    db_session.refresh(second)
    assert first.order_number == "OSH-999999"
    assert second.order_number == "OSH-1000000"
    assert db_session.execute(text("SELECT next_order_number()")).scalar_one() == "OSH-1000001"


def test_order_number_is_unique(db_session: Session) -> None:
    user = _user(db_session, "dup")
    order = _order(db_session, user)
    db_session.refresh(order)
    _expect_integrity_error(db_session, _pickup_order(user, order_number=order.order_number))


# ------------------------------------------------------------------ orders: defaults & money


def test_order_defaults(db_session: Session) -> None:
    order = _order(db_session, _user(db_session, "defaults"))
    db_session.refresh(order)
    assert isinstance(order.id, uuid.UUID)
    assert order.status == "pending"
    assert order.currency == "KGS"
    assert order.delivery_fee == Decimal("0.00")
    assert order.payment_due_at is None
    assert order.created_at.tzinfo is not None
    assert order.updated_at.tzinfo is not None


def test_money_is_decimal_with_two_places(db_session: Session) -> None:
    user = _user(db_session, "money")
    order = _delivery_order(
        user,
        subtotal=Decimal("1234.5"),
        delivery_fee=Decimal("100.25"),
        total_amount=Decimal("1334.75"),
    )
    _add(db_session, order)
    db_session.expire(order)
    assert (order.subtotal, order.delivery_fee, order.total_amount) == (
        Decimal("1234.50"),
        Decimal("100.25"),
        Decimal("1334.75"),
    )
    assert all(isinstance(v, Decimal) for v in (order.subtotal, order.total_amount))
    assert order.subtotal.as_tuple().exponent == -2

    with pytest.raises(DataError), db_session.begin_nested():
        db_session.add(
            _pickup_order(
                user, subtotal=Decimal("10000000000.00"), total_amount=Decimal("10000000000.00")
            )
        )
        db_session.flush()


# --------------------------------------------------------------------------- orders: CHECKs


def test_valid_delivery_and_pickup_orders(db_session: Session) -> None:
    user = _user(db_session, "valid")
    _add(
        db_session,
        _pickup_order(user),
        _delivery_order(user, delivery_entrance="2", delivery_floor="3", delivery_apartment="12"),
        _pickup_order(user, payment_method_code="mock_card",
                      payment_due_at=datetime.now(UTC) + timedelta(minutes=30)),
    )  # fmt: skip


@pytest.mark.parametrize(
    "values",
    [
        {"delivery_address_text": "ул. Ленина"},
        {"delivery_latitude": Decimal("40.5")},
        {"delivery_entrance": "1"},
        {"delivery_floor": "2"},
        {"delivery_apartment": "3"},
        {"delivery_fee": Decimal("100.00"), "total_amount": Decimal("600.00")},
    ],
)
def test_pickup_must_not_have_delivery_fields(db_session: Session, values: dict) -> None:
    user = _user(db_session, "pickup")
    _expect_integrity_error(db_session, _pickup_order(user, **values))


@pytest.mark.parametrize(
    "missing", ["delivery_address_text", "delivery_latitude", "delivery_longitude"]
)
def test_delivery_requires_address_and_coordinates(db_session: Session, missing: str) -> None:
    user = _user(db_session, "delivery")
    _expect_integrity_error(db_session, _delivery_order(user, **{missing: None}))


def test_total_must_equal_subtotal_plus_fee(db_session: Session) -> None:
    user = _user(db_session, "total")
    _expect_integrity_error(db_session, _delivery_order(user, total_amount=Decimal("699.99")))
    _expect_integrity_error(db_session, _pickup_order(user, total_amount=Decimal("500.01")))


@pytest.mark.parametrize(
    "values",
    [
        {"subtotal": Decimal("-1.00"), "total_amount": Decimal("-1.00")},
        {"currency": "USD"},
        {"customer_phone": "0700123456"},
        {"customer_phone": "+99670012345"},
        {"language_code": "en"},
        {"status": "shipped"},
        {"delivery_type": "courier"},
        {"customer_name": None},
        {"payment_method_code": None},
    ],
)
def test_invalid_order_values_are_rejected(db_session: Session, values: dict) -> None:
    user = _user(db_session, "invalid")
    _expect_integrity_error(db_session, _pickup_order(user, **values))


def test_negative_delivery_fee_is_rejected(db_session: Session) -> None:
    user = _user(db_session, "fee")
    _expect_integrity_error(
        db_session,
        _delivery_order(user, delivery_fee=Decimal("-1.00"), total_amount=Decimal("599.00")),
    )


def test_cancellation_fields_follow_status(db_session: Session) -> None:
    user = _user(db_session, "cancel")
    now = datetime.now(UTC)
    _add(
        db_session,
        _pickup_order(user, status="cancelled", cancellation_reason_code="payment_timeout",
                      cancelled_at=now),
    )  # fmt: skip
    invalid = [
        {"status": "cancelled", "cancelled_at": now},  # no reason
        {"status": "cancelled", "cancellation_reason_code": "admin_decision"},  # no timestamp
        {"status": "pending", "cancellation_reason_code": "admin_decision"},  # reason w/o cancel
        {"status": "completed", "cancelled_at": now},  # timestamp w/o cancel
        {"status": "cancelled", "cancellation_reason_code": "other", "cancelled_at": now},
    ]
    for values in invalid:
        _expect_integrity_error(db_session, _pickup_order(user, **values))


# --------------------------------------------------------------------------- user deletion


def test_user_with_orders_cannot_be_deleted(db_session: Session) -> None:
    """5.1 — orders.user_id ON DELETE RESTRICT (DEC-62)."""
    customer = _user(db_session, "customer")
    order = _order(db_session, customer)
    _expect_sql_error(db_session, "DELETE FROM users WHERE id = :id", id=customer.id)
    assert _count(db_session, "orders", "id", order.id) == 1


def test_user_with_cancellation_request_cannot_be_deleted(db_session: Session) -> None:
    """5.2 — cancellation_requests.user_id ON DELETE RESTRICT."""
    customer = _user(db_session, "owner")
    requester = _user(db_session, "requester")  # has no orders
    order = _order(db_session, customer)
    _add(db_session, CancellationRequest(order_id=order.id, user_id=requester.id, reason="Долго"))
    _expect_sql_error(db_session, "DELETE FROM users WHERE id = :id", id=requester.id)
    assert _count(db_session, "users", "id", requester.id) == 1


def test_deleting_user_cascades_idempotency_keys(db_session: Session) -> None:
    """5.3 — idempotency_keys.user_id ON DELETE CASCADE."""
    user = _user(db_session, "idem")
    _add(
        db_session,
        IdempotencyKey(user_id=user.id, scope="create_order", key="k1", request_hash="a" * 64,
                       expires_at=datetime.now(UTC) + timedelta(hours=24)),
    )  # fmt: skip
    _delete_user(db_session, user)
    assert _count(db_session, "idempotency_keys", "user_id", user.id) == 0


def test_deleting_staff_sets_changed_by_null(db_session: Session) -> None:
    """5.4 — changed_by ON DELETE SET NULL for regular (non-override) records."""
    customer = _user(db_session, "client")
    cook = _user(db_session, "cook")  # no orders
    order = _order(db_session, customer)
    record = _history(order, old_status="confirmed", new_status="preparing", changed_by=cook.id)
    _add(db_session, record)

    _delete_user(db_session, cook)

    db_session.refresh(record)
    assert record.changed_by is None
    assert record.new_status == "preparing"


def test_deleting_reviewer_sets_reviewed_by_null(db_session: Session) -> None:
    """5.5 — cancellation_requests.reviewed_by ON DELETE SET NULL."""
    customer = _user(db_session, "asker")
    admin = _user(db_session, "reviewer")  # no orders
    order = _order(db_session, customer)
    request = CancellationRequest(
        order_id=order.id,
        user_id=customer.id,
        reason="Передумал",
        status="approved",
        reviewed_by=admin.id,
        reviewed_at=datetime.now(UTC),
    )
    _add(db_session, request)

    _delete_user(db_session, admin)

    db_session.refresh(request)
    assert request.reviewed_by is None
    assert request.status == "approved"


def test_deleting_admin_with_override_record_is_blocked(db_session: Session) -> None:
    """5.6 — DEC-131: SET NULL would violate the override CHECK, so the delete fails."""
    customer = _user(db_session, "buyer")
    admin = _user(db_session, "override-admin")  # no orders
    order = _order(db_session, customer)
    record = _history(
        order,
        old_status="ready_for_pickup",
        new_status="out_for_delivery",
        changed_by=admin.id,
        is_admin_override=True,
        comment="Курьер недоступен, передано вручную",
    )
    _add(db_session, record)

    message = _expect_sql_error(db_session, "DELETE FROM users WHERE id = :id", id=admin.id)

    assert "ck_order_status_history_admin_override_author_comment" in message
    db_session.refresh(record)
    assert record.changed_by == admin.id
    assert _count(db_session, "users", "id", admin.id) == 1


# ------------------------------------------------------------------ order & catalog deletion


def _catalog(session: Session) -> tuple[Product, ProductVariant, Modifier]:
    category = Category(slug="order-cat")
    group = ModifierGroup(selection_type=SelectionType.MULTIPLE)
    _add(session, category, group)
    product = Product(category_id=category.id, slug="order-product")
    _add(session, product)
    variant = ProductVariant(product_id=product.id, sku="ORD-SKU", price=Decimal("450.00"))
    modifier = Modifier(group_id=group.id, price_delta=Decimal("50.00"))
    _add(session, variant, modifier)
    return product, variant, modifier


def _line(session: Session, order: Order, product: Product, variant: ProductVariant,
          modifier: Modifier) -> tuple[OrderItem, OrderItemModifier]:  # fmt: skip
    item = OrderItem(
        order_id=order.id, product_id=product.id, variant_id=variant.id,
        product_name="Маргарита", variant_name="30 см", sku="ORD-SKU",
        unit_price=Decimal("450.00"), quantity=2, total_price=Decimal("1000.00"),
    )  # fmt: skip
    _add(session, item)
    mod = OrderItemModifier(
        order_item_id=item.id, modifier_id=modifier.id, group_name="Добавки",
        modifier_name="Сыр", quantity=1, unit_price=Decimal("50.00"),
        total_price=Decimal("50.00"),
    )  # fmt: skip
    _add(session, mod)
    return item, mod


def test_deleting_order_cascades_to_children(db_session: Session) -> None:
    user = _user(db_session, "cascade")
    order = _order(db_session, user)
    item, mod = _line(db_session, order, *_catalog(db_session))
    _add(
        db_session,
        _history(order),
        CancellationRequest(order_id=order.id, user_id=user.id, reason="Ошибся"),
    )
    db_session.execute(text("DELETE FROM orders WHERE id = :id"), {"id": order.id})
    assert _count(db_session, "order_items", "order_id", order.id) == 0
    assert _count(db_session, "order_item_modifiers", "id", mod.id) == 0
    assert _count(db_session, "order_status_history", "order_id", order.id) == 0
    assert _count(db_session, "cancellation_requests", "order_id", order.id) == 0


def test_catalog_deletion_keeps_order_snapshots(db_session: Session) -> None:
    order = _order(db_session, _user(db_session, "snapshot"))
    product, variant, modifier = _catalog(db_session)
    item, mod = _line(db_session, order, product, variant, modifier)

    db_session.execute(text("DELETE FROM modifiers WHERE id = :id"), {"id": modifier.id})
    db_session.execute(text("DELETE FROM products WHERE id = :id"), {"id": product.id})

    db_session.refresh(item)
    db_session.refresh(mod)
    assert (item.product_id, item.variant_id, mod.modifier_id) == (None, None, None)
    assert (item.product_name, item.variant_name, item.sku) == ("Маргарита", "30 см", "ORD-SKU")
    assert (item.unit_price, item.total_price) == (Decimal("450.00"), Decimal("1000.00"))
    assert (mod.group_name, mod.modifier_name, mod.unit_price) == (
        "Добавки",
        "Сыр",
        Decimal("50.00"),
    )


@pytest.mark.parametrize(
    "values",
    [
        {"quantity": 0},
        {"unit_price": Decimal("-1.00")},
        {"total_price": Decimal("-0.01")},
        {"product_name": None},
        {"sku": None},
    ],
)
def test_invalid_order_items_are_rejected(db_session: Session, values: dict) -> None:
    order = _order(db_session, _user(db_session, "items"))
    defaults: dict[str, object] = {
        "order_id": order.id, "product_name": "P", "variant_name": "V", "sku": "S",
        "unit_price": Decimal("1.00"), "quantity": 1, "total_price": Decimal("1.00"),
    }  # fmt: skip
    _expect_integrity_error(db_session, OrderItem(**(defaults | values)))


@pytest.mark.parametrize(
    "values",
    [
        {"quantity": 0},
        {"quantity": None},
        {"unit_price": Decimal("-1.00")},
        {"total_price": Decimal("-1.00")},
        {"group_name": None},
        {"modifier_name": None},
    ],
)
def test_invalid_order_item_modifiers_are_rejected(db_session: Session, values: dict) -> None:
    order = _order(db_session, _user(db_session, "mods"))
    item = OrderItem(
        order_id=order.id, product_name="P", variant_name="V", sku="S",
        unit_price=Decimal("1.00"), quantity=1, total_price=Decimal("1.00"),
    )  # fmt: skip
    _add(db_session, item)
    defaults: dict[str, object] = {
        "order_item_id": item.id, "group_name": "G", "modifier_name": "M", "quantity": 1,
        "unit_price": Decimal("1.00"), "total_price": Decimal("1.00"),
    }  # fmt: skip
    _expect_integrity_error(db_session, OrderItemModifier(**(defaults | values)))


# --------------------------------------------------------------------------- status history


def test_history_defaults_and_status_checks(db_session: Session) -> None:
    order = _order(db_session, _user(db_session, "hist"))
    first = _history(order)  # first record: old_status NULL, no comment needed
    _add(db_session, first)
    db_session.refresh(first)
    assert first.old_status is None
    assert first.is_admin_override is False
    assert first.created_at.tzinfo is not None

    _add(db_session, _history(order, old_status="pending", new_status="confirmed"))
    _expect_integrity_error(db_session, _history(order, new_status="shipped"))
    _expect_integrity_error(db_session, _history(order, old_status="draft"))


@pytest.mark.parametrize("comment", [None, "", "   "])
def test_admin_override_requires_author_and_comment(
    db_session: Session, comment: str | None
) -> None:
    """DEC-131: is_admin_override requires changed_by and a non-empty comment."""
    order = _order(db_session, _user(db_session, "ovr-customer"))
    admin = _user(db_session, "ovr-admin")
    override = {"old_status": "out_for_delivery", "new_status": "completed",
                "is_admin_override": True}  # fmt: skip
    _expect_integrity_error(
        db_session, _history(order, changed_by=admin.id, comment=comment, **override)
    )
    _expect_integrity_error(db_session, _history(order, comment="Вручную", **override))
    _add(db_session, _history(order, changed_by=admin.id, comment="Вручную", **override))


@pytest.mark.parametrize("status", ["rejected", "cancelled"])
@pytest.mark.parametrize("comment", [None, "", "   "])
def test_rejected_and_cancelled_require_comment(
    db_session: Session, status: str, comment: str | None
) -> None:
    """DEC-132: NULL, empty and spaces-only comments are rejected."""
    order = _order(db_session, _user(db_session, f"{status}-c"))
    _expect_integrity_error(
        db_session, _history(order, old_status="pending", new_status=status, comment=comment)
    )
    _add(db_session, _history(order, old_status="pending", new_status=status, comment="Причина"))


def test_other_statuses_do_not_require_comment(db_session: Session) -> None:
    order = _order(db_session, _user(db_session, "nocomment"))
    _add(
        db_session,
        *(_history(order, new_status=status) for status in
          ("pending", "confirmed", "preparing", "ready_for_pickup", "out_for_delivery",
           "completed")),
    )  # fmt: skip


# --------------------------------------------------------------------------- cancellation requests


def test_cancellation_request_defaults_and_status_check(db_session: Session) -> None:
    user = _user(db_session, "req")
    order = _order(db_session, user)
    request = CancellationRequest(order_id=order.id, user_id=user.id, reason="Долго")
    _add(db_session, request)
    db_session.refresh(request)
    assert request.status == "pending"
    assert request.reviewed_by is None
    _expect_integrity_error(
        db_session,
        CancellationRequest(order_id=order.id, user_id=user.id, reason="x", status="maybe"),
    )
    _expect_integrity_error(
        db_session, CancellationRequest(order_id=order.id, user_id=user.id, reason=None)
    )


def test_one_pending_request_per_order_and_retry_after_rejection(db_session: Session) -> None:
    user = _user(db_session, "retry")
    order = _order(db_session, user)
    first = CancellationRequest(order_id=order.id, user_id=user.id, reason="Первый")
    _add(db_session, first)
    _expect_integrity_error(
        db_session, CancellationRequest(order_id=order.id, user_id=user.id, reason="Второй")
    )
    # After rejection a new pending request is allowed (DEC-42).
    first.status = "rejected"
    db_session.flush()
    _add(db_session, CancellationRequest(order_id=order.id, user_id=user.id, reason="Снова"))
    assert _count(db_session, "cancellation_requests", "order_id", order.id) == 2


# --------------------------------------------------------------------------- idempotency keys


def test_idempotency_key_uniqueness_and_jsonb(db_session: Session) -> None:
    user = _user(db_session, "idem-a")
    other = _user(db_session, "idem-b")
    expires = datetime.now(UTC) + timedelta(hours=24)

    def key(owner: User, scope: str = "create_order", value: str = "abc") -> IdempotencyKey:
        return IdempotencyKey(user_id=owner.id, scope=scope, key=value,
                              request_hash="f" * 64, expires_at=expires)  # fmt: skip

    in_progress = key(user)
    _add(db_session, in_progress)
    db_session.refresh(in_progress)
    assert in_progress.response_status is None  # request still in progress
    assert in_progress.response_body is None

    _expect_integrity_error(db_session, key(user))
    _add(db_session, key(other), key(user, scope="other_scope"), key(user, value="def"))

    in_progress.response_status = 201
    in_progress.response_body = {"id": "x", "total_amount": "700.00", "items": [1, 2]}
    db_session.flush()
    db_session.expire(in_progress)
    assert in_progress.response_body == {"id": "x", "total_amount": "700.00", "items": [1, 2]}

    _expect_integrity_error(
        db_session,
        IdempotencyKey(user_id=user.id, scope="create_order", key="noexp", request_hash="0"),
    )


def test_idempotency_response_body_none_is_sql_null(db_session: Session) -> None:
    """Explicit Python None is stored as SQL NULL, not JSON 'null' (none_as_null=True)."""
    user = _user(db_session, "idem-null")

    def stored(key_id: uuid.UUID) -> tuple[bool, str | None]:
        return db_session.execute(
            text(
                "SELECT response_body IS NULL, jsonb_typeof(response_body) "
                "FROM idempotency_keys WHERE id = :id"
            ),
            {"id": key_id},
        ).one()

    explicit = IdempotencyKey(user_id=user.id, scope="create_order", key="none",
                              request_hash="e" * 64, response_body=None,
                              expires_at=datetime.now(UTC) + timedelta(hours=24))  # fmt: skip
    _add(db_session, explicit)
    assert stored(explicit.id) == (True, None)

    explicit.response_body = {"id": "x"}
    db_session.flush()
    assert stored(explicit.id) == (False, "object")

    explicit.response_body = None  # update back to None → SQL NULL as well
    db_session.flush()
    assert stored(explicit.id) == (True, None)


# --------------------------------------------------------------------------- relationships


def test_relationships_require_explicit_loading(db_session: Session) -> None:
    user = _user(db_session, "rel")
    order = _order(db_session, user)
    _line(db_session, order, *_catalog(db_session))
    _add(
        db_session,
        _history(order),
        CancellationRequest(order_id=order.id, user_id=user.id, reason="Тест"),
    )
    db_session.expunge_all()

    lazy = db_session.get(Order, order.id)
    assert lazy is not None
    for attribute in ("user", "items", "status_history", "cancellation_requests"):
        with pytest.raises(InvalidRequestError, match="lazy='raise'"):
            getattr(lazy, attribute)
    db_session.expunge_all()

    loaded = db_session.scalars(
        select(Order)
        .where(Order.id == order.id)
        .options(
            selectinload(Order.user),
            selectinload(Order.items).selectinload(OrderItem.modifiers),
            selectinload(Order.status_history),
            selectinload(Order.cancellation_requests),
        )
    ).one()
    assert loaded.user.email == "rel@example.kg"
    assert [i.product_name for i in loaded.items] == ["Маргарита"]
    assert [m.modifier_name for m in loaded.items[0].modifiers] == ["Сыр"]
    assert [h.new_status for h in loaded.status_history] == ["pending"]
    assert [r.reason for r in loaded.cancellation_requests] == ["Тест"]
