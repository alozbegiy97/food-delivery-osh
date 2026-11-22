"""Migrations on the isolated test database only (db-test, tmpfs storage).

The main database is never downgraded by tests: every Alembic call goes
through `run_alembic`, which first verifies the target database.
"""

import psycopg
import pytest

from tests.conftest import run_alembic, sync_database_url, verify_test_database

pytestmark = pytest.mark.db

HEAD = "0009_telegram_only_accounts"

USERS_TABLES = {
    "users",
    "roles",
    "user_roles",
    "courier_profiles",
    "addresses",
    "refresh_tokens",
    "password_reset_tokens",
}
RESTAURANT_DELIVERY_TABLES = {
    "restaurant_settings",
    "restaurant_working_hours",
    "payment_methods",
    "delivery_zones",
}
CATALOG_TABLES = {
    "categories",
    "category_translations",
    "products",
    "product_translations",
    "product_images",
    "product_variants",
    "product_variant_translations",
    "modifier_groups",
    "modifier_group_translations",
    "modifiers",
    "modifier_translations",
    "product_modifier_groups",
    "variant_modifier_prices",
}
CART_TABLES = {"carts", "cart_items", "cart_item_modifiers"}
ORDERS_TABLES = {
    "orders",
    "order_items",
    "order_item_modifiers",
    "order_status_history",
    "cancellation_requests",
    "idempotency_keys",
}
PAYMENTS_DELIVERIES_TABLES = {"payments", "deliveries", "courier_assignments"}
NOTIFICATIONS_TABLES = {
    "notifications",
    "telegram_links",
    "telegram_link_tokens",
    "telegram_outbox",
}
UP_TO_CATALOG = USERS_TABLES | RESTAURANT_DELIVERY_TABLES | CATALOG_TABLES
UP_TO_CARTS = UP_TO_CATALOG | CART_TABLES
UP_TO_ORDERS = UP_TO_CARTS | ORDERS_TABLES
UP_TO_PAYMENTS_DELIVERIES = UP_TO_ORDERS | PAYMENTS_DELIVERIES_TABLES
ALL_TABLES = UP_TO_PAYMENTS_DELIVERIES | NOTIFICATIONS_TABLES


def _postgis_installed() -> bool:
    with psycopg.connect(sync_database_url()) as conn:
        row = conn.execute("SELECT 1 FROM pg_extension WHERE extname = 'postgis'").fetchone()
        return row is not None


def _public_tables() -> set[str]:
    with psycopg.connect(sync_database_url()) as conn:
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
        ).fetchall()
    return {row[0] for row in rows} - {"alembic_version", "spatial_ref_sys"}


def _order_number_objects() -> tuple[bool, bool]:
    """(sequence exists, function exists) — created by 0006 (DEC-123)."""
    with psycopg.connect(sync_database_url()) as conn:
        seq = conn.execute("SELECT to_regclass('public.order_number_seq') IS NOT NULL").fetchone()
        fn = conn.execute("SELECT to_regproc('public.next_order_number') IS NOT NULL").fetchone()
    return bool(seq[0]), bool(fn[0])


def _credentials_schema() -> tuple[bool, bool, bool]:
    """(email nullable, password_hash nullable, CHECK ck_users_credentials_pair exists)."""
    with psycopg.connect(sync_database_url()) as conn:
        nullable = dict(
            conn.execute(
                "SELECT column_name, is_nullable = 'YES' FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'users' "
                "AND column_name IN ('email', 'password_hash')"
            ).fetchall()
        )
        check = conn.execute(
            "SELECT 1 FROM pg_constraint WHERE conname = 'ck_users_credentials_pair' "
            "AND conrelid = 'public.users'::regclass AND contype = 'c'"
        ).fetchone()
    return nullable["email"], nullable["password_hash"], check is not None


def _current_revision() -> str:
    return run_alembic("current").stdout.strip()


def test_target_is_isolated_test_database() -> None:
    assert verify_test_database().split("/")[-1].endswith("_test")


def test_full_cycle_from_clean_database() -> None:
    run_alembic("downgrade", "base")
    assert not _postgis_installed()
    assert _public_tables() == set()

    # Clean sequence 0001 -> ... -> 0009, step by step.
    run_alembic("upgrade", "0001_enable_postgis")
    assert _postgis_installed()
    assert _public_tables() == set()
    run_alembic("upgrade", "0002_users")
    assert _public_tables() == USERS_TABLES
    run_alembic("upgrade", "0003_restaurant_delivery")
    assert _public_tables() == USERS_TABLES | RESTAURANT_DELIVERY_TABLES
    run_alembic("upgrade", "0004_catalog")
    assert _public_tables() == UP_TO_CATALOG
    run_alembic("upgrade", "0005_carts")
    assert _public_tables() == UP_TO_CARTS
    assert _order_number_objects() == (False, False)
    run_alembic("upgrade", "0006_orders")
    assert _public_tables() == UP_TO_ORDERS
    assert _order_number_objects() == (True, True)
    run_alembic("upgrade", "0007_payments_deliveries")
    assert _public_tables() == UP_TO_PAYMENTS_DELIVERIES
    run_alembic("upgrade", "0008_notifications")
    assert _public_tables() == ALL_TABLES
    assert _credentials_schema() == (False, False, False)
    run_alembic("upgrade", HEAD)
    assert _public_tables() == ALL_TABLES  # 0009 adds no tables
    assert _credentials_schema() == (True, True, True)
    assert _order_number_objects() == (True, True)
    assert f"{HEAD} (head)" in _current_revision()


def test_telegram_only_accounts_downgrade_and_upgrade_again() -> None:
    run_alembic("upgrade", "head")
    assert _credentials_schema() == (True, True, True)

    run_alembic("downgrade", "0008_notifications")
    assert _credentials_schema() == (False, False, False)
    assert _public_tables() == ALL_TABLES
    assert "0008_notifications" in _current_revision()

    run_alembic("upgrade", HEAD)
    assert _credentials_schema() == (True, True, True)
    assert f"{HEAD} (head)" in _current_revision()


def test_telegram_only_accounts_downgrade_refused_while_such_accounts_exist() -> None:
    """Downgrade 0009 never deletes Telegram-only accounts: it stops instead."""
    run_alembic("upgrade", "head")
    verify_test_database()
    with psycopg.connect(sync_database_url()) as conn:
        user_id = conn.execute(
            "INSERT INTO users (full_name) VALUES ('Telegram only') RETURNING id"
        ).fetchone()[0]
    try:
        result = run_alembic("downgrade", "0008_notifications", expect_success=False)
        assert "Downgrade 0009 refused" in result.stderr
        # Nothing changed: still at head, columns nullable, CHECK and row kept.
        assert f"{HEAD} (head)" in _current_revision()
        assert _credentials_schema() == (True, True, True)
        with psycopg.connect(sync_database_url()) as conn:
            row = conn.execute(
                "SELECT email, password_hash FROM users WHERE id = %s", (user_id,)
            ).fetchone()
        assert row == (None, None)
    finally:
        with psycopg.connect(sync_database_url()) as conn:
            conn.execute("DELETE FROM users WHERE id = %s", (user_id,))

    run_alembic("downgrade", "0008_notifications")  # works again without such rows
    assert _credentials_schema() == (False, False, False)
    run_alembic("upgrade", HEAD)


def test_notifications_downgrade_and_upgrade_again() -> None:
    run_alembic("upgrade", "0009_telegram_only_accounts")

    run_alembic("downgrade", "0007_payments_deliveries")
    assert _public_tables() == UP_TO_PAYMENTS_DELIVERIES
    assert _order_number_objects() == (True, True)
    assert "0007_payments_deliveries" in _current_revision()

    run_alembic("upgrade", HEAD)
    assert _public_tables() == ALL_TABLES
    assert f"{HEAD} (head)" in _current_revision()


def test_payments_deliveries_downgrade_and_upgrade_again() -> None:
    run_alembic("upgrade", "head")

    run_alembic("downgrade", "0006_orders")
    assert _public_tables() == UP_TO_ORDERS
    # 0006 objects are untouched by the 0007 downgrade.
    assert _order_number_objects() == (True, True)
    assert "0006_orders" in _current_revision()

    run_alembic("upgrade", HEAD)
    assert _public_tables() == ALL_TABLES
    assert f"{HEAD} (head)" in _current_revision()


def test_orders_downgrade_and_upgrade_again() -> None:
    run_alembic("upgrade", "head")

    run_alembic("downgrade", "0005_carts")
    assert _public_tables() == UP_TO_CARTS
    assert _order_number_objects() == (False, False)
    assert "0005_carts" in _current_revision()

    run_alembic("upgrade", HEAD)
    assert _public_tables() == ALL_TABLES
    assert _order_number_objects() == (True, True)
    assert f"{HEAD} (head)" in _current_revision()


def test_carts_downgrade_and_upgrade_again() -> None:
    run_alembic("upgrade", "head")

    run_alembic("downgrade", "0004_catalog")
    assert _public_tables() == UP_TO_CATALOG
    assert "0004_catalog" in _current_revision()

    run_alembic("upgrade", HEAD)
    assert _public_tables() == ALL_TABLES
    assert f"{HEAD} (head)" in _current_revision()


def test_catalog_downgrade_and_upgrade_again() -> None:
    run_alembic("upgrade", "head")

    run_alembic("downgrade", "0003_restaurant_delivery")
    assert _public_tables() == USERS_TABLES | RESTAURANT_DELIVERY_TABLES
    assert "0003_restaurant_delivery" in _current_revision()

    run_alembic("upgrade", HEAD)
    assert _public_tables() == ALL_TABLES
    assert f"{HEAD} (head)" in _current_revision()


def test_restaurant_delivery_downgrade_and_upgrade_again() -> None:
    run_alembic("upgrade", "head")

    run_alembic("downgrade", "0002_users")
    assert _public_tables() == USERS_TABLES
    assert "0002_users" in _current_revision()

    run_alembic("upgrade", HEAD)
    assert _public_tables() == ALL_TABLES
    assert f"{HEAD} (head)" in _current_revision()


def test_users_revision_downgrade_and_upgrade_again() -> None:
    run_alembic("upgrade", "head")

    run_alembic("downgrade", "0001_enable_postgis")
    assert _public_tables() == set()
    assert _postgis_installed()
    assert "0001_enable_postgis" in _current_revision()

    run_alembic("upgrade", "head")
    assert _public_tables() == ALL_TABLES
    assert f"{HEAD} (head)" in _current_revision()


def test_models_match_migrations() -> None:
    """`alembic check` fails if models and migrations have drifted apart."""
    run_alembic("upgrade", "head")
    result = run_alembic("check")
    assert "No new upgrade operations detected" in result.stdout + result.stderr
