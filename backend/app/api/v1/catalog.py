"""Public catalog and restaurant info (API_SPECIFICATION.md §3).

Used by both client interfaces (site and Telegram Mini App, DEC-144).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.language import LanguageCode, language_chain
from app.db.session import get_session
from app.modules.auth.dependencies import get_optional_user_language
from app.modules.catalog import service
from app.modules.catalog.schemas import CategoryList, ProductDetail, ProductList
from app.modules.restaurant.service import RestaurantOut, get_restaurant

router = APIRouter(tags=["catalog"])

Session = Annotated[AsyncSession, Depends(get_session)]
UserLanguage = Annotated[str | None, Depends(get_optional_user_language)]
LanguageParam = Annotated[LanguageCode | None, Query(description="ru, ky или uz")]


@router.get("/catalog/categories", response_model=CategoryList)
async def categories(
    session: Session, user_language: UserLanguage, language: LanguageParam = None
) -> CategoryList:
    return await service.list_categories(session, language_chain(language, user_language))


@router.get("/catalog/products", response_model=ProductList)
async def products(
    session: Session,
    user_language: UserLanguage,
    language: LanguageParam = None,
    category_id: uuid.UUID | None = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
    featured: bool | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ProductList:
    return await service.list_products(
        session,
        language_chain(language, user_language),
        category_id=category_id,
        search=search,
        featured=featured,
        page=page,
        page_size=page_size,
    )


@router.get("/catalog/products/{product_id}", response_model=ProductDetail)
async def product(
    product_id: uuid.UUID,
    session: Session,
    user_language: UserLanguage,
    language: LanguageParam = None,
) -> ProductDetail:
    return await service.get_product(session, product_id, language_chain(language, user_language))


@router.get("/restaurant", response_model=RestaurantOut)
async def restaurant(session: Session) -> RestaurantOut:
    return await get_restaurant(session)
