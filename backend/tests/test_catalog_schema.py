"""Catalog schema on the isolated test database (DATABASE_SCHEMA.md §4, §5).

Covers columns, types, constraints, indexes, delete rules, money precision
and the strict `single` CHECK (DEC-128) / FK indexes (DEC-129).
Each test runs inside a rolled-back transaction (`db_session`).
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import DataError, IntegrityError, InvalidRequestError
from sqlalchemy.orm import Session, selectinload

from app.modules.catalog.enums import SelectionType
from app.modules.catalog.models import (
    Category,
    CategoryTranslation,
    Modifier,
    ModifierGroup,
    ModifierGroupTranslation,
    ModifierTranslation,
    Product,
    ProductImage,
    ProductModifierGroup,
    ProductTranslation,
    ProductVariant,
    ProductVariantTranslation,
    VariantModifierPrice,
)

pytestmark = pytest.mark.db

TABLES = (
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
)


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


def _category(session: Session, slug: str = "pizza") -> Category:
    category = Category(slug=slug)
    _add(session, category)
    return category


def _product(
    session: Session, slug: str = "margherita", category: Category | None = None
) -> Product:
    category = category or _category(session, f"cat-{slug}")
    product = Product(category_id=category.id, slug=slug)
    _add(session, product)
    return product


def _variant(
    session: Session, product: Product, sku: str = "SKU-1", price: str = "450.00"
) -> ProductVariant:
    variant = ProductVariant(product_id=product.id, sku=sku, price=Decimal(price))
    _add(session, variant)
    return variant


def _group(session: Session, **values: object) -> ModifierGroup:
    defaults: dict[str, object] = {"selection_type": SelectionType.MULTIPLE}
    group = ModifierGroup(**(defaults | values))
    _add(session, group)
    return group


def _modifier(session: Session, group: ModifierGroup, **values: object) -> Modifier:
    modifier = Modifier(group_id=group.id, **values)
    _add(session, modifier)
    return modifier


# --------------------------------------------------------------------------- structure

EXPECTED_COLUMNS = {
    "categories": {
        "id": False, "slug": False, "image_path": True, "sort_order": False,
        "is_active": False, "created_at": False, "updated_at": False,
    },
    "category_translations": {
        "id": False, "category_id": False, "language_code": False, "name": False,
        "description": True,
    },
    "products": {
        "id": False, "category_id": False, "slug": False, "is_available": False,
        "is_featured": False, "sort_order": False, "created_at": False,
        "updated_at": False, "deleted_at": True,
    },
    "product_translations": {
        "id": False, "product_id": False, "language_code": False, "name": False,
        "description": True,
    },
    "product_images": {
        "id": False, "product_id": False, "image_path": False, "alt_text": True,
        "sort_order": False, "is_primary": False, "created_at": False,
    },
    "product_variants": {
        "id": False, "product_id": False, "sku": False, "price": False,
        "is_available": False, "sort_order": False, "created_at": False, "updated_at": False,
    },
    "product_variant_translations": {
        "id": False, "variant_id": False, "language_code": False, "name": False,
    },
    "modifier_groups": {
        "id": False, "selection_type": False, "is_required": False, "min_selections": False,
        "max_selections": True, "is_active": False, "sort_order": False,
        "created_at": False, "updated_at": False,
    },
    "modifier_group_translations": {
        "id": False, "group_id": False, "language_code": False, "name": False,
        "description": True,
    },
    "modifiers": {
        "id": False, "group_id": False, "price_delta": False, "max_quantity": False,
        "is_available": False, "sort_order": False, "created_at": False, "updated_at": False,
    },
    "modifier_translations": {
        "id": False, "modifier_id": False, "language_code": False, "name": False,
        "description": True,
    },
    "product_modifier_groups": {"product_id": False, "group_id": False, "sort_order": False},
    "variant_modifier_prices": {"variant_id": False, "modifier_id": False, "price_delta": False},
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
            "SELECT table_name || '.' || column_name, udt_name, character_maximum_length, "
            "numeric_precision, numeric_scale FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = ANY(:tables)"
        ),
        {"tables": list(TABLES)},
    ).all()
    types = {name: tuple(rest) for name, *rest in rows}
    money = ("numeric", None, 12, 2)
    assert types["product_variants.price"] == money
    assert types["modifiers.price_delta"] == money
    assert types["variant_modifier_prices.price_delta"] == money
    assert types["categories.slug"] == ("varchar", 100, None, None)
    assert types["products.slug"] == ("varchar", 150, None, None)
    assert types["product_variants.sku"] == ("varchar", 100, None, None)
    assert types["category_translations.name"] == ("varchar", 120, None, None)
    assert types["product_translations.name"] == ("varchar", 180, None, None)
    assert types["product_variant_translations.name"] == ("varchar", 100, None, None)
    assert types["modifier_group_translations.name"] == ("varchar", 120, None, None)
    assert types["modifier_translations.name"] == ("varchar", 120, None, None)
    assert types["product_images.alt_text"] == ("varchar", 255, None, None)
    assert types["modifier_groups.selection_type"] == ("varchar", 20, None, None)
    for column in ("modifier_groups.min_selections", "modifier_groups.max_selections",
                   "modifiers.max_quantity"):  # fmt: skip
        assert types[column][0] == "int2"
    for table in TABLES:
        if f"{table}.language_code" in types:
            assert types[f"{table}.language_code"] == ("varchar", 2, None, None)
    assert types["products.deleted_at"][0] == "timestamptz"
    assert types["categories.image_path"][0] == "text"


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
        "uq_categories_slug",
        "uq_products_slug",
        "uq_product_variants_sku",
        "uq_category_translations_category_id_language_code",
        "uq_product_translations_product_id_language_code",
        "uq_product_variant_translations_variant_id_language_code",
        "uq_modifier_group_translations_group_id_language_code",
        "uq_modifier_translations_modifier_id_language_code",
        "ck_category_translations_language_code",
        "ck_product_translations_language_code",
        "ck_product_variant_translations_language_code",
        "ck_modifier_group_translations_language_code",
        "ck_modifier_translations_language_code",
        "ck_product_variants_price_non_negative",
        "ck_modifier_groups_selection_type",
        "ck_modifier_groups_min_selections_non_negative",
        "ck_modifier_groups_max_selections_positive",
        "ck_modifier_groups_min_not_greater_than_max",
        "ck_modifier_groups_single_max_one",
        "ck_modifier_groups_required_matches_min",
        "ck_modifiers_price_delta_non_negative",
        "ck_modifiers_max_quantity_positive",
        "ck_variant_modifier_prices_price_delta_non_negative",
        "fk_category_translations_category_id_categories",
        "fk_products_category_id_categories",
        "fk_product_translations_product_id_products",
        "fk_product_images_product_id_products",
        "fk_product_variants_product_id_products",
        "fk_product_variant_translations_variant_id_product_variants",
        "fk_modifier_group_translations_group_id_modifier_groups",
        "fk_modifiers_group_id_modifier_groups",
        "fk_modifier_translations_modifier_id_modifiers",
        "fk_product_modifier_groups_product_id_products",
        "fk_product_modifier_groups_group_id_modifier_groups",
        "fk_variant_modifier_prices_variant_id_product_variants",
        "fk_variant_modifier_prices_modifier_id_modifiers",
    }
    # Names longer than 63 characters would be silently truncated by PostgreSQL.
    assert all(len(name) <= 63 for name in expected)
    assert names == expected


def test_foreign_keys_and_delete_rules(db_session: Session) -> None:
    rows = db_session.execute(
        text(
            "SELECT conrelid::regclass::text, confrelid::regclass::text, confdeltype "
            "FROM pg_constraint WHERE contype = 'f' AND conrelid::regclass::text = ANY(:tables)"
        ),
        {"tables": list(TABLES)},
    ).all()
    # c = CASCADE, r = RESTRICT (DATABASE_SCHEMA.md §4–§5)
    assert {(table, target): rule for table, target, rule in rows} == {
        ("category_translations", "categories"): "c",
        ("products", "categories"): "r",
        ("product_translations", "products"): "c",
        ("product_images", "products"): "c",
        ("product_variants", "products"): "c",
        ("product_variant_translations", "product_variants"): "c",
        ("modifier_group_translations", "modifier_groups"): "c",
        ("modifiers", "modifier_groups"): "c",
        ("modifier_translations", "modifiers"): "c",
        ("product_modifier_groups", "products"): "c",
        ("product_modifier_groups", "modifier_groups"): "r",
        ("variant_modifier_prices", "product_variants"): "c",
        ("variant_modifier_prices", "modifiers"): "c",
    }


def test_indexes(db_session: Session) -> None:
    indexes = dict(
        db_session.execute(
            text(
                "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' "
                "AND tablename = ANY(:tables) AND indexname NOT LIKE 'pk\\_%' "
                "AND indexname NOT LIKE 'uq\\_%\\_language\\_code' "
                "AND indexname NOT IN ('uq_categories_slug', 'uq_products_slug', "
                "'uq_product_variants_sku')"
            ),
            {"tables": list(TABLES)},
        ).all()
    )
    assert indexes == {
        "ix_products_category_id_is_available_sort_order": (
            "CREATE INDEX ix_products_category_id_is_available_sort_order ON public.products "
            "USING btree (category_id, is_available, sort_order) WHERE (deleted_at IS NULL)"
        ),
        "ix_product_images_product_id_sort_order": (
            "CREATE INDEX ix_product_images_product_id_sort_order ON public.product_images "
            "USING btree (product_id, sort_order)"
        ),
        "uq_product_images_product_id_primary": (
            "CREATE UNIQUE INDEX uq_product_images_product_id_primary ON public.product_images "
            "USING btree (product_id) WHERE is_primary"
        ),
        "ix_product_variants_product_id": (
            "CREATE INDEX ix_product_variants_product_id ON public.product_variants "
            "USING btree (product_id)"
        ),
        "ix_modifiers_group_id": (
            "CREATE INDEX ix_modifiers_group_id ON public.modifiers USING btree (group_id)"
        ),
        "ix_product_modifier_groups_group_id": (
            "CREATE INDEX ix_product_modifier_groups_group_id ON public.product_modifier_groups "
            "USING btree (group_id)"
        ),
        "ix_variant_modifier_prices_modifier_id": (
            "CREATE INDEX ix_variant_modifier_prices_modifier_id "
            "ON public.variant_modifier_prices USING btree (modifier_id)"
        ),
    }


# --------------------------------------------------------------------------- categories


def test_category_defaults_and_unique_slug(db_session: Session) -> None:
    category = _category(db_session)
    db_session.refresh(category)
    assert isinstance(category.id, uuid.UUID)
    assert category.sort_order == 0
    assert category.is_active is True
    assert category.image_path is None
    assert category.created_at.tzinfo is not None
    _expect_integrity_error(db_session, Category(slug="pizza"))


def test_category_translations_unique_language_and_cascade(db_session: Session) -> None:
    category = _category(db_session)
    _add(
        db_session,
        *(CategoryTranslation(category_id=category.id, language_code=lang, name="Пицца")
          for lang in ("ru", "ky", "uz")),
    )  # fmt: skip
    _expect_integrity_error(
        db_session, CategoryTranslation(category_id=category.id, language_code="ru", name="X")
    )
    _expect_integrity_error(
        db_session, CategoryTranslation(category_id=category.id, language_code="en", name="X")
    )
    _delete(db_session, "categories", category.id)
    assert _count(db_session, "category_translations", "category_id", category.id) == 0


def test_category_with_products_cannot_be_deleted(db_session: Session) -> None:
    product = _product(db_session)
    _expect_sql_error(db_session, "DELETE FROM categories WHERE id = :id", id=product.category_id)


# --------------------------------------------------------------------------- products


def test_product_defaults_soft_delete_and_unique_slug(db_session: Session) -> None:
    product = _product(db_session)
    db_session.refresh(product)
    assert product.is_available is True
    assert product.is_featured is False
    assert product.sort_order == 0
    assert product.deleted_at is None
    _expect_integrity_error(db_session, Product(category_id=product.category_id, slug="margherita"))

    db_session.execute(
        text("UPDATE products SET deleted_at = now() WHERE id = :id"), {"id": product.id}
    )
    db_session.refresh(product)
    assert product.deleted_at is not None


def test_product_children_cascade(db_session: Session) -> None:
    product = _product(db_session)
    variant = _variant(db_session, product)
    group = _group(db_session)
    _add(
        db_session,
        ProductTranslation(product_id=product.id, language_code="ru", name="Маргарита"),
        ProductImage(product_id=product.id, image_path="products/a.webp", is_primary=True),
        ProductVariantTranslation(variant_id=variant.id, language_code="ru", name="30 см"),
        ProductModifierGroup(product_id=product.id, group_id=group.id),
    )
    _delete(db_session, "products", product.id)
    for table, column, value in (
        ("product_translations", "product_id", product.id),
        ("product_images", "product_id", product.id),
        ("product_variants", "product_id", product.id),
        ("product_variant_translations", "variant_id", variant.id),
        ("product_modifier_groups", "product_id", product.id),
    ):
        assert _count(db_session, table, column, value) == 0
    # The shared modifier group itself survives.
    assert _count(db_session, "modifier_groups", "id", group.id) == 1


def test_product_translations_unique_language(db_session: Session) -> None:
    product = _product(db_session)
    _add(db_session, ProductTranslation(product_id=product.id, language_code="uz", name="A"))
    _expect_integrity_error(
        db_session, ProductTranslation(product_id=product.id, language_code="uz", name="B")
    )
    _expect_integrity_error(
        db_session, ProductTranslation(product_id=product.id, language_code="de", name="B")
    )


def test_one_primary_image_per_product(db_session: Session) -> None:
    product = _product(db_session)
    other = _product(db_session, slug="pepperoni")
    _add(
        db_session,
        ProductImage(product_id=product.id, image_path="a.webp", is_primary=True),
        ProductImage(product_id=product.id, image_path="b.webp"),
        ProductImage(product_id=product.id, image_path="c.webp", sort_order=2),
        ProductImage(product_id=other.id, image_path="d.webp", is_primary=True),
    )
    _expect_integrity_error(
        db_session, ProductImage(product_id=product.id, image_path="e.webp", is_primary=True)
    )


# --------------------------------------------------------------------------- variants & money


def test_variant_sku_unique_and_price_non_negative(db_session: Session) -> None:
    product = _product(db_session)
    _variant(db_session, product, sku="PIZZA-30")
    _expect_integrity_error(
        db_session, ProductVariant(product_id=product.id, sku="PIZZA-30", price=Decimal("1.00"))
    )
    _expect_integrity_error(
        db_session, ProductVariant(product_id=product.id, sku="NEG", price=Decimal("-0.01"))
    )
    _variant(db_session, product, sku="FREE", price="0.00")


def test_money_is_decimal_with_two_places(db_session: Session) -> None:
    product = _product(db_session)
    variant = _variant(db_session, product, price="450.50")
    db_session.expire(variant)
    assert variant.price == Decimal("450.50")
    assert isinstance(variant.price, Decimal)
    assert variant.price.as_tuple().exponent == -2

    # NUMERIC(12,2): extra fraction digits are rounded by PostgreSQL ...
    rounded = db_session.execute(
        text("SELECT CAST(:v AS NUMERIC(12,2))"), {"v": Decimal("199.995")}
    ).scalar_one()
    assert rounded == Decimal("200.00")
    # ... and more than 10 integer digits overflow.
    with pytest.raises(DataError), db_session.begin_nested():
        db_session.add(
            ProductVariant(product_id=product.id, sku="HUGE", price=Decimal("10000000000.00"))
        )
        db_session.flush()
    largest = _variant(db_session, product, sku="MAX", price="9999999999.99")
    db_session.expire(largest)
    assert largest.price == Decimal("9999999999.99")


# --------------------------------------------------------------------------- modifier groups


def test_modifier_group_defaults(db_session: Session) -> None:
    group = _group(db_session)
    db_session.refresh(group)
    assert group.is_required is False
    assert group.min_selections == 0
    assert group.max_selections is None
    assert group.is_active is True
    assert group.sort_order == 0


@pytest.mark.parametrize(
    "values",
    [
        {"selection_type": "single", "max_selections": 1},
        {"selection_type": "single", "max_selections": 1, "is_required": True, "min_selections": 1},
        {"selection_type": "multiple", "max_selections": None},
        {
            "selection_type": "multiple",
            "min_selections": 2,
            "max_selections": 3,
            "is_required": True,
        },
    ],
)
def test_valid_modifier_groups(db_session: Session, values: dict[str, object]) -> None:
    _group(db_session, **values)


@pytest.mark.parametrize(
    "values",
    [
        {"selection_type": "single", "max_selections": None},  # DEC-128
        {"selection_type": "single", "max_selections": 2},
        {"selection_type": "dropdown"},
        {"min_selections": -1},
        {"max_selections": 0},
        {"min_selections": 3, "max_selections": 2, "is_required": True},
        {"is_required": True, "min_selections": 0},
        {"is_required": False, "min_selections": 1},
    ],
)
def test_invalid_modifier_groups_are_rejected(
    db_session: Session, values: dict[str, object]
) -> None:
    defaults: dict[str, object] = {"selection_type": SelectionType.MULTIPLE}
    _expect_integrity_error(db_session, ModifierGroup(**(defaults | values)))


def test_group_linked_to_product_cannot_be_deleted(db_session: Session) -> None:
    product = _product(db_session)
    group = _group(db_session)
    _add(db_session, ProductModifierGroup(product_id=product.id, group_id=group.id))
    _expect_integrity_error(
        db_session, ProductModifierGroup(product_id=product.id, group_id=group.id)
    )
    _expect_sql_error(db_session, "DELETE FROM modifier_groups WHERE id = :id", id=group.id)


def test_unlinked_group_deletion_cascades(db_session: Session) -> None:
    group = _group(db_session)
    modifier = _modifier(db_session, group)
    _add(
        db_session,
        ModifierGroupTranslation(group_id=group.id, language_code="ky", name="Соус"),
        ModifierTranslation(modifier_id=modifier.id, language_code="ky", name="Сыр"),
    )
    _delete(db_session, "modifier_groups", group.id)
    assert _count(db_session, "modifier_group_translations", "group_id", group.id) == 0
    assert _count(db_session, "modifiers", "group_id", group.id) == 0
    assert _count(db_session, "modifier_translations", "modifier_id", modifier.id) == 0


# --------------------------------------------------------------------------- modifiers


def test_modifier_defaults_and_checks(db_session: Session) -> None:
    group = _group(db_session)
    modifier = _modifier(db_session, group)
    db_session.refresh(modifier)
    assert modifier.price_delta == Decimal("0.00")
    assert modifier.max_quantity == 1
    assert modifier.is_available is True

    _modifier(db_session, group, max_quantity=3, price_delta=Decimal("50.00"))  # double cheese
    _expect_integrity_error(db_session, Modifier(group_id=group.id, max_quantity=0))
    _expect_integrity_error(db_session, Modifier(group_id=group.id, price_delta=Decimal("-1")))


def test_modifier_translations_unique_language(db_session: Session) -> None:
    modifier = _modifier(db_session, _group(db_session))
    _add(db_session, ModifierTranslation(modifier_id=modifier.id, language_code="ru", name="Сыр"))
    _expect_integrity_error(
        db_session, ModifierTranslation(modifier_id=modifier.id, language_code="ru", name="X")
    )


def test_variant_modifier_prices(db_session: Session) -> None:
    product = _product(db_session)
    variant = _variant(db_session, product)
    group = _group(db_session)
    modifier = _modifier(db_session, group)
    other = _modifier(db_session, group)

    def price(modifier_id: uuid.UUID, amount: str) -> VariantModifierPrice:
        return VariantModifierPrice(
            variant_id=variant.id, modifier_id=modifier_id, price_delta=Decimal(amount)
        )

    _add(db_session, price(modifier.id, "80.00"), price(other.id, "0.00"))
    _expect_integrity_error(db_session, price(modifier.id, "1"))  # duplicate PK
    _expect_integrity_error(db_session, price(uuid.uuid4(), "1"))  # unknown modifier (FK)
    _expect_sql_error(
        db_session,
        "INSERT INTO variant_modifier_prices (variant_id, modifier_id, price_delta) "
        "VALUES (:v, :m, -1)",
        v=variant.id,
        m=modifier.id,
    )
    # Overrides disappear with the modifier or the variant (CASCADE).
    _delete(db_session, "modifiers", other.id)
    assert _count(db_session, "variant_modifier_prices", "modifier_id", other.id) == 0
    _delete(db_session, "product_variants", variant.id)
    assert _count(db_session, "variant_modifier_prices", "variant_id", variant.id) == 0


# --------------------------------------------------------------------------- relationships


def test_relationships_require_explicit_loading(db_session: Session) -> None:
    product = _product(db_session)
    _variant(db_session, product)
    group = _group(db_session)
    _modifier(db_session, group)
    _add(
        db_session,
        ProductTranslation(product_id=product.id, language_code="ru", name="Маргарита"),
        ProductModifierGroup(product_id=product.id, group_id=group.id),
    )
    db_session.expunge_all()

    lazy = db_session.get(Product, product.id)
    assert lazy is not None
    for attribute in ("category", "translations", "images", "variants", "modifier_group_links"):
        with pytest.raises(InvalidRequestError, match="lazy='raise'"):
            getattr(lazy, attribute)
    db_session.expunge_all()

    loaded = db_session.scalars(
        select(Product)
        .where(Product.id == product.id)
        .options(
            selectinload(Product.category),
            selectinload(Product.translations),
            selectinload(Product.variants),
            selectinload(Product.modifier_group_links)
            .selectinload(ProductModifierGroup.group)
            .selectinload(ModifierGroup.modifiers),
        )
    ).one()
    assert loaded.category.slug == "cat-margherita"
    assert [t.name for t in loaded.translations] == ["Маргарита"]
    assert [v.sku for v in loaded.variants] == ["SKU-1"]
    assert len(loaded.modifier_group_links[0].group.modifiers) == 1
