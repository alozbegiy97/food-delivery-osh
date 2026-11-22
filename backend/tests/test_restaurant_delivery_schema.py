"""Restaurant, payment methods and delivery zones schema on db-test.

DATABASE_SCHEMA.md §8.1, §9.1, §10.1, §10.2; DEC-107, DEC-116, DEC-122.
Each test runs inside a rolled-back transaction (`db_session`). Values used
below (300.00, 100.00, 500.00, 10:00–23:00, demo contacts) only check that
the schema accepts the approved demo data; the real rows come from seed.
"""

from datetime import UTC, datetime, time
from decimal import Decimal

import pytest
from geoalchemy2 import WKTElement
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.modules.delivery.models import DeliveryZone
from app.modules.payments.enums import PaymentMethodCode
from app.modules.payments.models import PaymentMethod
from app.modules.restaurant.models import RestaurantSettings, RestaurantWorkingHours

pytestmark = pytest.mark.db

TABLES = ("restaurant_settings", "restaurant_working_hours", "payment_methods", "delivery_zones")

# Demo-like zone in Osh: a single valid square, lon/lat order (SRID 4326).
OSH_SQUARE = "MULTIPOLYGON(((72.76 40.50, 72.84 40.50, 72.84 40.55, 72.76 40.55, 72.76 40.50)))"
# Self-intersecting "bow tie": syntactically fine, but ST_IsValid() is false.
BOW_TIE = "MULTIPOLYGON(((0 0, 1 1, 1 0, 0 1, 0 0)))"


def _expect_integrity_error(session: Session, *objects: object) -> None:
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add_all(objects)
        session.flush()


def _expect_db_error(session: Session, sql: str, **params: object) -> str:
    with pytest.raises(DBAPIError) as excinfo, session.begin_nested():
        session.execute(text(sql), params)
    return str(excinfo.value.orig)


def _zone(**values: object) -> DeliveryZone:
    defaults: dict[str, object] = {"name": "Демо-зона", "delivery_fee": Decimal("100.00")}
    return DeliveryZone(**(defaults | values))


# --------------------------------------------------------------------------- structure

EXPECTED_COLUMNS = {
    "restaurant_settings": {
        "id": False, "restaurant_name": False, "phone": True, "address": True,
        "latitude": True, "longitude": True, "min_order_amount": False,
        "delivery_enabled": False, "pickup_enabled": False, "timezone": False,
        "updated_at": False,
    },
    "restaurant_working_hours": {
        "id": False, "weekday": False, "opens_at": True, "closes_at": True, "is_closed": False,
    },
    "payment_methods": {
        "id": False, "code": False, "is_active": False, "sort_order": False, "created_at": False,
    },
    "delivery_zones": {
        "id": False, "name": False, "description": True, "delivery_fee": False,
        "min_order_amount": False, "is_active": False, "boundary": True,
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


def test_column_types(db_session: Session) -> None:
    rows = db_session.execute(
        text(
            "SELECT table_name || '.' || column_name, data_type, udt_name, "
            "character_maximum_length, numeric_precision, numeric_scale "
            "FROM information_schema.columns WHERE table_schema = 'public' "
            "AND table_name IN ('restaurant_settings', 'restaurant_working_hours', "
            "'payment_methods', 'delivery_zones')"
        )
    ).all()
    types = {name: rest for name, *rest in rows}
    assert types["restaurant_settings.id"][1] == "int2"
    assert types["restaurant_settings.restaurant_name"][2] == 180
    assert types["restaurant_settings.latitude"][3:] == [10, 7]
    assert types["restaurant_settings.min_order_amount"][3:] == [12, 2]
    assert types["restaurant_settings.timezone"][2] == 64
    assert types["restaurant_settings.updated_at"][0] == "timestamp with time zone"
    assert types["restaurant_working_hours.weekday"][1] == "int2"
    assert types["restaurant_working_hours.opens_at"][0] == "time without time zone"
    assert types["payment_methods.code"][2] == 30
    assert types["payment_methods.sort_order"][1] == "int4"
    assert types["delivery_zones.delivery_fee"][3:] == [12, 2]
    assert types["delivery_zones.min_order_amount"][3:] == [12, 2]
    assert types["delivery_zones.boundary"][1] == "geometry"


def test_boundary_is_multipolygon_srid_4326(db_session: Session) -> None:
    row = db_session.execute(
        text(
            "SELECT type, srid, coord_dimension FROM geometry_columns "
            "WHERE f_table_name = 'delivery_zones' AND f_geometry_column = 'boundary'"
        )
    ).one()
    assert tuple(row) == ("MULTIPOLYGON", 4326, 2)


def test_constraints(db_session: Session) -> None:
    rows = db_session.execute(
        text(
            "SELECT conrelid::regclass::text, contype, conname, pg_get_constraintdef(oid) "
            "FROM pg_constraint WHERE connamespace = 'public'::regnamespace "
            "AND conrelid::regclass::text = ANY(:tables)"
        ),
        {"tables": list(TABLES)},
    ).all()
    by_name = {name: (table, kind, definition) for table, kind, name, definition in rows}
    assert set(by_name) == {
        "pk_restaurant_settings",
        "ck_restaurant_settings_singleton",
        "ck_restaurant_settings_min_order_amount_non_negative",
        "pk_restaurant_working_hours",
        "uq_restaurant_working_hours_weekday",
        "ck_restaurant_working_hours_weekday_range",
        "ck_restaurant_working_hours_open_day_interval",
        "pk_payment_methods",
        "uq_payment_methods_code",
        "pk_delivery_zones",
        "ck_delivery_zones_delivery_fee_non_negative",
        "ck_delivery_zones_min_order_amount_non_negative",
        "ck_delivery_zones_active_requires_boundary",
        "ck_delivery_zones_boundary_valid",
    }
    # These four tables have no foreign keys (DATABASE_SCHEMA.md §8.1–§10.2).
    assert not [name for name, (_, kind, _) in by_name.items() if kind == "f"]
    assert "st_isvalid(boundary)" in by_name["ck_delivery_zones_boundary_valid"][2].lower()


def test_indexes(db_session: Session) -> None:
    indexes = dict(
        db_session.execute(
            text(
                "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' "
                "AND tablename = ANY(:tables)"
            ),
            {"tables": list(TABLES)},
        ).all()
    )
    assert indexes["ix_delivery_zones_boundary"] == (
        "CREATE INDEX ix_delivery_zones_boundary ON public.delivery_zones USING gist (boundary)"
    )
    assert "UNIQUE INDEX" in indexes["uq_restaurant_working_hours_weekday"]
    assert "UNIQUE INDEX" in indexes["uq_payment_methods_code"]
    # Only the explicit GIST index exists on boundary (no duplicate auto index).
    assert [name for name, ddl in indexes.items() if "boundary" in ddl] == [
        "ix_delivery_zones_boundary"
    ]


# --------------------------------------------------------------------------- restaurant_settings


def test_settings_defaults_and_demo_values(db_session: Session) -> None:
    settings = RestaurantSettings(id=1, restaurant_name="Demo Restaurant — Osh")
    db_session.add(settings)
    db_session.flush()
    db_session.refresh(settings)
    assert settings.min_order_amount == Decimal("0.00")
    assert settings.delivery_enabled is True
    assert settings.pickup_enabled is True
    assert settings.timezone == "Asia/Bishkek"
    assert settings.updated_at.tzinfo is not None

    # The approved demo values fit the schema (inserted later by seed).
    settings.min_order_amount = Decimal("300.00")
    settings.phone = "+996000000000"
    settings.address = "Демонстрационный адрес, г. Ош"
    db_session.flush()
    db_session.refresh(settings)
    assert settings.min_order_amount == Decimal("300.00")
    assert settings.address == "Демонстрационный адрес, г. Ош"


def test_settings_is_a_singleton(db_session: Session) -> None:
    db_session.add(RestaurantSettings(id=1, restaurant_name="Demo"))
    db_session.flush()
    _expect_integrity_error(db_session, RestaurantSettings(id=2, restaurant_name="Second"))
    _expect_integrity_error(db_session, RestaurantSettings(id=1, restaurant_name="Duplicate"))


def test_settings_checks(db_session: Session) -> None:
    _expect_integrity_error(
        db_session,
        RestaurantSettings(id=1, restaurant_name="Demo", min_order_amount=Decimal("-0.01")),
    )
    _expect_integrity_error(db_session, RestaurantSettings(id=1, restaurant_name=None))


def test_settings_updated_at_is_refreshed(db_session: Session) -> None:
    settings = RestaurantSettings(id=1, restaurant_name="Demo")
    db_session.add(settings)
    db_session.flush()
    old = datetime(2020, 1, 1, tzinfo=UTC)
    db_session.execute(text("UPDATE restaurant_settings SET updated_at = :old"), {"old": old})
    db_session.refresh(settings)
    settings.pickup_enabled = False
    db_session.flush()
    db_session.refresh(settings)
    assert settings.updated_at > old


# --------------------------------------------------------------------------- working hours


def test_working_hours_daily_10_to_23(db_session: Session) -> None:
    db_session.add_all(
        RestaurantWorkingHours(weekday=day, opens_at=time(10), closes_at=time(23))
        for day in range(7)
    )
    db_session.flush()
    count = db_session.execute(text("SELECT count(*) FROM restaurant_working_hours")).scalar_one()
    assert count == 7


@pytest.mark.parametrize("weekday", [-1, 7])
def test_weekday_out_of_range_is_rejected(db_session: Session, weekday: int) -> None:
    _expect_integrity_error(
        db_session, RestaurantWorkingHours(weekday=weekday, opens_at=time(10), closes_at=time(23))
    )


def test_one_interval_per_weekday(db_session: Session) -> None:
    db_session.add(RestaurantWorkingHours(weekday=0, opens_at=time(10), closes_at=time(23)))
    db_session.flush()
    _expect_integrity_error(
        db_session, RestaurantWorkingHours(weekday=0, opens_at=time(12), closes_at=time(20))
    )


@pytest.mark.parametrize(
    ("opens_at", "closes_at"),
    [(None, None), (time(10), None), (None, time(23)), (time(10), time(10))],
)
def test_open_day_requires_distinct_times(
    db_session: Session, opens_at: time | None, closes_at: time | None
) -> None:
    _expect_integrity_error(
        db_session, RestaurantWorkingHours(weekday=1, opens_at=opens_at, closes_at=closes_at)
    )


def test_closed_day_and_overnight_interval_are_allowed(db_session: Session) -> None:
    db_session.add_all(
        [
            RestaurantWorkingHours(weekday=5, is_closed=True),
            # Overnight interval (DEC-21): allowed by the schema, semantics in service.
            RestaurantWorkingHours(weekday=4, opens_at=time(22), closes_at=time(2)),
        ]
    )
    db_session.flush()


# --------------------------------------------------------------------------- payment methods


def test_payment_methods_codes_defaults_and_uniqueness(db_session: Session) -> None:
    methods = [PaymentMethod(code=code) for code in PaymentMethodCode]
    db_session.add_all(methods)
    db_session.flush()
    for method in methods:
        db_session.refresh(method)
        assert method.is_active is True
        assert method.sort_order == 0
        assert method.created_at.tzinfo is not None
    _expect_integrity_error(db_session, PaymentMethod(code=PaymentMethodCode.CASH))


# --------------------------------------------------------------------------- delivery zones


def test_demo_like_zone_is_accepted(db_session: Session) -> None:
    zone = _zone(
        name="Демонстрационная зона — Ош",
        min_order_amount=Decimal("500.00"),
        boundary=WKTElement(OSH_SQUARE, srid=4326),
    )
    db_session.add(zone)
    db_session.flush()
    db_session.refresh(zone)
    assert zone.delivery_fee == Decimal("100.00")
    assert zone.min_order_amount == Decimal("500.00")

    srid, kind, valid, covers_inside, covers_outside = db_session.execute(
        text(
            "SELECT ST_SRID(boundary), GeometryType(boundary), ST_IsValid(boundary), "
            "ST_Covers(boundary, ST_SetSRID(ST_MakePoint(72.80, 40.52), 4326)), "
            "ST_Covers(boundary, ST_SetSRID(ST_MakePoint(73.00, 40.52), 4326)) "
            "FROM delivery_zones WHERE id = :id"
        ),
        {"id": zone.id},
    ).one()
    assert (srid, kind, valid) == (4326, "MULTIPOLYGON", True)
    assert covers_inside is True
    assert covers_outside is False


def test_zone_defaults(db_session: Session) -> None:
    zone = _zone(is_active=False)
    db_session.add(zone)
    db_session.flush()
    db_session.refresh(zone)
    assert zone.min_order_amount == Decimal("0.00")
    assert zone.boundary is None
    assert zone.created_at.tzinfo is not None


def test_active_zone_requires_boundary(db_session: Session) -> None:
    # Default is_active = TRUE, boundary NULL -> rejected (D5).
    _expect_integrity_error(db_session, _zone())
    # Inactive zone without boundary is allowed (DEC-122: NULL is valid).
    db_session.add(_zone(is_active=False))
    db_session.flush()


def test_invalid_geometry_is_rejected(db_session: Session) -> None:
    _expect_integrity_error(
        db_session, _zone(is_active=False, boundary=WKTElement(BOW_TIE, srid=4326))
    )


def test_wrong_srid_is_rejected(db_session: Session) -> None:
    message = _expect_db_error(
        db_session,
        "INSERT INTO delivery_zones (name, delivery_fee, boundary) VALUES "
        "('z', 100, ST_GeomFromText(:wkt, 3857))",
        wkt=OSH_SQUARE,
    )
    assert "SRID" in message


@pytest.mark.parametrize("wkt", ["POINT(72.8 40.52)", "LINESTRING(0 0, 1 1)", "MULTIPOINT((0 0))"])
def test_non_polygon_geometry_is_rejected(db_session: Session, wkt: str) -> None:
    message = _expect_db_error(
        db_session,
        "INSERT INTO delivery_zones (name, delivery_fee, is_active, boundary) VALUES "
        "('z', 100, false, ST_GeomFromText(:wkt, 4326))",
        wkt=wkt,
    )
    assert "does not match column type (MultiPolygon)" in message


def test_single_polygon_is_stored_as_multipolygon(db_session: Session) -> None:
    """PostGIS 3.6 promotes a Polygon to MultiPolygon for this column type."""
    kind = db_session.execute(
        text(
            "INSERT INTO delivery_zones (name, delivery_fee, is_active, boundary) VALUES "
            "('z', 100, false, ST_GeomFromText('POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))', 4326)) "
            "RETURNING GeometryType(boundary)"
        )
    ).scalar_one()
    assert kind == "MULTIPOLYGON"


@pytest.mark.parametrize("field", ["delivery_fee", "min_order_amount"])
def test_negative_money_is_rejected(db_session: Session, field: str) -> None:
    _expect_integrity_error(db_session, _zone(is_active=False, **{field: Decimal("-1.00")}))


def test_delivery_fee_is_required(db_session: Session) -> None:
    _expect_integrity_error(db_session, DeliveryZone(name="z", is_active=False))
