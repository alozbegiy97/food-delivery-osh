"""Customer orders (API_SPECIFICATION.md §6.2, §6.3; DEC-25, DEC-148).

Only the `customer` role; an order is visible only to its owner. Thin
layer: rules live in `app.modules.orders`.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.orders import cancellation, queries, service
from app.modules.orders.idempotency import validate_key
from app.modules.orders.schemas import (
    CancellationRequestCreate,
    CancellationRequestOut,
    OrderCreate,
    OrderCreated,
    OrderDetail,
    OrderList,
)
from app.modules.users.enums import RoleName

router = APIRouter(prefix="/orders", tags=["orders"])

Session = Annotated[AsyncSession, Depends(get_session)]
Customer = Annotated[CurrentUser, Depends(require_roles(RoleName.CUSTOMER.value))]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=OrderCreated)
async def create_order(
    payload: OrderCreate,
    session: Session,
    user: Customer,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description="1–128 символов [A-Za-z0-9_-] (DEC-109)",
        ),
    ] = None,
) -> JSONResponse:
    result = await service.create_order(
        session,
        user_id=user.id,
        preferred_language=user.preferred_language,
        payload=payload,
        idempotency_key=validate_key(idempotency_key),
    )
    headers = {"Idempotent-Replayed": "true"} if result.replayed else None
    return JSONResponse(status_code=result.status, content=result.body, headers=headers)


@router.get("", response_model=OrderList)
async def list_orders(
    session: Session,
    user: Customer,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> OrderList:
    return await queries.list_orders(session, user.id, page=page, page_size=page_size)


@router.get("/{order_id}", response_model=OrderDetail)
async def get_order(order_id: uuid.UUID, session: Session, user: Customer) -> OrderDetail:
    return await queries.get_order(session, user.id, order_id)


@router.post(
    "/{order_id}/cancellation-requests",
    status_code=status.HTTP_201_CREATED,
    response_model=CancellationRequestOut,
)
async def request_cancellation(
    order_id: uuid.UUID,
    payload: CancellationRequestCreate,
    session: Session,
    user: Customer,
) -> CancellationRequestOut:
    return await cancellation.create_request(session, user.id, order_id, payload)
