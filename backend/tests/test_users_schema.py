"""Users domain schema on the isolated test database (DATABASE_SCHEMA.md §3).

Every test runs inside a transaction that is rolled back (`db_session`),
so no data persists in db-test.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError, InvalidRequestError
from sqlalchemy.orm import Session, selectinload

from app.modules.users.models import (
    Address,
    CourierProfile,
    PasswordResetToken,
    RefreshToken,
    Role,
    User,
    UserRole,
)

pytestmark = pytest.mark.db


# --------------------------------------------------------------------------- helpers


def _user(session: Session, email: str = "user@example.kg", **values: object) -> User:
    user = User(email=email, password_hash="argon2-hash", full_name="Test User", **values)
    session.add(user)
    session.flush()
    return user


def _role(session: Session, name: str = "customer") -> Role:
    role = Role(name=name)
    session.add(role)
    session.flush()
    return role


def _expect_integrity_error(session: Session, *objects: object) -> None:
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add_all(objects)
        session.flush()


def _expect_sql_error(session: Session, sql: str, **params: object) -> None:
    with pytest.raises(IntegrityError), session.begin_nested():
        session.execute(text(sql), params)


def _count(session: Session, table: str, **where: object) -> int:
    condition = " AND ".join(f"{column} = :{column}" for column in where) or "TRUE"
    return session.execute(
        text(f"SELECT count(*) FROM {table} WHERE {condition}"),  # noqa: S608 - test-only literals
        where,
    ).scalar_one()


def _expires() -> datetime:
    return datetime.now(UTC) + timedelta(days=30)


# --------------------------------------------------------------------------- structure

EXPECTED_COLUMNS = {
    "users": {
        "id": False, "email": True, "password_hash": True, "full_name": False,
        "phone": True, "preferred_language": False, "is_active": False,
        "is_verified": False, "must_change_password": False,
        "created_at": False, "updated_at": False,
    },
    "roles": {"id": False, "name": False, "description": True, "created_at": False},
    "user_roles": {"user_id": False, "role_id": False, "assigned_at": False},
    "courier_profiles": {
        "user_id": False, "is_available": False, "max_active_orders": False,
        "created_at": False, "updated_at": False,
    },
    "addresses": {
        "id": False, "user_id": False, "label": True, "address_text": False,
        "latitude": True, "longitude": True, "entrance": True, "floor": True,
        "apartment": True, "comment": True, "is_default": False,
        "created_at": False, "updated_at": False,
    },
    "refresh_tokens": {
        "id": False, "user_id": False, "family_id": False, "token_hash": False,
        "replaced_by_id": True, "expires_at": False, "revoked_at": True, "created_at": False,
    },
    "password_reset_tokens": {
        "id": False, "user_id": False, "token_hash": False, "expires_at": False,
        "used_at": True, "created_at": False,
    },
}  # fmt: skip


@pytest.mark.parametrize("table", sorted(EXPECTED_COLUMNS))
def test_columns_and_nullability(db_session: Session, table: str) -> None:
    columns = {
        column["name"]: column["nullable"]
        for column in inspect(db_session.connection()).get_columns(table)
    }
    assert columns == EXPECTED_COLUMNS[table]


def test_column_types(db_session: Session) -> None:
    rows = db_session.execute(
        text(
            "SELECT table_name || '.' || column_name, data_type, character_maximum_length, "
            "numeric_precision, numeric_scale FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name IN ('users', 'addresses', "
            "'courier_profiles', 'refresh_tokens')"
        )
    ).all()
    types = {name: rest for name, *rest in rows}
    assert types["users.id"][0] == "uuid"
    assert types["users.email"] == ["character varying", 255, None, None]
    assert types["users.phone"] == ["character varying", 30, None, None]
    assert types["users.preferred_language"] == ["character varying", 2, None, None]
    assert types["users.created_at"][0] == "timestamp with time zone"
    assert types["addresses.latitude"] == ["numeric", None, 10, 7]
    assert types["addresses.longitude"] == ["numeric", None, 10, 7]
    assert types["courier_profiles.max_active_orders"][0] == "smallint"
    assert types["refresh_tokens.family_id"][0] == "uuid"
    assert types["refresh_tokens.expires_at"][0] == "timestamp with time zone"


def test_indexes(db_session: Session) -> None:
    rows = db_session.execute(
        text(
            "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' AND tablename "
            "IN ('users', 'addresses', 'refresh_tokens', 'password_reset_tokens', 'roles')"
        )
    ).all()
    indexes = dict(rows)
    assert "UNIQUE INDEX" in indexes["uq_users_email_lower"]
    assert "lower((email)::text)" in indexes["uq_users_email_lower"]
    assert "(user_id)" in indexes["ix_addresses_user_id"]
    assert "UNIQUE INDEX" in indexes["uq_addresses_user_id_default"]
    assert "WHERE is_default" in indexes["uq_addresses_user_id_default"]
    assert "(user_id, expires_at)" in indexes["ix_refresh_tokens_user_id_expires_at"]
    assert "(family_id)" in indexes["ix_refresh_tokens_family_id"]
    assert "UNIQUE INDEX" in indexes["uq_refresh_tokens_token_hash"]
    assert "UNIQUE INDEX" in indexes["uq_password_reset_tokens_token_hash"]
    assert "UNIQUE INDEX" in indexes["uq_roles_name"]


def test_password_reset_tokens_user_id_index(db_session: Session) -> None:
    """DEC-127: plain B-tree index on password_reset_tokens(user_id)."""
    definition = db_session.execute(
        text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_password_reset_tokens_user_id'")
    ).scalar_one()
    assert definition == (
        "CREATE INDEX ix_password_reset_tokens_user_id "
        "ON public.password_reset_tokens USING btree (user_id)"
    )

    # The invalidation query can use it (sequential scans disabled to make
    # the planner's choice independent of the tiny test table size).
    db_session.execute(text("SET LOCAL enable_seqscan = off"))
    plan = "\n".join(
        db_session.execute(
            text(
                # A constant UUID: a volatile function (gen_random_uuid())
                # would be evaluated per row and could never use an index.
                "EXPLAIN UPDATE password_reset_tokens SET used_at = now() "
                "WHERE user_id = '00000000-0000-0000-0000-000000000000'::uuid "
                "AND used_at IS NULL"
            )
        ).scalars()
    )
    assert "ix_password_reset_tokens_user_id" in plan


def test_foreign_keys_and_delete_rules(db_session: Session) -> None:
    rows = db_session.execute(
        text(
            "SELECT conrelid::regclass::text, confrelid::regclass::text, confdeltype "
            "FROM pg_constraint WHERE contype = 'f' AND connamespace = 'public'::regnamespace "
            "AND conrelid::regclass::text = ANY(:tables)"
        ),
        {"tables": list(EXPECTED_COLUMNS)},  # only the users domain tables
    ).all()
    rules = {(table, target): rule for table, target, rule in rows}
    # c = CASCADE, r = RESTRICT, n = SET NULL
    assert rules == {
        ("user_roles", "users"): "c",
        ("user_roles", "roles"): "r",
        ("courier_profiles", "users"): "c",
        ("addresses", "users"): "c",
        ("refresh_tokens", "users"): "c",
        ("refresh_tokens", "refresh_tokens"): "n",
        ("password_reset_tokens", "users"): "c",
    }


# --------------------------------------------------------------------------- users


def test_user_defaults_are_generated_by_the_database(db_session: Session) -> None:
    user = _user(db_session)
    db_session.refresh(user)

    assert isinstance(user.id, uuid.UUID)
    assert user.preferred_language == "ru"
    assert user.is_active is True
    assert user.is_verified is False
    assert user.must_change_password is False
    assert user.created_at.tzinfo is not None
    assert user.updated_at.tzinfo is not None


def test_updated_at_is_refreshed_on_orm_update(db_session: Session) -> None:
    user = _user(db_session)
    old = datetime(2020, 1, 1, tzinfo=UTC)
    db_session.execute(
        text("UPDATE users SET updated_at = :old WHERE id = :id"), {"old": old, "id": user.id}
    )
    db_session.refresh(user)
    assert user.updated_at == old

    user.full_name = "Renamed"
    db_session.flush()
    db_session.refresh(user)
    assert user.updated_at > old


def test_email_is_unique_case_insensitive(db_session: Session) -> None:
    _user(db_session, email="User@Example.kg")
    _expect_integrity_error(
        db_session, User(email="user@example.kg", password_hash="h", full_name="Other")
    )


def test_telegram_only_accounts_have_neither_email_nor_password(db_session: Session) -> None:
    """DEC-142 K2-B: both NULL is allowed, and NULLs do not collide in uq_users_email_lower."""
    first = User(email=None, password_hash=None, full_name="Telegram One")
    second = User(email=None, password_hash=None, full_name="Telegram Two")
    db_session.add_all([first, second])
    db_session.flush()
    assert first.email is None and second.email is None


@pytest.mark.parametrize(
    ("email", "password_hash"), [("half@example.kg", None), (None, "argon2-hash")]
)
def test_credentials_pair_check(
    db_session: Session, email: str | None, password_hash: str | None
) -> None:
    """`ck_users_credentials_pair`: email and password_hash both set or both NULL."""
    with (
        pytest.raises(IntegrityError, match="ck_users_credentials_pair"),
        db_session.begin_nested(),
    ):
        db_session.add(User(email=email, password_hash=password_hash, full_name="Half"))
        db_session.flush()


@pytest.mark.parametrize("phone", ["+996700123456", None])
def test_valid_phone(db_session: Session, phone: str | None) -> None:
    assert _user(db_session, phone=phone).phone == phone


@pytest.mark.parametrize(
    "phone", ["+99670012345", "+9967001234567", "0700123456", "+996 700123456", "+997700123456"]
)
def test_invalid_phone_is_rejected(db_session: Session, phone: str) -> None:
    _expect_integrity_error(
        db_session, User(email="p@example.kg", password_hash="h", full_name="P", phone=phone)
    )


def test_preferred_language_is_restricted(db_session: Session) -> None:
    for language in ("ru", "ky", "uz"):
        _user(db_session, email=f"{language}@example.kg", preferred_language=language)
    _expect_integrity_error(
        db_session,
        User(email="en@example.kg", password_hash="h", full_name="E", preferred_language="en"),
    )


# --------------------------------------------------------------------------- roles


def test_role_name_is_unique(db_session: Session) -> None:
    _role(db_session, "admin")
    _expect_integrity_error(db_session, Role(name="admin"))


def test_user_role_pk_cascade_and_restrict(db_session: Session) -> None:
    user = _user(db_session)
    role = _role(db_session)
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    db_session.flush()

    _expect_integrity_error(db_session, UserRole(user_id=user.id, role_id=role.id))
    # A role that is still assigned cannot be deleted (RESTRICT).
    _expect_sql_error(db_session, "DELETE FROM roles WHERE id = :id", id=role.id)
    # Deleting the user removes its role links (CASCADE).
    db_session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user.id})
    assert _count(db_session, "user_roles", role_id=role.id) == 0
    assert _count(db_session, "roles", id=role.id) == 1


# --------------------------------------------------------------------------- courier profiles


def test_courier_profile_defaults_check_and_cascade(db_session: Session) -> None:
    user = _user(db_session)
    profile = CourierProfile(user_id=user.id)
    db_session.add(profile)
    db_session.flush()
    db_session.refresh(profile)
    assert profile.is_available is False
    assert profile.max_active_orders == 1

    other = _user(db_session, email="courier2@example.kg")
    _expect_integrity_error(db_session, CourierProfile(user_id=other.id, max_active_orders=0))

    db_session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user.id})
    assert _count(db_session, "courier_profiles", user_id=user.id) == 0


# --------------------------------------------------------------------------- addresses


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [(D("90"), D("180")), (D("-90"), D("-180")), (D("40.5283000"), D("72.7985000"))],
)
def test_valid_coordinates(db_session: Session, latitude: D, longitude: D) -> None:
    user = _user(db_session)
    db_session.add(
        Address(user_id=user.id, address_text="Ош", latitude=latitude, longitude=longitude)
    )
    db_session.flush()


@pytest.mark.parametrize(
    ("latitude", "longitude"), [(D("90.0000001"), D("0")), (D("0"), D("-180.0000001"))]
)
def test_invalid_coordinates_are_rejected(db_session: Session, latitude: D, longitude: D) -> None:
    user = _user(db_session)
    _expect_integrity_error(
        db_session,
        Address(user_id=user.id, address_text="Ош", latitude=latitude, longitude=longitude),
    )


def test_one_default_address_per_user(db_session: Session) -> None:
    user = _user(db_session)
    other = _user(db_session, email="other@example.kg")
    db_session.add_all(
        [
            Address(user_id=user.id, address_text="A", is_default=True),
            Address(user_id=user.id, address_text="B"),
            Address(user_id=user.id, address_text="C"),
            Address(user_id=other.id, address_text="D", is_default=True),
        ]
    )
    db_session.flush()

    _expect_integrity_error(db_session, Address(user_id=user.id, address_text="E", is_default=True))


def test_addresses_cascade_with_user(db_session: Session) -> None:
    user = _user(db_session)
    db_session.add(Address(user_id=user.id, address_text="A"))
    db_session.flush()
    db_session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user.id})
    assert _count(db_session, "addresses", user_id=user.id) == 0


# --------------------------------------------------------------------------- tokens


def test_refresh_tokens_unique_hash_set_null_and_cascade(db_session: Session) -> None:
    user = _user(db_session)
    family = uuid.uuid4()
    newer = RefreshToken(user_id=user.id, family_id=family, token_hash="h2", expires_at=_expires())
    db_session.add(newer)
    db_session.flush()
    older = RefreshToken(
        user_id=user.id,
        family_id=family,
        token_hash="h1",
        expires_at=_expires(),
        replaced_by_id=newer.id,
    )
    db_session.add(older)
    db_session.flush()

    _expect_integrity_error(
        db_session,
        RefreshToken(user_id=user.id, family_id=family, token_hash="h1", expires_at=_expires()),
    )
    _expect_sql_error(
        db_session,
        "INSERT INTO refresh_tokens (user_id, token_hash, expires_at) VALUES (:u, 'h3', now())",
        u=user.id,
    )  # family_id is NOT NULL

    # Deleting the successor keeps the older token but clears the link (SET NULL).
    db_session.execute(text("DELETE FROM refresh_tokens WHERE id = :id"), {"id": newer.id})
    db_session.refresh(older)
    assert older.replaced_by_id is None

    db_session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user.id})
    assert _count(db_session, "refresh_tokens", user_id=user.id) == 0


def test_password_reset_tokens_unique_hash_and_cascade(db_session: Session) -> None:
    user = _user(db_session)
    db_session.add(PasswordResetToken(user_id=user.id, token_hash="r1", expires_at=_expires()))
    db_session.flush()

    _expect_integrity_error(
        db_session, PasswordResetToken(user_id=user.id, token_hash="r1", expires_at=_expires())
    )
    db_session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user.id})
    assert _count(db_session, "password_reset_tokens", user_id=user.id) == 0


# --------------------------------------------------------------------------- relationships


def test_relationships_require_explicit_loading(db_session: Session) -> None:
    user = _user(db_session)
    role = _role(db_session)
    db_session.add_all(
        [
            UserRole(user_id=user.id, role_id=role.id),
            CourierProfile(user_id=user.id),
            Address(user_id=user.id, address_text="A"),
        ]
    )
    db_session.flush()
    db_session.expunge_all()

    lazy_user = db_session.get(User, user.id)
    assert lazy_user is not None
    for attribute in ("roles", "courier_profile", "addresses"):
        with pytest.raises(InvalidRequestError, match="lazy='raise'"):
            getattr(lazy_user, attribute)
    db_session.expunge_all()

    loaded = db_session.scalars(
        select(User)
        .where(User.id == user.id)
        .options(
            selectinload(User.roles),
            selectinload(User.courier_profile),
            selectinload(User.addresses),
        )
    ).one()
    assert [r.name for r in loaded.roles] == ["customer"]
    assert loaded.courier_profile is not None
    assert [a.address_text for a in loaded.addresses] == ["A"]
