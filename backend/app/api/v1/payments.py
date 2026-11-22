"""Payments (API_SPECIFICATION.md §7; DEC-47, DEC-149).

`GET /payment-methods` is public; `POST /payments/mock/confirm` is for the
order owner (role `customer`). Only simulated payments: no card data, no
real provider. Thin layer: rules live in `app.modules.payments.service`.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.payments import service
from app.modules.payments.schemas import MockConfirmIn, MockConfirmOut, PaymentMethodList
from app.modules.users.enums import RoleName

router = APIRouter(tags=["payments"])

Session = Annotated[AsyncSession, Depends(get_session)]
Customer = Annotated[CurrentUser, Depends(require_roles(RoleName.CUSTOMER.value))]


@router.get("/payment-methods", response_model=PaymentMethodList)
async def payment_methods(session: Session) -> PaymentMethodList:
    return await service.list_methods(session)


@router.post("/payments/mock/confirm", response_model=MockConfirmOut)
async def confirm_mock_payment(
    payload: MockConfirmIn, session: Session, user: Customer
) -> MockConfirmOut:
    return await service.confirm_mock(session, user.id, payload)
