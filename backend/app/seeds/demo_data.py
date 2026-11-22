"""Data of seed mode `demo`: demo zone and catalog (DEC-120, DEC-136…DEC-138).

Pure data and row builders only: no database access, no SQL.

- Composition (8 categories, 21 products, variants, modifier groups) is
  fixed by DEC-136; slugs, codes and settings were agreed on 2026-11-08.
- PRICES ARE DEMONSTRATION PROPOSALS, not approved restaurant prices.
- KY and UZ translations are drafts: a native speaker must review them
  before a real run (DEC-120). Uzbek uses Latin script with `ʻ` (U+02BB)
  in oʻ/gʻ and `ʼ` (U+02BC) as the tutuq belgisi.
- Every record id is `seed_uuid(code)` with the codes of DEC-138.
  Translations get a UUIDv5 id too, but their existence is decided only by
  the pair (parent id, language_code) (DEC-137, DEC-138).
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.db.types import Language
from app.modules.catalog.enums import SelectionType
from app.seeds.common import seed_uuid

DEMO_SLUG_PREFIX = "demo-"
SKU_PREFIX = "DEMO-"


@dataclass(frozen=True)
class Names:
    ru: str
    ky: str
    uz: str

    def items(self) -> list[tuple[Language, str]]:
        return [(Language.RU, self.ru), (Language.KY, self.ky), (Language.UZ, self.uz)]


@dataclass(frozen=True)
class ZoneData:
    code: str
    name: str
    description: str
    delivery_fee: Decimal
    min_order_amount: Decimal
    boundary_wkt: str
    srid: int


@dataclass(frozen=True)
class CategoryData:
    slug: str
    sort_order: int
    names: Names


@dataclass(frozen=True)
class ModifierPriceData:
    """Per-variant override of a modifier surcharge (variant_modifier_prices)."""

    group_code: str
    modifier_code: str
    price_delta: Decimal


@dataclass(frozen=True)
class VariantData:
    code: str
    sku: str
    sort_order: int
    price: Decimal
    modifier_prices: tuple[ModifierPriceData, ...] = ()


@dataclass(frozen=True)
class GroupLinkData:
    group_code: str
    sort_order: int


@dataclass(frozen=True)
class ProductData:
    code: str
    category_slug: str
    sort_order: int
    names: Names
    variants: tuple[VariantData, ...]
    groups: tuple[GroupLinkData, ...] = ()

    @property
    def slug(self) -> str:
        return DEMO_SLUG_PREFIX + self.code


@dataclass(frozen=True)
class ModifierData:
    code: str
    sort_order: int
    names: Names
    price_delta: Decimal
    max_quantity: int


@dataclass(frozen=True)
class ModifierGroupData:
    code: str
    sort_order: int
    names: Names
    selection_type: SelectionType
    is_required: bool
    min_selections: int
    max_selections: int | None
    modifiers: tuple[ModifierData, ...]


# --- Demo zone (DEC-119, DEC-124, DEC-136) ----------------------------------
# Rectangle lat 40.49-40.57, lon 72.74-72.86 (WKT order: lon lat).
# name/description: approved by the project owner on 2026-11-09.

DEMO_ZONE = ZoneData(
    code="osh",
    name="Демо-зона доставки — Ош",
    description=(
        "Демонстрационная зона доставки для тестирования каталога. "
        "Не является утверждённой рестораном зоной обслуживания."
    ),
    delivery_fee=Decimal("100.00"),
    min_order_amount=Decimal("500.00"),
    boundary_wkt=(
        "MULTIPOLYGON(((72.74 40.49, 72.86 40.49, 72.86 40.57, 72.74 40.57, 72.74 40.49)))"
    ),
    srid=4326,
)

# --- Categories ----------------------------------------------------------------

CATEGORIES: tuple[CategoryData, ...] = (
    CategoryData("pizza", 0, Names("Пицца", "Пицца", "Pitsa")),
    CategoryData("burgers", 1, Names("Бургеры", "Бургерлер", "Burgerlar")),
    CategoryData("national", 2, Names("Национальная кухня", "Улуттук тамактар", "Milliy taomlar")),
    CategoryData("shawarma", 3, Names("Шаурма", "Шаурма", "Shaurma")),
    CategoryData("salads", 4, Names("Салаты", "Салаттар", "Salatlar")),
    CategoryData("soups", 5, Names("Супы", "Шорполор", "Shoʻrvalar")),
    CategoryData("desserts", 6, Names("Десерты", "Десерттер", "Desertlar")),
    CategoryData("drinks", 7, Names("Напитки", "Суусундуктар", "Ichimliklar")),
)

# --- Modifier groups and modifiers ---------------------------------------------
# D1 (DEC-58) and DEC-128: single => max_selections = 1;
# is_required = (min_selections >= 1); min <= max.

MODIFIER_GROUPS: tuple[ModifierGroupData, ...] = (
    ModifierGroupData(
        code="pizza-dough",
        sort_order=0,
        names=Names("Тесто", "Камыр", "Xamir"),
        selection_type=SelectionType.SINGLE,
        is_required=True,
        min_selections=1,
        max_selections=1,
        modifiers=(
            ModifierData(
                "thin", 0, Names("Тонкое тесто", "Жука камыр", "Yupqa xamir"), Decimal("0.00"), 1
            ),
            ModifierData(
                "traditional",
                1,
                Names("Традиционное тесто", "Салттуу камыр", "Anʼanaviy xamir"),
                Decimal("0.00"),
                1,
            ),
        ),
    ),
    ModifierGroupData(
        code="pizza-extras",
        sort_order=1,
        names=Names("Добавки", "Кошумчалар", "Qoʻshimchalar"),
        selection_type=SelectionType.MULTIPLE,
        is_required=False,
        min_selections=0,
        max_selections=3,
        modifiers=(
            ModifierData("cheese", 0, Names("Сыр", "Сыр", "Pishloq"), Decimal("60.00"), 2),
            ModifierData(
                "mushrooms", 1, Names("Грибы", "Козу карын", "Qoʻziqorin"), Decimal("50.00"), 1
            ),
            ModifierData(
                "jalapeno", 2, Names("Халапеньо", "Халапеньо", "Xalapenyo"), Decimal("40.00"), 1
            ),
        ),
    ),
    ModifierGroupData(
        code="burger-extras",
        sort_order=0,
        names=Names("Добавки к бургеру", "Бургерге кошумчалар", "Burger uchun qoʻshimchalar"),
        selection_type=SelectionType.MULTIPLE,
        is_required=False,
        min_selections=0,
        max_selections=2,
        modifiers=(
            ModifierData(
                "patty",
                0,
                Names("Дополнительная котлета", "Кошумча котлет", "Qoʻshimcha kotlet"),
                Decimal("120.00"),
                2,
            ),
            ModifierData("cheese", 1, Names("Сыр", "Сыр", "Pishloq"), Decimal("40.00"), 1),
        ),
    ),
    ModifierGroupData(
        code="shawarma-sauce",
        sort_order=0,
        names=Names("Соус", "Соус", "Sous"),
        selection_type=SelectionType.SINGLE,
        is_required=False,
        min_selections=0,
        max_selections=1,
        modifiers=(
            ModifierData(
                "garlic",
                0,
                Names("Чесночный соус", "Сарымсак соусу", "Sarimsoqli sous"),
                Decimal("20.00"),
                1,
            ),
            ModifierData(
                "spicy", 1, Names("Острый соус", "Ачуу соус", "Achchiq sous"), Decimal("20.00"), 1
            ),
            ModifierData(
                "cheese",
                2,
                Names("Сырный соус", "Сыр соусу", "Pishloqli sous"),
                Decimal("20.00"),
                1,
            ),
        ),
    ),
)

# --- Variant names (by variant code) ---------------------------------------------

VARIANT_NAMES: dict[str, Names] = {
    "30": Names("30 см", "30 см", "30 sm"),
    "40": Names("40 см", "40 см", "40 sm"),
    "std": Names("Стандарт", "Стандарт", "Standart"),
    "large": Names("Большая", "Чоң", "Katta"),
    "5pcs": Names("5 шт", "5 даана", "5 dona"),
    "10pcs": Names("10 шт", "10 даана", "10 dona"),
    "05l": Names("0,5 л", "0,5 л", "0,5 l"),
    "1l": Names("1 л", "1 л", "1 l"),
}


def _std(sku: str, price: str) -> tuple[VariantData, ...]:
    return (VariantData("std", sku, 0, Decimal(price)),)


def _pizza_variants(sku_base: str, price_30: str, price_40: str) -> tuple[VariantData, ...]:
    # 40 cm: higher surcharges for pizza extras (DEC-136); 30 cm uses
    # modifiers.price_delta.
    overrides = (
        ModifierPriceData("pizza-extras", "cheese", Decimal("80.00")),
        ModifierPriceData("pizza-extras", "mushrooms", Decimal("70.00")),
        ModifierPriceData("pizza-extras", "jalapeno", Decimal("60.00")),
    )
    return (
        VariantData("30", f"{sku_base}-30", 0, Decimal(price_30)),
        VariantData("40", f"{sku_base}-40", 1, Decimal(price_40), overrides),
    )


def _two(sku_base: str, first: tuple[str, str], second: tuple[str, str]) -> tuple[VariantData, ...]:
    """Two variants: (variant code, price) each; SKU suffix = code in upper case."""
    return (
        VariantData(first[0], f"{sku_base}-{first[0].upper()}", 0, Decimal(first[1])),
        VariantData(second[0], f"{sku_base}-{second[0].upper()}", 1, Decimal(second[1])),
    )


PIZZA_GROUPS = (GroupLinkData("pizza-dough", 0), GroupLinkData("pizza-extras", 1))
BURGER_GROUPS = (GroupLinkData("burger-extras", 0),)
SHAWARMA_GROUPS = (GroupLinkData("shawarma-sauce", 0),)

# --- Products --------------------------------------------------------------------

PRODUCTS: tuple[ProductData, ...] = (
    # pizza
    ProductData(
        "pizza-margherita",
        "pizza",
        0,
        Names("Маргарита", "Маргарита", "Margarita"),
        _pizza_variants("DEMO-PIZZA-MARGHERITA", "550.00", "750.00"),
        PIZZA_GROUPS,
    ),
    ProductData(
        "pizza-pepperoni-beef",
        "pizza",
        1,
        Names("Пепперони (говяжья)", "Пепперони (уй этинен)", "Pepperoni (mol goʻshtidan)"),
        _pizza_variants("DEMO-PIZZA-PEPPERONI-BEEF", "650.00", "850.00"),
        PIZZA_GROUPS,
    ),
    ProductData(
        "pizza-four-cheese",
        "pizza",
        2,
        Names("Четыре сыра", "Төрт сыр", "Toʻrt pishloq"),
        _pizza_variants("DEMO-PIZZA-FOUR-CHEESE", "690.00", "890.00"),
        PIZZA_GROUPS,
    ),
    # burgers
    ProductData(
        "burger-classic",
        "burgers",
        0,
        Names("Классический бургер", "Классикалык бургер", "Klassik burger"),
        _std("DEMO-BURGER-CLASSIC-STD", "280.00"),
        BURGER_GROUPS,
    ),
    ProductData(
        "burger-cheeseburger",
        "burgers",
        1,
        Names("Чизбургер", "Чизбургер", "Chizburger"),
        _std("DEMO-BURGER-CHEESEBURGER-STD", "320.00"),
        BURGER_GROUPS,
    ),
    ProductData(
        "burger-chicken",
        "burgers",
        2,
        Names("Куриный бургер", "Тоок бургер", "Tovuqli burger"),
        _std("DEMO-BURGER-CHICKEN-STD", "300.00"),
        BURGER_GROUPS,
    ),
    # national
    ProductData(
        "plov",
        "national",
        0,
        Names("Плов", "Палоо", "Palov"),
        _std("DEMO-PLOV-STD", "300.00"),
    ),
    ProductData(
        "lagman",
        "national",
        1,
        Names("Лагман", "Лагман", "Lagʻmon"),
        _std("DEMO-LAGMAN-STD", "280.00"),
    ),
    ProductData(
        "manty",
        "national",
        2,
        Names("Манты", "Манты", "Manti"),
        _two("DEMO-MANTY", ("5pcs", "250.00"), ("10pcs", "450.00")),
    ),
    # shawarma
    ProductData(
        "shawarma-chicken",
        "shawarma",
        0,
        Names("Шаурма куриная", "Тоок эти менен шаурма", "Tovuqli shaurma"),
        _two("DEMO-SHAWARMA-CHICKEN", ("std", "220.00"), ("large", "280.00")),
        SHAWARMA_GROUPS,
    ),
    ProductData(
        "shawarma-beef",
        "shawarma",
        1,
        Names("Шаурма говяжья", "Уй эти менен шаурма", "Mol goʻshtli shaurma"),
        _two("DEMO-SHAWARMA-BEEF", ("std", "260.00"), ("large", "320.00")),
        SHAWARMA_GROUPS,
    ),
    # salads
    ProductData(
        "salad-caesar",
        "salads",
        0,
        Names("Цезарь", "Цезарь", "Sezar"),
        _std("DEMO-SALAD-CAESAR-STD", "320.00"),
    ),
    ProductData(
        "salad-achichuk",
        "salads",
        1,
        Names("Ачичук", "Аччык-чучук", "Achchiq-chuchuk"),
        _std("DEMO-SALAD-ACHICHUK-STD", "180.00"),
    ),
    ProductData(
        "salad-greek",
        "salads",
        2,
        Names("Греческий салат", "Грек салаты", "Grek salati"),
        _std("DEMO-SALAD-GREEK-STD", "290.00"),
    ),
    # soups
    ProductData(
        "soup-shorpo",
        "soups",
        0,
        Names("Шорпо", "Шорпо", "Shoʻrva"),
        _std("DEMO-SOUP-SHORPO-STD", "260.00"),
    ),
    ProductData(
        "soup-lentil",
        "soups",
        1,
        Names("Чечевичный суп", "Жасмык шорпосу", "Yasmiq shoʻrva"),
        _std("DEMO-SOUP-LENTIL-STD", "200.00"),
    ),
    # desserts
    ProductData(
        "dessert-medovik",
        "desserts",
        0,
        Names("Медовик", "Медовик", "Medovik"),
        _std("DEMO-DESSERT-MEDOVIK-STD", "180.00"),
    ),
    ProductData(
        "dessert-cheesecake",
        "desserts",
        1,
        Names("Чизкейк", "Чизкейк", "Chizkeyk"),
        _std("DEMO-DESSERT-CHEESECAKE-STD", "220.00"),
    ),
    # drinks
    ProductData(
        "drink-kompot",
        "drinks",
        0,
        Names("Компот", "Компот", "Kompot"),
        _two("DEMO-DRINK-KOMPOT", ("05l", "80.00"), ("1l", "140.00")),
    ),
    ProductData(
        "drink-ayran",
        "drinks",
        1,
        Names("Айран", "Айран", "Ayron"),
        _two("DEMO-DRINK-AYRAN", ("05l", "70.00"), ("1l", "120.00")),
    ),
    ProductData(
        "drink-black-tea",
        "drinks",
        2,
        Names("Чай чёрный", "Кара чай", "Qora choy"),
        _two("DEMO-DRINK-BLACK-TEA", ("05l", "60.00"), ("1l", "100.00")),
    ),
)

# --- UUIDv5 codes (DEC-138) --------------------------------------------------------


def zone_code(zone: str) -> str:
    return f"demo.zone.{zone}"


def category_code(category_slug: str) -> str:
    return f"demo.category.{category_slug}"


def product_code(product: str) -> str:
    return f"demo.product.{product}"


def variant_code(product: str, variant: str) -> str:
    return f"demo.variant.{product}.{variant}"


def group_code(group: str) -> str:
    return f"demo.group.{group}"


def modifier_code(group: str, modifier: str) -> str:
    return f"demo.modifier.{group}.{modifier}"


def translation_code(parent_type: str, parent_code: str, language: Language) -> str:
    """`parent_type` is one of: category, product, variant, group, modifier."""
    return f"demo.translation.{parent_type}.{parent_code}.{language.value}"


def zone_id(zone: str) -> UUID:
    return seed_uuid(zone_code(zone))


def category_id(category_slug: str) -> UUID:
    return seed_uuid(category_code(category_slug))


def product_id(product: str) -> UUID:
    return seed_uuid(product_code(product))


def variant_id(product: str, variant: str) -> UUID:
    return seed_uuid(variant_code(product, variant))


def group_id(group: str) -> UUID:
    return seed_uuid(group_code(group))


def modifier_id(group: str, modifier: str) -> UUID:
    return seed_uuid(modifier_code(group, modifier))


def translation_id(parent_type: str, parent_code: str, language: Language) -> UUID:
    return seed_uuid(translation_code(parent_type, parent_code, language))


# --- Row builders (column names of the catalog models) -----------------------------

Row = dict[str, Any]


def _translations(
    parent_type: str, parent_code: str, parent_column: str, parent: UUID, names: Names
) -> list[Row]:
    rows = []
    for language, name in names.items():
        row: Row = {
            "id": translation_id(parent_type, parent_code, language),
            parent_column: parent,
            "language_code": language.value,
            "name": name,
        }
        if parent_type != "variant":  # product_variant_translations has no description
            row["description"] = None
        rows.append(row)
    return rows


def category_rows() -> list[Row]:
    return [
        {
            "id": category_id(c.slug),
            "slug": c.slug,
            "image_path": None,
            "sort_order": c.sort_order,
            "is_active": True,
        }
        for c in CATEGORIES
    ]


def category_translation_rows() -> list[Row]:
    return [
        row
        for c in CATEGORIES
        for row in _translations("category", c.slug, "category_id", category_id(c.slug), c.names)
    ]


def modifier_group_rows() -> list[Row]:
    return [
        {
            "id": group_id(g.code),
            "selection_type": g.selection_type.value,
            "is_required": g.is_required,
            "min_selections": g.min_selections,
            "max_selections": g.max_selections,
            "is_active": True,
            "sort_order": g.sort_order,
        }
        for g in MODIFIER_GROUPS
    ]


def modifier_group_translation_rows() -> list[Row]:
    return [
        row
        for g in MODIFIER_GROUPS
        for row in _translations("group", g.code, "group_id", group_id(g.code), g.names)
    ]


def modifier_rows() -> list[Row]:
    return [
        {
            "id": modifier_id(g.code, m.code),
            "group_id": group_id(g.code),
            "price_delta": m.price_delta,
            "max_quantity": m.max_quantity,
            "is_available": True,
            "sort_order": m.sort_order,
        }
        for g in MODIFIER_GROUPS
        for m in g.modifiers
    ]


def modifier_translation_rows() -> list[Row]:
    return [
        row
        for g in MODIFIER_GROUPS
        for m in g.modifiers
        for row in _translations(
            "modifier",
            f"{g.code}.{m.code}",
            "modifier_id",
            modifier_id(g.code, m.code),
            m.names,
        )
    ]


def product_rows() -> list[Row]:
    return [
        {
            "id": product_id(p.code),
            "category_id": category_id(p.category_slug),
            "slug": p.slug,
            "is_available": True,
            "is_featured": False,
            "sort_order": p.sort_order,
        }
        for p in PRODUCTS
    ]


def product_translation_rows() -> list[Row]:
    return [
        row
        for p in PRODUCTS
        for row in _translations("product", p.code, "product_id", product_id(p.code), p.names)
    ]


def variant_rows() -> list[Row]:
    return [
        {
            "id": variant_id(p.code, v.code),
            "product_id": product_id(p.code),
            "sku": v.sku,
            "price": v.price,
            "is_available": True,
            "sort_order": v.sort_order,
        }
        for p in PRODUCTS
        for v in p.variants
    ]


def variant_translation_rows() -> list[Row]:
    return [
        row
        for p in PRODUCTS
        for v in p.variants
        for row in _translations(
            "variant",
            f"{p.code}.{v.code}",
            "variant_id",
            variant_id(p.code, v.code),
            VARIANT_NAMES[v.code],
        )
    ]


def product_modifier_group_rows() -> list[Row]:
    return [
        {
            "product_id": product_id(p.code),
            "group_id": group_id(link.group_code),
            "sort_order": link.sort_order,
        }
        for p in PRODUCTS
        for link in p.groups
    ]


def variant_modifier_price_rows() -> list[Row]:
    return [
        {
            "variant_id": variant_id(p.code, v.code),
            "modifier_id": modifier_id(price.group_code, price.modifier_code),
            "price_delta": price.price_delta,
        }
        for p in PRODUCTS
        for v in p.variants
        for price in v.modifier_prices
    ]
