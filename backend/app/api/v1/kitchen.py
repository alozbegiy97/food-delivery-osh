"""`/staff/kitchen` (API §9 "Kitchen"; DEC-25, DEC-106, DEC-112, DEC-150).

Roles `cook` or `admin`. Responses use the narrow kitchen schema: no customer
personal data, comments, amounts or payment data.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.kitchen import service
from app.modules.kitchen.schemas import KitchenOrderOut, KitchenQueue
from app.modules.orders.enums import OrderStatus
from app.modules.users.enums import RoleName

router = APIRouter(prefix="/staff/kitchen", tags=["kitchen"])

Session = Annotated[AsyncSession, Depends(get_session)]
KitchenUser = Annotated[
    CurrentUser, Depends(require_roles(RoleName.COOK.value, RoleName.ADMIN.value))
]


@router.get("/orders", response_model=KitchenQueue)
async def kitchen_orders(session: Session, _: KitchenUser) -> KitchenQueue:
    return await service.queue(session)


@router.post("/orders/{order_id}/start", response_model=KitchenOrderOut)
async def start(order_id: uuid.UUID, session: Session, user: KitchenUser) -> KitchenOrderOut:
    return await service.act(
        session, order_id, OrderStatus.PREPARING.value, user_id=user.id, roles=user.roles
    )


@router.post("/orders/{order_id}/ready", response_model=KitchenOrderOut)
async def ready(order_id: uuid.UUID, session: Session, user: KitchenUser) -> KitchenOrderOut:
    return await service.act(
        session, order_id, OrderStatus.READY_FOR_PICKUP.value, user_id=user.id, roles=user.roles
    )
