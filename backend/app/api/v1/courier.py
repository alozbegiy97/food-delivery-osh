"""`/courier` (API §10; DEC-36, DEC-83, DEC-92, DEC-93, DEC-106, DEC-151).

Role `courier`; the courier id is taken from the access token only, never
from the request. Every order endpoint works on the courier's own
assignment; anything else is `404`.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.courier import service
from app.modules.courier.schemas import (
    AvailabilityIn,
    CourierActiveList,
    CourierHistoryList,
    CourierHistoryOut,
    CourierMe,
    CourierOrderOut,
    DeclineIn,
)
from app.modules.users.enums import RoleName

router = APIRouter(prefix="/courier", tags=["courier"])

Session = Annotated[AsyncSession, Depends(get_session)]
Courier = Annotated[CurrentUser, Depends(require_roles(RoleName.COURIER.value))]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


@router.get("/me", response_model=CourierMe)
async def me(session: Session, courier: Courier) -> CourierMe:
    return await service.me(session, courier.id)


@router.patch("/me/availability", response_model=CourierMe)
async def availability(payload: AvailabilityIn, session: Session, courier: Courier) -> CourierMe:
    return await service.set_availability(session, courier.id, payload)


@router.get("/orders", response_model=CourierActiveList | CourierHistoryList)
async def orders(
    session: Session,
    courier: Courier,
    history: bool = False,
    page: Page = 1,
    page_size: PageSize = 20,
) -> CourierActiveList | CourierHistoryList:
    """Active assignments; `?history=true` — completed and declined (DEC-106)."""
    await service.me(session, courier.id)  # the profile is required (DEC-27)
    if history:
        return await service.history(session, courier.id, page=page, page_size=page_size)
    return await service.active_orders(session, courier.id)


@router.get("/orders/{order_id}", response_model=CourierOrderOut)
async def order(order_id: uuid.UUID, session: Session, courier: Courier) -> CourierOrderOut:
    return await service.order_detail(session, courier.id, order_id)


@router.post("/orders/{order_id}/accept", response_model=CourierOrderOut)
async def accept(order_id: uuid.UUID, session: Session, courier: Courier) -> CourierOrderOut:
    return await service.accept(session, courier.id, order_id)


@router.post("/orders/{order_id}/decline", response_model=CourierHistoryOut)
async def decline(
    order_id: uuid.UUID, session: Session, courier: Courier, payload: DeclineIn | None = None
) -> CourierHistoryOut:
    return await service.decline(session, courier.id, order_id, payload or DeclineIn())


@router.post("/orders/{order_id}/picked-up", response_model=CourierOrderOut)
async def picked_up(order_id: uuid.UUID, session: Session, courier: Courier) -> CourierOrderOut:
    return await service.picked_up(session, courier.id, order_id)


@router.post("/orders/{order_id}/delivered", response_model=CourierHistoryOut)
async def delivered(order_id: uuid.UUID, session: Session, courier: Courier) -> CourierHistoryOut:
    return await service.delivered(session, courier.id, order_id)
