"""`POST /checkout/quote` (API_SPECIFICATION.md §6.1, DEC-148).

Informational: always `200` with the full calculation and `problems`
(catalog codes of §1.1). Order creation recalculates everything.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.language import LanguageCode, language_chain
from app.db.session import get_session
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.orders.checkout import Point, address_point, calculate
from app.modules.orders.schemas import QuoteIn, QuoteOut
from app.modules.users.enums import RoleName

router = APIRouter(prefix="/checkout", tags=["checkout"])

Session = Annotated[AsyncSession, Depends(get_session)]
Customer = Annotated[CurrentUser, Depends(require_roles(RoleName.CUSTOMER.value))]
LanguageParam = Annotated[LanguageCode | None, Query(description="ru, ky или uz")]


@router.post("/quote", response_model=QuoteOut)
async def quote(
    payload: QuoteIn, session: Session, user: Customer, language: LanguageParam = None
) -> QuoteOut:
    point = None
    if payload.address_id is not None:
        _, point = await address_point(session, user.id, payload.address_id)
    elif payload.address is not None:
        point = Point(payload.address.latitude, payload.address.longitude)
    calc = await calculate(
        session,
        user.id,
        language_chain(language, user.preferred_language),
        payload.delivery_type,
        point,
        lock_cart=False,
    )
    return calc.to_quote()
