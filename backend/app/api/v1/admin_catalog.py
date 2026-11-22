"""`/admin` catalog endpoints (API_SPECIFICATION.md §9 "Catalog", DEC-72).

Every route requires the `admin` role (checked in the database on each
request, DEC-66). Thin layer: rules live in `app.modules.admin_catalog`.
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.modules.admin_catalog import categories, modifiers, products
from app.modules.admin_catalog.schemas import (
    CategoryAdminList,
    CategoryAdminOut,
    CategoryCreate,
    CategoryUpdate,
    ModifierAdminList,
    ModifierAdminOut,
    ModifierCreate,
    ModifierGroupAdminList,
    ModifierGroupAdminOut,
    ModifierGroupCreate,
    ModifierGroupUpdate,
    ModifierPriceIn,
    ModifierUpdate,
    ProductAdminDetail,
    ProductAdminList,
    ProductCreate,
    ProductGroupLink,
    ProductUpdate,
    VariantCreate,
    VariantUpdate,
)
from app.modules.auth.dependencies import require_roles
from app.modules.users.enums import RoleName

router = APIRouter(
    prefix="/admin",
    tags=["admin-catalog"],
    dependencies=[Depends(require_roles(RoleName.ADMIN.value))],
)

Session = Annotated[AsyncSession, Depends(get_session)]
ImageFile = Annotated[UploadFile, File(description="JPEG, PNG or WebP, up to 5 MB")]


# --------------------------------------------------------------------------
# Categories
# --------------------------------------------------------------------------


@router.get("/categories", response_model=CategoryAdminList)
async def list_categories(session: Session) -> CategoryAdminList:
    return await categories.list_categories(session)


@router.post("/categories", status_code=status.HTTP_201_CREATED, response_model=CategoryAdminOut)
async def create_category(data: CategoryCreate, session: Session) -> CategoryAdminOut:
    return await categories.create_category(session, data)


@router.patch("/categories/{category_id}", response_model=CategoryAdminOut)
async def update_category(
    category_id: uuid.UUID, data: CategoryUpdate, session: Session
) -> CategoryAdminOut:
    return await categories.update_category(session, category_id, data)


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_category(category_id: uuid.UUID, session: Session) -> None:
    await categories.deactivate_category(session, category_id)


@router.post("/categories/{category_id}/image", response_model=CategoryAdminOut)
async def upload_category_image(
    category_id: uuid.UUID, file: ImageFile, session: Session
) -> CategoryAdminOut:
    return await categories.set_category_image(session, category_id, file)


# --------------------------------------------------------------------------
# Products and variants
# --------------------------------------------------------------------------


@router.get("/products", response_model=ProductAdminList)
async def list_products(
    session: Session,
    category_id: uuid.UUID | None = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
    status_filter: Annotated[Literal["active", "deleted", "all"], Query(alias="status")] = "active",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ProductAdminList:
    return await products.list_products(
        session,
        category_id=category_id,
        search=search,
        status=status_filter,
        page=page,
        page_size=page_size,
    )


@router.get("/products/{product_id}", response_model=ProductAdminDetail)
async def get_product(product_id: uuid.UUID, session: Session) -> ProductAdminDetail:
    return await products.get_product(session, product_id)


@router.post("/products", status_code=status.HTTP_201_CREATED, response_model=ProductAdminDetail)
async def create_product(data: ProductCreate, session: Session) -> ProductAdminDetail:
    return await products.create_product(session, data)


@router.patch("/products/{product_id}", response_model=ProductAdminDetail)
async def update_product(
    product_id: uuid.UUID, data: ProductUpdate, session: Session
) -> ProductAdminDetail:
    return await products.update_product(session, product_id, data)


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(product_id: uuid.UUID, session: Session) -> None:
    await products.delete_product(session, product_id)


@router.post(
    "/products/{product_id}/images",
    status_code=status.HTTP_201_CREATED,
    response_model=ProductAdminDetail,
)
async def upload_product_image(
    product_id: uuid.UUID,
    file: ImageFile,
    session: Session,
    alt_text: Annotated[str | None, Form(max_length=255)] = None,
    is_primary: Annotated[bool, Form()] = False,
) -> ProductAdminDetail:
    return await products.add_image(session, product_id, file, alt_text, is_primary)


@router.delete("/products/{product_id}/images/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product_image(
    product_id: uuid.UUID, image_id: uuid.UUID, session: Session
) -> None:
    await products.delete_image(session, product_id, image_id)


@router.post(
    "/products/{product_id}/variants",
    status_code=status.HTTP_201_CREATED,
    response_model=ProductAdminDetail,
)
async def add_variant(
    product_id: uuid.UUID, data: VariantCreate, session: Session
) -> ProductAdminDetail:
    return await products.add_variant(session, product_id, data)


@router.patch("/variants/{variant_id}", response_model=ProductAdminDetail)
async def update_variant(
    variant_id: uuid.UUID, data: VariantUpdate, session: Session
) -> ProductAdminDetail:
    return await products.update_variant(session, variant_id, data)


@router.put("/variants/{variant_id}/modifier-prices", response_model=ProductAdminDetail)
async def put_modifier_prices(
    variant_id: uuid.UUID, items: list[ModifierPriceIn], session: Session
) -> ProductAdminDetail:
    return await products.put_modifier_prices(session, variant_id, items)


@router.put("/products/{product_id}/modifier-groups", response_model=ProductAdminDetail)
async def put_modifier_groups(
    product_id: uuid.UUID, items: list[ProductGroupLink], session: Session
) -> ProductAdminDetail:
    return await products.put_modifier_groups(session, product_id, items)


# --------------------------------------------------------------------------
# Modifier groups and modifiers
# --------------------------------------------------------------------------


@router.get("/modifier-groups", response_model=ModifierGroupAdminList)
async def list_groups(session: Session) -> ModifierGroupAdminList:
    return await modifiers.list_groups(session)


@router.post(
    "/modifier-groups", status_code=status.HTTP_201_CREATED, response_model=ModifierGroupAdminOut
)
async def create_group(data: ModifierGroupCreate, session: Session) -> ModifierGroupAdminOut:
    return await modifiers.create_group(session, data)


@router.patch("/modifier-groups/{group_id}", response_model=ModifierGroupAdminOut)
async def update_group(
    group_id: uuid.UUID, data: ModifierGroupUpdate, session: Session
) -> ModifierGroupAdminOut:
    return await modifiers.update_group(session, group_id, data)


@router.get("/modifiers", response_model=ModifierAdminList)
async def list_modifiers(session: Session, group_id: uuid.UUID | None = None) -> ModifierAdminList:
    return await modifiers.list_modifiers(session, group_id)


@router.post("/modifiers", status_code=status.HTTP_201_CREATED, response_model=ModifierAdminOut)
async def create_modifier(data: ModifierCreate, session: Session) -> ModifierAdminOut:
    return await modifiers.create_modifier(session, data)


@router.patch("/modifiers/{modifier_id}", response_model=ModifierAdminOut)
async def update_modifier(
    modifier_id: uuid.UUID, data: ModifierUpdate, session: Session
) -> ModifierAdminOut:
    return await modifiers.update_modifier(session, modifier_id, data)
