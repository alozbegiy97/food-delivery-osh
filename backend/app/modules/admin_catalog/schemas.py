"""Request and response schemas of the catalog administration (§9 "Catalog").

- Translations are an array `[{language_code, name, description}]`; the
  Russian name is required, KY/UZ are optional (DEC-145). Sending the array
  replaces all translations of the record.
- Money is a decimal string with up to two fraction digits, never a float.
- Unknown fields are rejected (`extra="forbid"`).
"""

import re
import unicodedata
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

from app.modules.admin_catalog.slugs import SLUG_MAX_LENGTH, SLUG_PATTERN

LanguageCode = Literal["ru", "ky", "uz"]
MONEY_MAX = Decimal("9999999999.99")  # NUMERIC(12,2)


def _clean_text(value: str) -> str:
    value = value.strip()
    if any(unicodedata.category(ch) == "Cc" and ch not in "\n\t" for ch in value):
        raise ValueError("must not contain control characters")
    return value


def _money(value: Decimal) -> Decimal:
    if value < 0 or value > MONEY_MAX:
        raise ValueError("must be between 0 and 9999999999.99")
    if value.as_tuple().exponent < -2:  # type: ignore[operator]
        raise ValueError("at most two digits after the decimal point")
    return value.quantize(Decimal("0.01"))


def _slug(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip().lower()
    if not value:
        return None
    if len(value) > SLUG_MAX_LENGTH or not SLUG_PATTERN.fullmatch(value):
        raise ValueError("use lowercase Latin letters, digits and hyphens")
    return value


Money = Annotated[Decimal, AfterValidator(_money)]
Slug = Annotated[str | None, AfterValidator(_slug)]
SortOrder = Annotated[int, Field(ge=-1_000_000, le=1_000_000)]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _translations_rule(max_name: int):  # noqa: ANN202
    def check(items: list[TranslationIn]) -> list[TranslationIn]:
        codes = [item.language_code for item in items]
        if len(codes) != len(set(codes)):
            raise ValueError("each language may appear only once")
        if "ru" not in codes:
            raise ValueError("the Russian (ru) name is required")
        for item in items:
            if len(item.name) > max_name:
                raise ValueError(f"name must be at most {max_name} characters")
        return items

    return check


class TranslationIn(_In):
    language_code: LanguageCode
    name: Annotated[str, AfterValidator(_clean_text), Field(min_length=1, max_length=180)]
    description: str | None = None

    @field_validator("name")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value:
            raise ValueError("must not be empty")
        return value

    @field_validator("description")
    @classmethod
    def _description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = _clean_text(value)
        if len(value) > 2000:
            raise ValueError("must be at most 2000 characters")
        return value or None


class TranslationOut(BaseModel):
    language_code: str
    name: str
    description: str | None = None


def translations(max_name: int):  # noqa: ANN201
    """Annotated list type with the ru-required rule and a name length cap."""
    return Annotated[list[TranslationIn], AfterValidator(_translations_rule(max_name))]


CategoryTranslations = translations(120)
ProductTranslations = translations(180)
VariantTranslations = translations(100)
GroupTranslations = translations(120)
ModifierTranslations = translations(120)


# --------------------------------------------------------------------------
# Categories
# --------------------------------------------------------------------------


class CategoryCreate(_In):
    translations: CategoryTranslations
    slug: Slug = None
    sort_order: SortOrder = 0
    is_active: bool = True


class CategoryUpdate(_In):
    translations: CategoryTranslations | None = None
    slug: Slug = None
    sort_order: SortOrder | None = None
    is_active: bool | None = None


class CategoryAdminOut(BaseModel):
    id: uuid.UUID
    slug: str
    sort_order: int
    is_active: bool
    image_url: str | None
    translations: list[TranslationOut]
    products_count: int


class CategoryAdminList(BaseModel):
    items: list[CategoryAdminOut]


# --------------------------------------------------------------------------
# Variants and prices
# --------------------------------------------------------------------------


class VariantCreate(_In):
    translations: VariantTranslations
    sku: Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")]
    price: Money
    is_available: bool = True
    sort_order: SortOrder = 0


class VariantUpdate(_In):
    translations: VariantTranslations | None = None
    sku: (
        Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")] | None
    ) = None
    price: Money | None = None
    is_available: bool | None = None
    sort_order: SortOrder | None = None


class ModifierPriceIn(_In):
    modifier_id: uuid.UUID
    price_delta: Money


class ModifierPriceOut(BaseModel):
    modifier_id: uuid.UUID
    price_delta: Decimal


class VariantAdminOut(BaseModel):
    id: uuid.UUID
    sku: str
    price: Decimal
    is_available: bool
    sort_order: int
    translations: list[TranslationOut]
    modifier_prices: list[ModifierPriceOut]


# --------------------------------------------------------------------------
# Products
# --------------------------------------------------------------------------


class ProductCreate(_In):
    category_id: uuid.UUID
    translations: ProductTranslations
    slug: Slug = None
    is_available: bool = True
    is_featured: bool = False
    sort_order: SortOrder = 0
    # DEC-06: every product has at least one variant.
    variants: Annotated[list[VariantCreate], Field(min_length=1, max_length=20)]


class ProductUpdate(_In):
    category_id: uuid.UUID | None = None
    translations: ProductTranslations | None = None
    slug: Slug = None
    is_available: bool | None = None
    is_featured: bool | None = None
    sort_order: SortOrder | None = None


class ProductGroupLink(_In):
    group_id: uuid.UUID
    sort_order: SortOrder = 0


class ProductGroupOut(BaseModel):
    group_id: uuid.UUID
    sort_order: int


class ImageAdminOut(BaseModel):
    id: uuid.UUID
    url: str
    alt_text: str | None
    sort_order: int
    is_primary: bool


class ProductAdminSummary(BaseModel):
    id: uuid.UUID
    slug: str
    category_id: uuid.UUID
    name: str  # Russian name
    is_available: bool
    is_featured: bool
    sort_order: int
    deleted_at: datetime | None
    price_from: Decimal | None
    variants_count: int
    image_url: str | None


class ProductAdminList(BaseModel):
    items: list[ProductAdminSummary]
    total: int


class ProductAdminDetail(BaseModel):
    id: uuid.UUID
    slug: str
    category_id: uuid.UUID
    is_available: bool
    is_featured: bool
    sort_order: int
    deleted_at: datetime | None
    translations: list[TranslationOut]
    variants: list[VariantAdminOut]
    modifier_groups: list[ProductGroupOut]
    images: list[ImageAdminOut]


# --------------------------------------------------------------------------
# Modifier groups and modifiers
# --------------------------------------------------------------------------


class ModifierGroupCreate(_In):
    translations: GroupTranslations
    selection_type: Literal["single", "multiple"]
    min_selections: Annotated[int, Field(ge=0, le=100)] = 0
    # NULL = no limit; `single` requires exactly 1 (DEC-128).
    max_selections: Annotated[int, Field(ge=1, le=100)] | None = None
    is_active: bool = True
    sort_order: SortOrder = 0


class ModifierGroupUpdate(_In):
    translations: GroupTranslations | None = None
    selection_type: Literal["single", "multiple"] | None = None
    min_selections: Annotated[int, Field(ge=0, le=100)] | None = None
    max_selections: Annotated[int, Field(ge=1, le=100)] | None = None
    # Explicit flag because `max_selections: null` means "no limit".
    clear_max_selections: bool = False
    is_active: bool | None = None
    sort_order: SortOrder | None = None


class ModifierCreate(_In):
    group_id: uuid.UUID
    translations: ModifierTranslations
    price_delta: Money = Decimal("0.00")
    max_quantity: Annotated[int, Field(ge=1, le=99)] = 1
    is_available: bool = True
    sort_order: SortOrder = 0


class ModifierUpdate(_In):
    translations: ModifierTranslations | None = None
    price_delta: Money | None = None
    max_quantity: Annotated[int, Field(ge=1, le=99)] | None = None
    is_available: bool | None = None
    sort_order: SortOrder | None = None


class ModifierAdminOut(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID
    price_delta: Decimal
    max_quantity: int
    is_available: bool
    sort_order: int
    translations: list[TranslationOut]


class ModifierGroupAdminOut(BaseModel):
    id: uuid.UUID
    selection_type: str
    is_required: bool
    min_selections: int
    max_selections: int | None
    is_active: bool
    sort_order: int
    translations: list[TranslationOut]
    modifiers: list[ModifierAdminOut]
    products_count: int


class ModifierGroupAdminList(BaseModel):
    items: list[ModifierGroupAdminOut]


class ModifierAdminList(BaseModel):
    items: list[ModifierAdminOut]


SKU_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
