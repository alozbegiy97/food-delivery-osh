"""Public catalog responses (API_SPECIFICATION.md §3).

Money is `Decimal` and is serialized as a decimal string ("450.00").
"""

import uuid
from decimal import Decimal

from pydantic import BaseModel


class Pagination(BaseModel):
    page: int
    page_size: int
    total: int
    pages: int


class CategoryOut(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    description: str | None
    image_url: str | None
    sort_order: int


class CategoryList(BaseModel):
    items: list[CategoryOut]


class ProductSummary(BaseModel):
    id: uuid.UUID
    slug: str
    category_id: uuid.UUID
    name: str
    description: str | None
    image_url: str | None
    is_available: bool
    is_featured: bool
    # Lowest price among available variants; null when none is available.
    price_from: Decimal | None


class ProductList(BaseModel):
    items: list[ProductSummary]
    pagination: Pagination


class ImageOut(BaseModel):
    url: str
    alt_text: str | None
    is_primary: bool


class VariantOut(BaseModel):
    id: uuid.UUID
    name: str
    price: Decimal
    is_available: bool


class VariantPriceOut(BaseModel):
    variant_id: uuid.UUID
    price_delta: Decimal


class ModifierOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    price_delta: Decimal
    max_quantity: int
    is_available: bool
    # Overrides of `price_delta` for particular variants (DATABASE_SCHEMA.md §5.6).
    variant_prices: list[VariantPriceOut]


class ModifierGroupOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    selection_type: str
    is_required: bool
    min_selections: int
    max_selections: int | None
    modifiers: list[ModifierOut]


class ProductDetail(ProductSummary):
    images: list[ImageOut]
    variants: list[VariantOut]
    modifier_groups: list[ModifierGroupOut]
