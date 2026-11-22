"""`/cart` (API_SPECIFICATION.md §5).

Only users with the `customer` role (DEC-13, DEC-23); roles are checked in
the database on every request. Thin layer: rules live in
`app.modules.cart.service` and `app.modules.pricing`. Shared by both client
interfaces (site and Telegram Mini App, DEC-144).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.language import LanguageCode, language_chain
from app.db.session import get_session
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.cart import service
from app.modules.cart.schemas import CartItemCreate, CartItemUpdate, CartOut
from app.modules.users.enums import RoleName

router = APIRouter(prefix="/cart", tags=["cart"])

Session = Annotated[AsyncSession, Depends(get_session)]
Customer = Annotated[CurrentUser, Depends(require_roles(RoleName.CUSTOMER.value))]
LanguageParam = Annotated[LanguageCode | None, Query(description="ru, ky или uz")]


def _chain(language: str | None, user: CurrentUser) -> tuple[str, ...]:
    return language_chain(language, user.preferred_language)


@router.get("", response_model=CartOut)
async def get_cart(session: Session, user: Customer, language: LanguageParam = None) -> CartOut:
    return await service.get_cart(session, user.id, _chain(language, user))


@router.post("/items", response_model=CartOut)
async def add_item(
    payload: CartItemCreate, session: Session, user: Customer, language: LanguageParam = None
) -> CartOut:
    return await service.add_item(session, user.id, payload, _chain(language, user))


@router.patch("/items/{item_id}", response_model=CartOut)
async def update_item(
    item_id: uuid.UUID,
    payload: CartItemUpdate,
    session: Session,
    user: Customer,
    language: LanguageParam = None,
) -> CartOut:
    return await service.update_item(session, user.id, item_id, payload, _chain(language, user))


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(item_id: uuid.UUID, session: Session, user: Customer) -> None:
    await service.delete_item(session, user.id, item_id)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def clear_cart(session: Session, user: Customer) -> None:
    await service.clear_cart(session, user.id)
