"""Notifications and Telegram schema on the isolated test database.

DATABASE_SCHEMA.md §11; DEC-116, DEC-121, DEC-126, DEC-135.
Each test runs inside a rolled-back transaction (`db_session`). Only what
the database enforces is tested; payload shape, token lifecycle, outbox
retries and linking rules are service/worker rules.
"""

import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError, InvalidRequestError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.modules.notifications.enums import NotificationType, TelegramOutboxStatus
from app.modules.notifications.models import (
    Notification,
    TelegramLink,
    TelegramLinkToken,
    TelegramOutbox,
)
from app.modules.orders.models import Order
from app.modules.users.models import User

pytestmark = pytest.mark.db

TABLES = ("notifications", "telegram_links", "telegram_link_tokens", "telegram_outbox")
TYPES = [member.value for member in NotificationType]


# --------------------------------------------------------------------------- helpers


def _add(session: Session, *objects: object) -> None:
    session.add_all(objects)
    session.flush()


def _expect_integrity_error(session: Session, *objects: object) -> None:
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add_all(objects)
        session.flush()


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


def _order(session: Session, user: User) -> Order:
    order = Order(
        user_id=user.id,
        language_code="ru",
        delivery_type="pickup",
        payment_method_code="cash",
        subtotal=Decimal("500.00"),
        total_amount=Decimal("500.00"),
        customer_name="Айбек",
        customer_phone="+996700123456",
    )
    _add(session, order)
    return order


def _notification(user: User, **values: object) -> Notification:
    defaults: dict[str, object] = {
        "user_id": user.id,
        "type": NotificationType.ORDER_STATUS_CHANGED,
    }
    return Notification(**(defaults | values))


def _link(user: User, chat_id: int, **values: object) -> TelegramLink:
    defaults: dict[str, object] = {
        "user_id": user.id,
        "telegram_chat_id": chat_id,
        "linked_at": _now(),
    }
    return TelegramLink(**(defaults | values))


def _token(user: User, **values: object) -> TelegramLinkToken:
    defaults: dict[str, object] = {
        "user_id": user.id,
        "token_hash": uuid.uuid4().hex * 2,  # 64 hex chars, like SHA-256
        "expires_at": _now() + timedelta(minutes=10),
    }
    return TelegramLinkToken(**(defaults | values))


def _outbox(user: User, **values: object) -> TelegramOutbox:
    defaults: dict[str, object] = {
        "user_id": user.id,
        "event_type": NotificationType.ORDER_STATUS_CHANGED,
        "payload": {"order_number": "OSH-000001", "new_status": "confirmed"},
        "language_code": "ru",
    }
    return TelegramOutbox(**(defaults | values))


# --------------------------------------------------------------------------- structure

EXPECTED_COLUMNS = {
    "notifications": {
        "id": False, "user_id": False, "order_id": True, "type": False, "payload": False,
        "is_read": False, "created_at": False, "read_at": True,
    },
    "telegram_links": {
        "id": False, "user_id": False, "telegram_chat_id": False, "telegram_username": True,
        "is_active": False, "linked_at": False,
    },
    "telegram_link_tokens": {
        "id": False, "user_id": False, "token_hash": False, "expires_at": False,
        "used_at": True, "created_at": False,
    },
    "telegram_outbox": {
        "id": False, "user_id": False, "order_id": True, "event_type": False,
        "payload": False, "language_code": False, "status": False, "attempts": False,
        "next_attempt_at": False, "sent_at": True, "last_error": True,
        "created_at": False, "updated_at": False,
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
            "column_default FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = ANY(:tables)"
        ),
        {"tables": list(TABLES)},
    ).all()
    info = {name: tuple(rest) for name, *rest in rows}
    tz = ("timestamptz", None, None)
    tz_now = ("timestamptz", None, "now()")

    assert info["notifications.type"] == ("varchar", 50, None)  # no default
    assert info["notifications.payload"] == ("jsonb", None, "'{}'::jsonb")
    assert info["notifications.is_read"] == ("bool", None, "false")
    assert info["notifications.created_at"] == tz_now
    assert info["notifications.read_at"] == tz

    assert info["telegram_links.telegram_chat_id"] == ("int8", None, None)
    assert info["telegram_links.telegram_username"] == ("varchar", 100, None)
    assert info["telegram_links.is_active"] == ("bool", None, "true")
    assert info["telegram_links.linked_at"] == tz  # NOT NULL without default (В3)

    assert info["telegram_link_tokens.token_hash"] == ("text", None, None)
    assert info["telegram_link_tokens.expires_at"] == tz
    assert info["telegram_link_tokens.used_at"] == tz
    assert info["telegram_link_tokens.created_at"] == tz_now

    assert info["telegram_outbox.event_type"] == ("varchar", 50, None)
    assert info["telegram_outbox.payload"] == ("jsonb", None, None)  # no default (§11.4)
    assert info["telegram_outbox.language_code"] == ("varchar", 2, None)
    assert info["telegram_outbox.status"] == ("varchar", 20, "'pending'::character varying")
    assert info["telegram_outbox.attempts"] == ("int2", None, "0")
    assert info["telegram_outbox.next_attempt_at"] == tz_now
    assert info["telegram_outbox.sent_at"] == tz
    assert info["telegram_outbox.last_error"] == ("text", None, None)
    assert info["telegram_outbox.created_at"] == tz_now
    assert info["telegram_outbox.updated_at"] == tz_now
    for table in TABLES:
        assert info[f"{table}.id"] == ("uuid", None, "gen_random_uuid()")


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
        "fk_notifications_user_id_users",
        "fk_notifications_order_id_orders",
        "ck_notifications_type",
        "fk_telegram_links_user_id_users",
        "uq_telegram_links_user_id",
        "uq_telegram_links_telegram_chat_id",
        "fk_telegram_link_tokens_user_id_users",
        "uq_telegram_link_tokens_token_hash",
        "fk_telegram_outbox_user_id_users",
        "fk_telegram_outbox_order_id_orders",
        "ck_telegram_outbox_event_type",
        "ck_telegram_outbox_language_code",
        "ck_telegram_outbox_status",
        "ck_telegram_outbox_attempts_non_negative",
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
    # c = CASCADE, n = SET NULL
    assert dict(rows) == {
        "fk_notifications_user_id_users": "c",
        "fk_notifications_order_id_orders": "n",
        "fk_telegram_links_user_id_users": "c",
        "fk_telegram_link_tokens_user_id_users": "c",
        "fk_telegram_outbox_user_id_users": "c",
        "fk_telegram_outbox_order_id_orders": "n",
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
    expected = {
        ("ix_notifications_user_id_is_read_created_at", "notifications",
         "(user_id, is_read, created_at DESC)", False),
        ("ix_notifications_order_id", "notifications", "(order_id)", False),  # DEC-135
        ("uq_telegram_links_user_id", "telegram_links", "(user_id)", True),
        ("uq_telegram_links_telegram_chat_id", "telegram_links", "(telegram_chat_id)", True),
        ("uq_telegram_link_tokens_token_hash", "telegram_link_tokens", "(token_hash)", True),
        ("ix_telegram_link_tokens_user_id", "telegram_link_tokens",
         "(user_id)", False),  # DEC-135
        ("ix_telegram_outbox_status_next_attempt_at", "telegram_outbox",
         "(status, next_attempt_at)", False),
        ("ix_telegram_outbox_user_id", "telegram_outbox", "(user_id)", False),  # DEC-135
        ("ix_telegram_outbox_order_id", "telegram_outbox", "(order_id)", False),  # DEC-135
    }  # fmt: skip

    def ddl(name: str, table: str, rest: str, unique: bool) -> str:
        kind = "UNIQUE INDEX" if unique else "INDEX"
        return f"CREATE {kind} {name} ON public.{table} USING btree {rest}"

    assert indexes == {name: ddl(name, table, rest, uq) for name, table, rest, uq in expected}


# --------------------------------------------------------------------------- DEC-126


def _check_values(session: Session, constraint: str) -> list[str]:
    definition = session.execute(
        text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :name"),
        {"name": constraint},
    ).scalar_one()
    return re.findall(r"'([a-z_]+)'::character varying", definition)


def test_type_checks_match_enum_and_each_other(db_session: Session) -> None:
    """The fixed SQL literals of 0008 equal NotificationType (DEC-126)."""
    assert TYPES == [
        "order_status_changed",
        "cancellation_request_approved",
        "cancellation_request_rejected",
    ]
    notifications = _check_values(db_session, "ck_notifications_type")
    outbox = _check_values(db_session, "ck_telegram_outbox_event_type")
    assert notifications == TYPES
    assert outbox == TYPES
    assert notifications == outbox


def test_status_and_language_checks_match_enums(db_session: Session) -> None:
    assert _check_values(db_session, "ck_telegram_outbox_status") == [
        member.value for member in TelegramOutboxStatus
    ]
    assert _check_values(db_session, "ck_telegram_outbox_language_code") == ["ru", "ky", "uz"]


@pytest.mark.parametrize("notification_type", TYPES)
def test_all_types_are_accepted(db_session: Session, notification_type: str) -> None:
    user = _user(db_session, "types")
    _add(
        db_session,
        _notification(user, type=notification_type),
        _outbox(user, event_type=notification_type),
    )


@pytest.mark.parametrize("value", ["order_created", "ORDER_STATUS_CHANGED", "", None])
def test_unknown_types_are_rejected(db_session: Session, value: str | None) -> None:
    user = _user(db_session, "unknown")
    _expect_integrity_error(db_session, _notification(user, type=value))
    _expect_integrity_error(db_session, _outbox(user, event_type=value))


# --------------------------------------------------------------------------- notifications


def test_notification_defaults_and_jsonb(db_session: Session) -> None:
    user = _user(db_session, "reader")
    order = _order(db_session, user)
    empty = _notification(user)
    full = _notification(
        user,
        order_id=order.id,
        type=NotificationType.CANCELLATION_REQUEST_REJECTED,
        payload={"order_number": order.order_number, "admin_comment": "Уже готовится"},
    )
    _add(db_session, empty, full)
    db_session.refresh(empty)
    db_session.refresh(full)
    assert empty.payload == {}
    assert empty.is_read is False and empty.read_at is None
    assert empty.order_id is None
    assert empty.created_at.tzinfo is not None
    assert full.payload["admin_comment"] == "Уже готовится"


def test_notification_requires_user(db_session: Session) -> None:
    _expect_integrity_error(db_session, Notification(type=NotificationType.ORDER_STATUS_CHANGED))
    _expect_integrity_error(
        db_session,
        Notification(user_id=uuid.uuid4(), type=NotificationType.ORDER_STATUS_CHANGED),  # FK
    )


# --------------------------------------------------------------------------- telegram links/tokens


def test_link_defaults_and_bigint_chat_id(db_session: Session) -> None:
    user = _user(db_session, "linked")
    link = _link(user, 9_000_000_000_123, telegram_username="osh_user")
    _add(db_session, link)
    db_session.refresh(link)
    assert link.is_active is True
    assert link.telegram_chat_id == 9_000_000_000_123  # above 2**31


def test_link_requires_linked_at(db_session: Session) -> None:
    user = _user(db_session, "nolinkdate")
    _expect_integrity_error(db_session, _link(user, 1, linked_at=None))


def test_one_link_per_user_and_per_chat(db_session: Session) -> None:
    first, second = _user(db_session, "first"), _user(db_session, "second")
    _add(db_session, _link(first, 1001))
    _expect_integrity_error(db_session, _link(first, 1002))  # second link of the same user
    _expect_integrity_error(db_session, _link(second, 1001))  # chat of another account
    _add(db_session, _link(second, 1002))


def test_unlink_allows_linking_the_chat_again(db_session: Session) -> None:
    first, second = _user(db_session, "old"), _user(db_session, "new")
    link = _link(first, 2001)
    _add(db_session, link)
    db_session.delete(link)
    db_session.flush()
    _add(db_session, _link(second, 2001))


def test_token_hash_is_unique_and_tokens_repeat_per_user(db_session: Session) -> None:
    user = _user(db_session, "tokens")
    token = _token(user)
    _add(db_session, token, _token(user, used_at=_now()), _token(user))
    _expect_integrity_error(db_session, _token(user, token_hash=token.token_hash))
    db_session.refresh(token)
    assert token.used_at is None
    assert token.created_at.tzinfo is not None


@pytest.mark.parametrize("field", ["token_hash", "expires_at"])
def test_token_required_fields(db_session: Session, field: str) -> None:
    user = _user(db_session, "tokenreq")
    _expect_integrity_error(db_session, _token(user, **{field: None}))


# --------------------------------------------------------------------------- outbox


def test_outbox_defaults(db_session: Session) -> None:
    user = _user(db_session, "outbox")
    event = _outbox(user)
    _add(db_session, event)
    db_session.refresh(event)
    assert event.status == "pending"
    assert event.attempts == 0
    assert event.next_attempt_at is not None and event.next_attempt_at.tzinfo is not None
    assert event.sent_at is None and event.last_error is None
    assert event.payload == {"order_number": "OSH-000001", "new_status": "confirmed"}


@pytest.mark.parametrize(
    "values",
    [
        {"status": "queued"},
        {"language_code": "en"},
        {"language_code": None},
        {"attempts": -1},
    ],
)
def test_invalid_outbox_values_are_rejected(db_session: Session, values: dict) -> None:
    user = _user(db_session, "badoutbox")
    _expect_integrity_error(db_session, _outbox(user, **values))


@pytest.mark.parametrize("table", ["notifications", "telegram_outbox"])
def test_sql_null_payload_is_rejected(db_session: Session, table: str) -> None:
    """NOT NULL on payload, checked with raw SQL.

    Through the ORM, Python None is stored as JSON `null` (JSONB default
    none_as_null=False), so the constraint is verified with a SQL NULL.
    """
    user = _user(db_session, "nullpayload")
    column = "type" if table == "notifications" else "event_type"
    extra = ", language_code" if table == "telegram_outbox" else ""
    extra_value = ", 'ru'" if table == "telegram_outbox" else ""
    with pytest.raises(IntegrityError, match="payload"), db_session.begin_nested():
        db_session.execute(
            text(
                f"INSERT INTO {table} (user_id, {column}, payload{extra}) "  # noqa: S608
                f"VALUES (:u, 'order_status_changed', NULL{extra_value})"
            ),
            {"u": user.id},
        )


def test_all_outbox_statuses_and_languages_are_accepted(db_session: Session) -> None:
    user = _user(db_session, "statuses")
    _add(
        db_session,
        *(_outbox(user, status=status) for status in TelegramOutboxStatus),
        *(_outbox(user, language_code=code) for code in ("ru", "ky", "uz")),
        _outbox(user, attempts=5, status="failed", last_error="HTTP 500"),
    )
    assert _count(db_session, "telegram_outbox", "user_id", user.id) == 8


# --------------------------------------------------------------------------- delete rules


def _populate(session: Session, user: User, order: Order | None = None) -> None:
    order_id = order.id if order else None
    _add(
        session,
        _notification(user, order_id=order_id),
        _link(user, int(uuid.uuid4().int % 10**12)),
        _token(user),
        _outbox(user, order_id=order_id),
    )


def test_deleting_user_cascades_everything(db_session: Session) -> None:
    user = _user(db_session, "gone")  # no orders: orders.user_id is RESTRICT
    _populate(db_session, user)
    db_session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user.id})
    for table in TABLES:
        assert _count(db_session, table, "user_id", user.id) == 0, table


def test_orm_delete_of_user_relies_on_database_cascade(db_session: Session) -> None:
    user = _user(db_session, "ormgone")
    _populate(db_session, user)
    db_session.expunge_all()
    db_session.delete(db_session.get(User, user.id))
    db_session.flush()
    for table in TABLES:
        assert _count(db_session, table, "user_id", user.id) == 0, table


def test_deleting_order_sets_order_id_null(db_session: Session) -> None:
    user = _user(db_session, "orderless")
    order = _order(db_session, user)
    _populate(db_session, user, order)
    db_session.execute(text("DELETE FROM orders WHERE id = :id"), {"id": order.id})
    assert _count(db_session, "notifications", "user_id", user.id) == 1
    assert _count(db_session, "telegram_outbox", "user_id", user.id) == 1
    assert _count(db_session, "notifications", "order_id", order.id) == 0
    assert _count(db_session, "telegram_outbox", "order_id", order.id) == 0


# --------------------------------------------------------------------------- relationships


def test_relationships_require_explicit_loading(db_session: Session) -> None:
    user = _user(db_session, "rel")
    order = _order(db_session, user)
    notification = _notification(user, order_id=order.id)
    link = _link(user, 3001)
    token = _token(user)
    event = _outbox(user, order_id=order.id)
    _add(db_session, notification, link, token, event)
    db_session.expunge_all()

    lazy_user = db_session.get(User, user.id)
    for attribute in ("notifications", "telegram_link", "telegram_link_tokens", "telegram_outbox"):
        with pytest.raises(InvalidRequestError, match="lazy='raise'"):
            getattr(lazy_user, attribute)
    lazy_order = db_session.get(Order, order.id)
    for attribute in ("notifications", "telegram_outbox"):
        with pytest.raises(InvalidRequestError, match="lazy='raise'"):
            getattr(lazy_order, attribute)
    checks = (
        (Notification, notification.id, ("user", "order")),
        (TelegramLink, link.id, ("user",)),
        (TelegramLinkToken, token.id, ("user",)),
        (TelegramOutbox, event.id, ("user", "order")),
    )
    for model, pk, attributes in checks:
        instance = db_session.get(model, pk)
        for attribute in attributes:
            with pytest.raises(InvalidRequestError, match="lazy='raise'"):
                getattr(instance, attribute)
    db_session.expunge_all()

    loaded_user = db_session.scalars(
        select(User)
        .where(User.id == user.id)
        .options(
            selectinload(User.notifications).joinedload(Notification.order),
            joinedload(User.telegram_link),
            selectinload(User.telegram_link_tokens),
            selectinload(User.telegram_outbox).joinedload(TelegramOutbox.order),
        )
    ).one()
    assert [n.order.id for n in loaded_user.notifications] == [order.id]
    assert loaded_user.telegram_link is not None
    assert loaded_user.telegram_link.telegram_chat_id == 3001
    assert [t.token_hash for t in loaded_user.telegram_link_tokens] == [token.token_hash]
    assert [e.order.id for e in loaded_user.telegram_outbox] == [order.id]
    db_session.expunge_all()

    loaded_order = db_session.scalars(
        select(Order)
        .where(Order.id == order.id)
        .options(
            selectinload(Order.notifications).joinedload(Notification.user),
            selectinload(Order.telegram_outbox).joinedload(TelegramOutbox.user),
        )
    ).one()
    assert [n.user.email for n in loaded_order.notifications] == ["rel@example.kg"]
    assert [e.user.email for e in loaded_order.telegram_outbox] == ["rel@example.kg"]


def test_user_without_link_loads_none(db_session: Session) -> None:
    user = _user(db_session, "nolink")
    db_session.expunge_all()
    loaded = db_session.scalars(
        select(User).where(User.id == user.id).options(joinedload(User.telegram_link))
    ).one()
    assert loaded.telegram_link is None
