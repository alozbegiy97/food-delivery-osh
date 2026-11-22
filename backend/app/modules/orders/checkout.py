"""Checkout calculation shared by the quote and order creation (DEC-08).

Order of checks (§14.1, DEC-148): empty cart; restaurant open (DEC-20,
DEC-21); delivery/pickup enabled (DEC-22); every cart line still available
and valid (§5.7); delivery zone of the point (PostGIS, DEC-102); minimum
order (DEC-17…DEC-19, compared with the subtotal without delivery).

The quote reports every problem with its catalog code (API §1.1); order
creation raises the first one as an error.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.addresses import service as addresses
from app.modules.cart.service import CartContent, CartLine, load_cart_content
from app.modules.delivery.zones import ZoneMatch, find_zone
from app.modules.orders.schemas import ProblemOut, QuoteOut, ZoneOut
from app.modules.pricing.service import (
    AVAILABILITY_ISSUES,
    ZERO,
    CatalogSnapshot,
    LineEvaluation,
    evaluate_line,
    load_catalog,
)
from app.modules.restaurant.service import get_restaurant

CART_EMPTY = "CART_EMPTY"
ITEM_UNAVAILABLE = "ITEM_UNAVAILABLE"
MODIFIER_CONSTRAINT_VIOLATION = "MODIFIER_CONSTRAINT_VIOLATION"
RESTAURANT_CLOSED = "RESTAURANT_CLOSED"
DELIVERY_DISABLED = "DELIVERY_DISABLED"
PICKUP_DISABLED = "PICKUP_DISABLED"
OUT_OF_DELIVERY_ZONE = "OUT_OF_DELIVERY_ZONE"
MIN_ORDER_NOT_REACHED = "MIN_ORDER_NOT_REACHED"

MESSAGES = {
    CART_EMPTY: "Корзина пуста",
    ITEM_UNAVAILABLE: "Товар, размер или добавка недоступны",
    MODIFIER_CONSTRAINT_VIOLATION: "Нарушены правила выбора добавок",
    RESTAURANT_CLOSED: "Ресторан сейчас закрыт",
    DELIVERY_DISABLED: "Доставка сейчас недоступна",
    PICKUP_DISABLED: "Самовывоз сейчас недоступен",
    OUT_OF_DELIVERY_ZONE: "Адрес вне зоны доставки",
    MIN_ORDER_NOT_REACHED: "Сумма заказа меньше минимальной",
}


def utc_now() -> datetime:
    """Current moment; tests replace it to check working hours (DEC-20)."""
    return datetime.now(UTC)


@dataclass(frozen=True)
class Point:
    latitude: Decimal
    longitude: Decimal


@dataclass(frozen=True)
class PricedLine:
    line: CartLine
    evaluation: LineEvaluation


@dataclass
class Calculation:
    delivery_type: str
    cart: CartContent
    catalog: CatalogSnapshot
    lines: list[PricedLine]
    subtotal: Decimal
    items_count: int
    zone: ZoneMatch | None
    delivery_fee: Decimal
    min_order_amount: Decimal
    min_order_reached: bool
    is_open_now: bool
    next_opening_at: datetime | None
    delivery_enabled: bool
    pickup_enabled: bool
    problems: list[ProblemOut] = field(default_factory=list)

    @property
    def total(self) -> Decimal:
        return self.subtotal + self.delivery_fee

    def to_quote(self) -> QuoteOut:
        return QuoteOut(
            delivery_type=self.delivery_type,
            items_count=self.items_count,
            subtotal=self.subtotal,
            zone=ZoneOut(id=self.zone.id, name=self.zone.name) if self.zone else None,
            delivery_fee=self.delivery_fee,
            min_order_amount=self.min_order_amount,
            min_order_reached=self.min_order_reached,
            total=self.total,
            is_open_now=self.is_open_now,
            next_opening_at=self.next_opening_at,
            delivery_enabled=self.delivery_enabled,
            pickup_enabled=self.pickup_enabled,
            problems=self.problems,
            can_place_order=not self.problems,
        )

    def first_problem_error(self) -> AppError | None:
        if not self.problems:
            return None
        problem = self.problems[0]
        return AppError(422, problem.code, MESSAGES[problem.code], details=problem.details)


async def address_point(
    session: AsyncSession, user_id: uuid.UUID, address_id: uuid.UUID
) -> tuple[Any, Point]:
    """The caller's saved address and its point; 404 if not his, 422 if it
    has no coordinates (DEC-01)."""
    address = await addresses.get_own(session, user_id, address_id)
    if address.latitude is None or address.longitude is None:
        raise AppError(
            422,
            "VALIDATION_ERROR",
            "Проверьте данные",
            details=[{"field": "address_id", "message": "у адреса нет точки на карте"}],
        )
    return address, Point(address.latitude, address.longitude)


def _line_problems(lines: list[PricedLine]) -> list[ProblemOut]:
    broken = [priced for priced in lines if not priced.evaluation.is_valid]
    if not broken:
        return []
    details = [
        {
            "item_id": str(priced.line.id),
            "issues": [issue.as_dict() for issue in priced.evaluation.issues],
        }
        for priced in broken
    ]
    unavailable = any(
        issue.code in AVAILABILITY_ISSUES for priced in broken for issue in priced.evaluation.issues
    )
    code = ITEM_UNAVAILABLE if unavailable else MODIFIER_CONSTRAINT_VIOLATION
    return [ProblemOut(code=code, details=details)]


async def calculate(
    session: AsyncSession,
    user_id: uuid.UUID,
    chain: tuple[str, ...],
    delivery_type: str,
    point: Point | None,
    *,
    lock_cart: bool,
    now: datetime | None = None,
) -> Calculation:
    moment = now or utc_now()
    restaurant = await get_restaurant(session, now=moment)
    cart = await load_cart_content(session, user_id, lock=lock_cart)
    catalog = await load_catalog(
        session,
        (line.product_id for line in cart.lines),
        (m for line in cart.lines for m in line.modifiers),
        chain,
    )
    lines = [
        PricedLine(line, evaluate_line(catalog, line.product_id, line.variant_id, line.modifiers))
        for line in cart.lines
    ]
    # Only lines without issues count (DEC-147).
    subtotal = ZERO
    for priced in lines:
        total = priced.evaluation.line_total(priced.line.quantity)
        if priced.evaluation.is_valid and total is not None:
            subtotal += total

    zone = None
    delivery_fee = ZERO
    if delivery_type == "delivery":
        min_order = restaurant.min_order_amount
        if point is not None:
            zone = await find_zone(session, point.latitude, point.longitude)
        if zone is not None:
            delivery_fee = zone.delivery_fee
            if zone.min_order_amount > 0:  # DEC-17
                min_order = zone.min_order_amount
    else:
        min_order = restaurant.min_order_amount  # DEC-18
    min_reached = subtotal >= min_order  # DEC-19: without the delivery fee

    problems: list[ProblemOut] = []
    if not cart.lines:
        problems.append(ProblemOut(code=CART_EMPTY))
    if not restaurant.is_open_now:
        problems.append(
            ProblemOut(
                code=RESTAURANT_CLOSED,
                details={
                    "next_opening_at": restaurant.next_opening_at.isoformat()
                    if restaurant.next_opening_at
                    else None
                },
            )
        )
    if delivery_type == "delivery" and not restaurant.delivery_enabled:
        problems.append(ProblemOut(code=DELIVERY_DISABLED))
    if delivery_type == "pickup" and not restaurant.pickup_enabled:
        problems.append(ProblemOut(code=PICKUP_DISABLED))
    problems.extend(_line_problems(lines))
    if delivery_type == "delivery" and zone is None:
        problems.append(ProblemOut(code=OUT_OF_DELIVERY_ZONE))
    if cart.lines and not min_reached and (delivery_type == "pickup" or zone is not None):
        problems.append(
            ProblemOut(
                code=MIN_ORDER_NOT_REACHED,
                details={"min_order_amount": f"{min_order:.2f}", "subtotal": f"{subtotal:.2f}"},
            )
        )

    return Calculation(
        delivery_type=delivery_type,
        cart=cart,
        catalog=catalog,
        lines=lines,
        subtotal=subtotal,
        items_count=sum(line.quantity for line in cart.lines),
        zone=zone,
        delivery_fee=delivery_fee,
        min_order_amount=min_order,
        min_order_reached=min_reached,
        is_open_now=restaurant.is_open_now,
        next_opening_at=restaurant.next_opening_at,
        delivery_enabled=restaurant.delivery_enabled,
        pickup_enabled=restaurant.pickup_enabled,
        problems=problems,
    )
