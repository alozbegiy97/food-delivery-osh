"""Cart schema on the isolated test database (DATABASE_SCHEMA.md §6, DEC-130).

Each test runs inside a rolled-back transaction (`db_session`).
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError, InvalidRequestError
from sqlalchemy.orm import Session, selectinload

from app.modules.cart.models import Cart, CartItem, CartItemModifier
from app.modules.catalog.enums import SelectionType
from app.modules.catalog.models import Category, Modifier, ModifierGroup, Product, ProductVariant
from app.modules.users.models import User

pytestmark = pytest.mark.db

TABLES = ("carts", "cart_items", "cart_item_modifiers")


# --------------------------------------------------------------------------- helpers


def _add(session: Session, *objects: object) -> None:
    session.add_all(objects)
    session.flush()


def _expect_integrity_error(session: Session, *objects: object) -> None:
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add_all(objects)
        session.flush()


def _expect_sql_error(session: Session, sql: str, **params: object) -> None:
    with pytest.raises(IntegrityError), session.begin_nested():
        session.execute(text(sql), params)


def _delete(session: Session, table: str, row_id: uuid.UUID) -> None:
    session.execute(text(f"DELETE FROM {table} WHERE id = :id"), {"id": row_id})  # noqa: S608


def _count(session: Session, table: str, column: str, value: object) -> int:
    return session.execute(
        text(f"SELECT count(*) FROM {table} WHERE {column} = :v"),  # noqa: S608 - test literals
        {"v": value},
    ).scalar_one()


class Fixture:
    """A user, a product with a variant and a modifier — enough for a cart line."""

    def __init__(self, session: Session, suffix: str = "") -> None:
        self.user = User(email=f"cart{suffix}@example.kg", password_hash="h", full_name="Buyer")
        self.category = Category(slug=f"pizza{suffix}")
        _add(session, self.user, self.category)
        self.product = Product(category_id=self.category.id, slug=f"margherita{suffix}")
        self.group = ModifierGroup(selection_type=SelectionType.MULTIPLE)
        _add(session, self.product, self.group)
        self.variant = ProductVariant(
            product_id=self.product.id, sku=f"SKU{suffix}", price=Decimal("450.00")
        )
        self.modifier = Modifier(group_id=self.group.id, max_quantity=3)
        _add(session, self.variant, self.modifier)

    def cart(self, session: Session) -> Cart:
        cart = Cart(user_id=self.user.id)
        _add(session, cart)
        return cart

    def item(self, session: Session, cart: Cart, quantity: int = 1) -> CartItem:
        item = CartItem(
            cart_id=cart.id,
            product_id=self.product.id,
            variant_id=self.variant.id,
            quantity=quantity,
        )
        _add(session, item)
        return item


@pytest.fixture
def data(db_session: Session) -> Fixture:
    return Fixture(db_session)


# --------------------------------------------------------------------------- structure

EXPECTED_COLUMNS = {
    "carts": {"id": False, "user_id": False, "created_at": False, "updated_at": False},
    "cart_items": {
        "id": False, "cart_id": False, "product_id": False, "variant_id": False,
        "quantity": False, "special_instructions": True, "created_at": False,
        "updated_at": False,
    },
    "cart_item_modifiers": {
        "id": False, "cart_item_id": False, "modifier_id": False, "quantity": False,
    },
}  # fmt: skip


@pytest.mark.parametrize("table", TABLES)
def test_columns_and_nullability(db_session: Session, table: str) -> None:
    columns = {
        column["name"]: column["nullable"]
        for column in inspect(db_session.connection()).get_columns(table)
    }
    assert columns == EXPECTED_COLUMNS[table]


def test_column_types_and_no_stored_prices(db_session: Session) -> None:
    rows = db_session.execute(
        text(
            "SELECT table_name || '.' || column_name, udt_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = ANY(:tables)"
        ),
        {"tables": list(TABLES)},
    ).all()
    types = dict(rows)
    assert types["cart_items.quantity"] == "int4"
    assert types["cart_item_modifiers.quantity"] == "int2"
    assert types["cart_items.special_instructions"] == "text"
    for column in ("carts.user_id", "cart_items.cart_id", "cart_items.product_id",
                   "cart_items.variant_id", "cart_item_modifiers.modifier_id"):  # fmt: skip
        assert types[column] == "uuid"
    assert types["carts.created_at"] == "timestamptz"
    # The cart never stores prices: they are recalculated by the server (§6.2, DEC-08).
    assert "numeric" not in types.values()


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
    assert names == {
        "pk_carts",
        "uq_carts_user_id",
        "fk_carts_user_id_users",
        "pk_cart_items",
        "ck_cart_items_quantity_positive",
        "fk_cart_items_cart_id_carts",
        "fk_cart_items_product_id_products",
        "fk_cart_items_variant_id_product_variants",
        "pk_cart_item_modifiers",
        "uq_cart_item_modifiers_cart_item_id_modifier_id",
        "ck_cart_item_modifiers_quantity_positive",
        "fk_cart_item_modifiers_cart_item_id_cart_items",
        "fk_cart_item_modifiers_modifier_id_modifiers",
    }


def test_foreign_keys_and_delete_rules(db_session: Session) -> None:
    rows = db_session.execute(
        text(
            "SELECT conrelid::regclass::text, confrelid::regclass::text, confdeltype "
            "FROM pg_constraint WHERE contype = 'f' AND conrelid::regclass::text = ANY(:tables)"
        ),
        {"tables": list(TABLES)},
    ).all()
    # c = CASCADE, r = RESTRICT (DATABASE_SCHEMA.md §6)
    assert {(table, target): rule for table, target, rule in rows} == {
        ("carts", "users"): "c",
        ("cart_items", "carts"): "c",
        ("cart_items", "products"): "r",
        ("cart_items", "product_variants"): "r",
        ("cart_item_modifiers", "cart_items"): "c",
        ("cart_item_modifiers", "modifiers"): "r",
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
    assert indexes == {
        "uq_carts_user_id": (
            "CREATE UNIQUE INDEX uq_carts_user_id ON public.carts USING btree (user_id)"
        ),
        "ix_cart_items_cart_id": (
            "CREATE INDEX ix_cart_items_cart_id ON public.cart_items USING btree (cart_id)"
        ),
        "ix_cart_items_product_id": (
            "CREATE INDEX ix_cart_items_product_id ON public.cart_items USING btree (product_id)"
        ),
        "ix_cart_items_variant_id": (
            "CREATE INDEX ix_cart_items_variant_id ON public.cart_items USING btree (variant_id)"
        ),
        "uq_cart_item_modifiers_cart_item_id_modifier_id": (
            "CREATE UNIQUE INDEX uq_cart_item_modifiers_cart_item_id_modifier_id "
            "ON public.cart_item_modifiers USING btree (cart_item_id, modifier_id)"
        ),
        "ix_cart_item_modifiers_modifier_id": (
            "CREATE INDEX ix_cart_item_modifiers_modifier_id "
            "ON public.cart_item_modifiers USING btree (modifier_id)"
        ),
    }


# --------------------------------------------------------------------------- carts


def test_one_cart_per_user(db_session: Session, data: Fixture) -> None:
    cart = data.cart(db_session)
    db_session.refresh(cart)
    assert isinstance(cart.id, uuid.UUID)
    assert cart.created_at.tzinfo is not None
    assert cart.updated_at.tzinfo is not None
    _expect_integrity_error(db_session, Cart(user_id=data.user.id))
    # Another user may have their own cart.
    other = Fixture(db_session, suffix="-2")
    other.cart(db_session)


def test_cart_requires_existing_user(db_session: Session) -> None:
    _expect_integrity_error(db_session, Cart(user_id=uuid.uuid4()))
    _expect_sql_error(db_session, "INSERT INTO carts (user_id) VALUES (NULL)")


def test_deleting_user_removes_cart_items_and_modifiers(db_session: Session, data: Fixture) -> None:
    cart = data.cart(db_session)
    item = data.item(db_session, cart)
    _add(db_session, CartItemModifier(cart_item_id=item.id, modifier_id=data.modifier.id))

    _delete(db_session, "users", data.user.id)

    assert _count(db_session, "carts", "id", cart.id) == 0
    assert _count(db_session, "cart_items", "cart_id", cart.id) == 0
    assert _count(db_session, "cart_item_modifiers", "cart_item_id", item.id) == 0
    # Catalog rows are untouched.
    assert _count(db_session, "product_variants", "id", data.variant.id) == 1


def test_clearing_cart_keeps_the_cart_row(db_session: Session, data: Fixture) -> None:
    """Checkout clears items but keeps and reuses the cart row (§6.1)."""
    cart = data.cart(db_session)
    item = data.item(db_session, cart)
    _add(db_session, CartItemModifier(cart_item_id=item.id, modifier_id=data.modifier.id))

    db_session.execute(text("DELETE FROM cart_items WHERE cart_id = :id"), {"id": cart.id})

    assert _count(db_session, "carts", "id", cart.id) == 1
    assert _count(db_session, "cart_item_modifiers", "cart_item_id", item.id) == 0


# --------------------------------------------------------------------------- cart items


def test_item_defaults_and_quantity_check(db_session: Session, data: Fixture) -> None:
    cart = data.cart(db_session)
    item = data.item(db_session, cart, quantity=2)
    db_session.refresh(item)
    assert item.quantity == 2
    assert item.special_instructions is None
    assert item.created_at.tzinfo is not None

    for quantity in (0, -1):
        _expect_integrity_error(
            db_session,
            CartItem(
                cart_id=cart.id,
                product_id=data.product.id,
                variant_id=data.variant.id,
                quantity=quantity,
            ),
        )


@pytest.mark.parametrize("column", ["cart_id", "product_id", "variant_id", "quantity"])
def test_item_required_columns(db_session: Session, data: Fixture, column: str) -> None:
    cart = data.cart(db_session)
    values: dict[str, object] = {
        "cart_id": cart.id,
        "product_id": data.product.id,
        "variant_id": data.variant.id,
        "quantity": 1,
    }
    values[column] = None
    _expect_sql_error(
        db_session,
        "INSERT INTO cart_items (cart_id, product_id, variant_id, quantity) "
        "VALUES (:cart_id, :product_id, :variant_id, :quantity)",
        **values,
    )


def test_identical_lines_are_not_blocked_by_the_schema(db_session: Session, data: Fixture) -> None:
    """Merging identical lines is a service rule (DEC-11), not a DB constraint."""
    cart = data.cart(db_session)
    data.item(db_session, cart)
    data.item(db_session, cart)
    assert _count(db_session, "cart_items", "cart_id", cart.id) == 2


def test_catalog_rows_in_a_cart_cannot_be_deleted(db_session: Session, data: Fixture) -> None:
    cart = data.cart(db_session)
    data.item(db_session, cart)
    _expect_sql_error(db_session, "DELETE FROM product_variants WHERE id = :id", id=data.variant.id)
    _expect_sql_error(db_session, "DELETE FROM products WHERE id = :id", id=data.product.id)
    # Soft delete of the product stays possible (DEC-26).
    db_session.execute(
        text("UPDATE products SET deleted_at = now() WHERE id = :id"), {"id": data.product.id}
    )


# --------------------------------------------------------------------------- item modifiers


def test_item_modifier_defaults_checks_and_uniqueness(db_session: Session, data: Fixture) -> None:
    item = data.item(db_session, data.cart(db_session))
    link = CartItemModifier(cart_item_id=item.id, modifier_id=data.modifier.id)
    _add(db_session, link)
    db_session.refresh(link)
    assert link.quantity == 1

    _expect_integrity_error(
        db_session, CartItemModifier(cart_item_id=item.id, modifier_id=data.modifier.id)
    )
    other = Modifier(group_id=data.group.id)
    _add(db_session, other)
    for quantity in (0, -2):
        _expect_integrity_error(
            db_session,
            CartItemModifier(cart_item_id=item.id, modifier_id=other.id, quantity=quantity),
        )
    # Upper bound (max_quantity) is a service rule (§6.3), not a DB constraint.
    _add(db_session, CartItemModifier(cart_item_id=item.id, modifier_id=other.id, quantity=5))


def test_modifier_in_a_cart_cannot_be_deleted(db_session: Session, data: Fixture) -> None:
    item = data.item(db_session, data.cart(db_session))
    _add(db_session, CartItemModifier(cart_item_id=item.id, modifier_id=data.modifier.id))
    _expect_sql_error(db_session, "DELETE FROM modifiers WHERE id = :id", id=data.modifier.id)
    # Deleting its group would cascade to the modifier and is blocked as well.
    _expect_sql_error(db_session, "DELETE FROM modifier_groups WHERE id = :id", id=data.group.id)


def test_deleting_item_removes_its_modifiers(db_session: Session, data: Fixture) -> None:
    item = data.item(db_session, data.cart(db_session))
    _add(db_session, CartItemModifier(cart_item_id=item.id, modifier_id=data.modifier.id))
    _delete(db_session, "cart_items", item.id)
    assert _count(db_session, "cart_item_modifiers", "cart_item_id", item.id) == 0
    assert _count(db_session, "modifiers", "id", data.modifier.id) == 1


# --------------------------------------------------------------------------- relationships


def test_relationships_require_explicit_loading(db_session: Session, data: Fixture) -> None:
    cart = data.cart(db_session)
    item = data.item(db_session, cart, quantity=3)
    _add(db_session, CartItemModifier(cart_item_id=item.id, modifier_id=data.modifier.id))
    db_session.expunge_all()

    lazy = db_session.get(Cart, cart.id)
    assert lazy is not None
    with pytest.raises(InvalidRequestError, match="lazy='raise'"):
        _ = lazy.items
    db_session.expunge_all()

    loaded = db_session.scalars(
        select(Cart)
        .where(Cart.id == cart.id)
        .options(selectinload(Cart.items).selectinload(CartItem.modifiers))
    ).one()
    assert [i.quantity for i in loaded.items] == [3]
    assert [m.modifier_id for m in loaded.items[0].modifiers] == [data.modifier.id]
