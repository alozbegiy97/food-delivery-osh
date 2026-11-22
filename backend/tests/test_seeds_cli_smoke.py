"""Smoke test of the seed CLI on the isolated `db-test` (DEC-137).

The CLI commits, so this test cleans up after itself:
- before any run it checks that no seed-keyed or conflicting record exists
  (otherwise it fails and deletes nothing);
- it snapshots all rows and the primary keys of the 17 touched tables;
- in `finally` it deletes exactly the rows created by this test (current
  primary keys minus the snapshot), after checking ownership, external
  foreign keys, the FK set of the real database and the delete order;
  all checks run before the first DELETE, all DELETEs run in one
  transaction with row-count checks, any problem rolls the cleanup back;
- finally all rows of the touched tables must equal the snapshot.
"""

import os
import re
import subprocess
import sys
from typing import Any
from urllib.parse import urlsplit

import pytest
from sqlalchemy import Connection, Engine, Table, delete, func, select, text, tuple_

from app.db.base import Base
from app.modules.payments.enums import PaymentMethodCode
from app.modules.users.enums import RoleName
from app.seeds import demo_data as data
from tests.conftest import BACKEND_DIR, TEST_DATABASE_URL, sync_database_url, verify_test_database

pytestmark = pytest.mark.db

BASE_TABLES = ["roles", "payment_methods", "restaurant_settings", "restaurant_working_hours"]
DEMO_TABLES = [
    "delivery_zones",
    "categories",
    "category_translations",
    "modifier_groups",
    "modifier_group_translations",
    "modifiers",
    "modifier_translations",
    "products",
    "product_translations",
    "product_modifier_groups",
    "product_variants",
    "product_variant_translations",
    "variant_modifier_prices",
]
TOUCHED = [*BASE_TABLES, *DEMO_TABLES]
SNAPSHOT_TABLES = [*TOUCHED, "users", "user_roles"]

BASE_CREATED = {
    "roles": 4,
    "payment_methods": 2,
    "restaurant_settings": 1,
    "restaurant_working_hours": 7,
}
DEMO_CREATED = {
    "delivery_zones": 1,
    "categories": 8,
    "category_translations": 24,
    "modifier_groups": 4,
    "modifier_group_translations": 12,
    "modifiers": 10,
    "modifier_translations": 30,
    "products": 21,
    "product_translations": 63,
    "product_modifier_groups": 11,
    "product_variants": 30,
    "product_variant_translations": 90,
    "variant_modifier_prices": 9,
}
REPORT_LINE = re.compile(r"^(\w+): создано (\d+), уже было (\d+)$", re.MULTILINE)

Key = tuple[Any, ...]


def _table(name: str) -> Table:
    return Base.metadata.tables[name]


# --- Expected seed keys -------------------------------------------------------------


def _expected_demo_keys() -> dict[str, set[Key]]:
    rows = {
        "categories": data.category_rows(),
        "category_translations": data.category_translation_rows(),
        "modifier_groups": data.modifier_group_rows(),
        "modifier_group_translations": data.modifier_group_translation_rows(),
        "modifiers": data.modifier_rows(),
        "modifier_translations": data.modifier_translation_rows(),
        "products": data.product_rows(),
        "product_translations": data.product_translation_rows(),
        "product_variants": data.variant_rows(),
        "product_variant_translations": data.variant_translation_rows(),
    }
    keys = {name: {(row["id"],) for row in table_rows} for name, table_rows in rows.items()}
    keys["delivery_zones"] = {(data.zone_id(data.DEMO_ZONE.code),)}
    keys["product_modifier_groups"] = {
        (row["product_id"], row["group_id"]) for row in data.product_modifier_group_rows()
    }
    keys["variant_modifier_prices"] = {
        (row["variant_id"], row["modifier_id"]) for row in data.variant_modifier_price_rows()
    }
    return keys


EXPECTED_DEMO_KEYS = _expected_demo_keys()
# base records have no UUIDv5: ownership is checked by their natural key.
BASE_NATURAL_KEYS: dict[str, tuple[str, set[Any]]] = {
    "roles": ("name", {role.value for role in RoleName}),
    "payment_methods": ("code", {code.value for code in PaymentMethodCode}),
    "restaurant_settings": ("id", {1}),
    "restaurant_working_hours": ("weekday", set(range(7))),
}


# --- Snapshots ------------------------------------------------------------------------


def _rows_snapshot(conn: Connection) -> dict[str, list[Key]]:
    snapshot = {}
    for name in SNAPSHOT_TABLES:
        table = _table(name)
        columns = [
            func.ST_AsEWKT(column).label(column.name) if column.name == "boundary" else column
            for column in table.columns
        ]
        query = select(*columns).order_by(*table.primary_key.columns)
        snapshot[name] = [tuple(row) for row in conn.execute(query)]
    return snapshot


def _pk_sets(conn: Connection) -> dict[str, set[Key]]:
    return {
        name: {tuple(row) for row in conn.execute(select(*_table(name).primary_key.columns))}
        for name in TOUCHED
    }


# --- Isolation and cleanliness ----------------------------------------------------------


def _expected_db_name() -> str:
    return urlsplit(sync_database_url()).path.lstrip("/")


def _assert_isolation(engine: Engine) -> str:
    verify_test_database()
    expected = _expected_db_name()
    assert expected.endswith("_test")
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT current_database()")) == expected
    return expected


def _findings_before_run(conn: Connection) -> list[str]:
    """Seed-keyed or conflicting records that must not exist before the test."""
    findings: list[str] = []
    for name, (column, values) in BASE_NATURAL_KEYS.items():
        table = _table(name)
        found = conn.execute(select(table.c[column]).where(table.c[column].in_(values))).all()
        if found:
            findings.append(f"{name}: {column} {sorted(row[0] for row in found)}")
    for name, keys in EXPECTED_DEMO_KEYS.items():
        found = _pk_sets_of(conn, name) & keys
        if found:
            findings.append(f"{name}: {len(found)} записей с ключами seed")
    natural = [
        ("categories", "slug", {c.slug for c in data.CATEGORIES}),
        ("products", "slug", {p.slug for p in data.PRODUCTS}),
        ("product_variants", "sku", {v.sku for p in data.PRODUCTS for v in p.variants}),
    ]
    for name, column, values in natural:
        table = _table(name)
        found = conn.execute(select(table.c[column]).where(table.c[column].in_(values))).all()
        if found:
            findings.append(f"{name}: {column} {sorted(row[0] for row in found)}")
    zones = _table("delivery_zones")
    overlapping = conn.execute(
        select(zones.c.id).where(
            zones.c.is_active.is_(True),
            zones.c.boundary.is_not(None),
            func.ST_Relate(
                zones.c.boundary,
                func.ST_GeomFromText(data.DEMO_ZONE.boundary_wkt, data.DEMO_ZONE.srid),
                "T********",
            ),
        )
    ).all()
    if overlapping:
        findings.append(f"delivery_zones: активные зоны пересекают демо-зону {overlapping}")
    return findings


def _pk_sets_of(conn: Connection, name: str) -> set[Key]:
    return {tuple(row) for row in conn.execute(select(*_table(name).primary_key.columns))}


# --- CLI ----------------------------------------------------------------------------


def _run_cli(mode: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DATABASE_URL": TEST_DATABASE_URL or ""}
    return subprocess.run(  # noqa: S603 - fixed command, no user input
        [sys.executable, "-m", "app.seeds", mode],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )


def _report(result: subprocess.CompletedProcess[str]) -> dict[str, tuple[int, int]]:
    return {
        table: (int(created), int(existing))
        for table, created, existing in REPORT_LINE.findall(result.stdout)
    }


def _assert_run(
    result: subprocess.CompletedProcess[str], db_name: str, code: int
) -> dict[str, tuple[int, int]]:
    details = f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert result.returncode == code, details
    assert f"База данных: {db_name}" in result.stdout, details
    return _report(result)


# --- Cleanup ------------------------------------------------------------------------


def _delete_order() -> list[str]:
    return [table.name for table in reversed(Base.metadata.sorted_tables) if table.name in TOUCHED]


def _metadata_fks() -> set[tuple[str, str, str, str]]:
    return {
        (table.name, fk.parent.name, fk.column.table.name, fk.column.name)
        for table in Base.metadata.tables.values()
        for fk in table.foreign_keys
    }


def _database_fks(conn: Connection) -> set[tuple[str, str, str, str]]:
    rows = conn.execute(
        text(
            "SELECT cl.relname, a.attname, fcl.relname, fa.attname "
            "FROM pg_constraint c "
            "JOIN pg_class cl ON cl.oid = c.conrelid "
            "JOIN pg_namespace n ON n.oid = cl.relnamespace "
            "JOIN pg_class fcl ON fcl.oid = c.confrelid "
            "JOIN LATERAL unnest(c.conkey, c.confkey) AS k(attnum, fattnum) ON true "
            "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum "
            "JOIN pg_attribute fa ON fa.attrelid = c.confrelid AND fa.attnum = k.fattnum "
            "WHERE c.contype = 'f' AND n.nspname = 'public'"
        )
    )
    return {tuple(row) for row in rows}


def _cleanup_problems(
    conn: Connection, created: dict[str, set[Key]], order: list[str]
) -> list[str]:
    """Every safety check; runs before the first DELETE (SELECT only)."""
    problems: list[str] = []

    # 1. Ownership: every created key must be a seed key.
    for name, keys in created.items():
        if not keys:
            continue
        if name in BASE_NATURAL_KEYS:
            column, allowed = BASE_NATURAL_KEYS[name]
            table = _table(name)
            pk = table.primary_key.columns.values()[0]
            values = conn.execute(
                select(table.c[column]).where(pk.in_([key[0] for key in keys]))
            ).all()
            foreign = [row[0] for row in values if row[0] not in allowed]
            if foreign or len(values) != len(keys):
                problems.append(f"{name}: созданы не seed-записи {foreign}")
        elif keys - EXPECTED_DEMO_KEYS[name]:
            problems.append(
                f"{name}: созданы записи вне ключей seed: {keys - EXPECTED_DEMO_KEYS[name]}"
            )

    # 2. FK set of the real database equals Base.metadata.
    metadata_fks = _metadata_fks()
    database_fks = _database_fks(conn)
    if metadata_fks != database_fks:
        problems.append(
            "FK в db-test не совпадают с Base.metadata: "
            f"только в БД {database_fks - metadata_fks}, только в моделях "
            f"{metadata_fks - database_fks}"
        )

    # 3. Delete order: every child of an FK between touched tables comes first.
    position = {name: index for index, name in enumerate(order)}
    if sorted(order) != sorted(TOUCHED):
        problems.append(f"порядок удаления покрывает не все 17 таблиц: {order}")
    for child, _, parent, _ in metadata_fks:
        if child in position and parent in position and child != parent:
            if position[child] >= position[parent]:
                problems.append(f"порядок удаления: {child} должна идти раньше {parent}")
        elif child == parent and child in position:
            problems.append(f"циклический FK в таблице {child}")

    # 4. External references to created rows (all FKs from Base.metadata).
    for table in Base.metadata.tables.values():
        for fk in table.foreign_keys:
            target = fk.column.table
            keys = created.get(target.name)
            if not keys:
                continue
            target_pk = list(target.primary_key.columns)
            if len(target_pk) != 1 or target_pk[0].name != fk.column.name:
                problems.append(
                    f"FK {table.name}.{fk.parent.name} ссылается не на PK {target.name}"
                )
                continue
            referring = {
                tuple(row)
                for row in conn.execute(
                    select(*table.primary_key.columns).where(
                        fk.parent.in_([key[0] for key in keys])
                    )
                )
            }
            outside = referring - created.get(table.name, set())
            if outside:
                problems.append(
                    f"внешние ссылки {table.name}.{fk.parent.name} -> {target.name}: "
                    f"{len(outside)} строк"
                )

    # 5. Every created key still exists exactly once.
    for name, keys in created.items():
        if keys and _select_keys(conn, name, keys) != keys:
            problems.append(f"{name}: найдено не столько строк, сколько создано")
    return problems


def _key_filter(table: Table, keys: set[Key]) -> Any:
    columns = list(table.primary_key.columns)
    if len(columns) == 1:
        return columns[0].in_([key[0] for key in keys])
    return tuple_(*columns).in_(list(keys))


def _select_keys(conn: Connection, name: str, keys: set[Key]) -> set[Key]:
    table = _table(name)
    query = select(*table.primary_key.columns).where(_key_filter(table, keys))
    return {tuple(row) for row in conn.execute(query)}


def _cleanup(engine: Engine, before_pks: dict[str, set[Key]]) -> None:
    order = _delete_order()
    with engine.begin() as conn:  # one transaction: any exception rolls it back
        current = _pk_sets(conn)
        created = {name: current[name] - before_pks[name] for name in TOUCHED}
        problems = _cleanup_problems(conn, created, order)
        if problems:
            raise AssertionError("очистка не начата, ничего не удалено:\n" + "\n".join(problems))
        for name in order:
            keys = created[name]
            if not keys:
                continue
            table = _table(name)
            deleted = conn.execute(delete(table).where(_key_filter(table, keys))).rowcount
            if deleted != len(keys):
                raise AssertionError(
                    f"{name}: удалено {deleted} строк вместо {len(keys)}; очистка откатывается"
                )


# --- The smoke test -----------------------------------------------------------------


def test_seed_cli_smoke(sync_engine: Engine) -> None:
    db_name = _assert_isolation(sync_engine)
    with sync_engine.connect() as conn:
        findings = _findings_before_run(conn)
        if findings:
            pytest.fail(
                "db-test не чиста, CLI не запускался, ничего не удалено:\n" + "\n".join(findings)
            )
        before_rows = _rows_snapshot(conn)
        before_pks = _pk_sets(conn)

    try:
        # demo before base: error kind 1, full rollback.
        result = _run_cli("demo")
        _assert_run(result, db_name, 1)
        assert "требует выполненного base" in result.stderr
        with sync_engine.connect() as conn:
            assert _pk_sets(conn) == before_pks

        report = _assert_run(_run_cli("base"), db_name, 0)
        assert {name: created for name, (created, _) in report.items()} == BASE_CREATED

        report = _assert_run(_run_cli("base"), db_name, 0)
        assert report == {name: (0, count) for name, count in BASE_CREATED.items()}

        report = _assert_run(_run_cli("demo"), db_name, 0)
        assert {name: created for name, (created, _) in report.items()} == DEMO_CREATED

        report = _assert_run(_run_cli("demo"), db_name, 0)
        assert report == {name: (0, count) for name, count in DEMO_CREATED.items()}

        with sync_engine.connect() as conn:
            after = _pk_sets(conn)
        created = {name: after[name] - before_pks[name] for name in TOUCHED}
        assert {name: len(created[name]) for name in TOUCHED} == {
            **BASE_CREATED,
            **DEMO_CREATED,
        }
        for name in DEMO_TABLES:
            assert created[name] == EXPECTED_DEMO_KEYS[name], name
    finally:
        _cleanup(sync_engine, before_pks)
        with sync_engine.connect() as conn:
            assert _rows_snapshot(conn) == before_rows
            assert _pk_sets(conn) == before_pks
