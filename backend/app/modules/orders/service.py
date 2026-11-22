"""Order creation in one transaction (DATABASE_SCHEMA.md §14.1; API §6.2;
DEC-09, DEC-10, DEC-15, DEC-16, DEC-43, DEC-59, DEC-61, DEC-78, DEC-97,
DEC-109, DEC-148, DEC-149).

Steps: idempotency key -> lock the cart -> checks and prices (shared
checkout calculation) -> `expected_total` -> order with snapshots in the
order language -> items and modifiers -> delivery -> saved address (if
asked) -> payment `pending` (cash, or the first mock_card attempt with
`payment_due_at`) -> first history row and event -> empty
cart -> stored response -> commit. Any error rolls everything back,
including the idempotency key.
"""

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import func, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.language import language_chain
from app.modules.addresses.schemas import AddressCreate
from app.modules.addresses.service import create_address
from app.modules.cart.service import empty_cart
from app.modules.delivery.models import Delivery
from app.modules.orders import idempotency
from app.modules.orders.checkout import Point, address_point, calculate
from app.modules.orders.enums import IdempotencyScope, OrderStatus
from app.modules.orders.models import Order, OrderItem, OrderItemModifier
from app.modules.orders.schemas import OrderCreate, OrderCreated
from app.modules.orders.status import record_initial_status
from app.modules.payments.enums import PaymentMethodCode, PaymentStatus
from app.modules.payments.service import active_method_id, add_attempt

CREATED = 201


@dataclass(frozen=True)
class CreateResult:
    status: int
    body: dict[str, Any]
    replayed: bool


def _payment_method_error() -> AppError:
    return AppError(
        422,
        "VALIDATION_ERROR",
        "Проверьте данные",
        details=[
            {
                "field": "payment_method_code",
                "message": "способ оплаты недоступен",
            }
        ],
    )


async def create_order(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    preferred_language: str,
    payload: OrderCreate,
    idempotency_key: str,
) -> CreateResult:
    # Known codes only (DEC-149); whether the method is active is checked below.
    if payload.payment_method_code not in {code.value for code in PaymentMethodCode}:
        raise _payment_method_error()
    method_code = payload.payment_method_code
    is_mock = method_code == PaymentMethodCode.MOCK_CARD

    started = await idempotency.begin(
        session,
        user_id=user_id,
        scope=IdempotencyScope.CREATE_ORDER.value,
        key=idempotency_key,
        digest=idempotency.request_hash(payload.canonical()),
    )
    if isinstance(started, idempotency.Replay):
        return CreateResult(started.status, started.body, replayed=True)
    key_id = started

    method_id = await active_method_id(session, method_code)
    if method_id is None:
        raise _payment_method_error()

    language = payload.language or preferred_language
    chain = language_chain(language, preferred_language)

    saved_address = None
    point: Point | None = None
    if payload.delivery_type == "delivery":
        if payload.address_id is not None:
            saved_address, point = await address_point(session, user_id, payload.address_id)
        else:
            assert payload.address is not None  # noqa: S101 - checked by the schema
            point = Point(payload.address.latitude, payload.address.longitude)

    calc = await calculate(session, user_id, chain, payload.delivery_type, point, lock_cart=True)
    error = calc.first_problem_error()
    if error is not None:
        raise error
    if payload.expected_total != calc.total:  # DEC-09, DEC-10
        raise AppError(
            409,
            "PRICE_CHANGED",
            "Сумма заказа изменилась",
            details=calc.to_quote().model_dump(mode="json"),
        )

    address_fields: dict[str, Any] = {}
    delivery_comment = None
    if payload.delivery_type == "delivery":
        source = saved_address if saved_address is not None else payload.address
        assert source is not None and point is not None  # noqa: S101
        address_fields = {
            "delivery_address_text": source.address_text,
            "delivery_latitude": point.latitude,
            "delivery_longitude": point.longitude,
            "delivery_entrance": source.entrance,
            "delivery_floor": source.floor,
            "delivery_apartment": source.apartment,
        }
        delivery_comment = source.comment

    order = (
        await session.execute(
            insert(Order)
            .values(
                user_id=user_id,
                language_code=language,
                delivery_type=payload.delivery_type,
                status=OrderStatus.PENDING.value,
                payment_method_code=method_code,
                subtotal=calc.subtotal,
                delivery_fee=calc.delivery_fee,
                total_amount=calc.total,
                customer_name=payload.customer_name,
                customer_phone=payload.customer_phone,
                customer_comment=payload.comment,
                # mock_card: created_at + timeout; cash: no deadline (DEC-97, DEC-149).
                payment_due_at=(
                    func.now() + timedelta(minutes=get_settings().payment_timeout_minutes)
                    if is_mock
                    else None
                ),
                **address_fields,
            )
            .returning(Order.id, Order.order_number, Order.created_at, Order.payment_due_at)
        )
    ).one()

    # Snapshots in the order language (DEC-15, DEC-60, DEC-61).
    for priced in calc.lines:
        evaluation = priced.evaluation
        product = calc.catalog.products[priced.line.product_id]
        variant = calc.catalog.variants[priced.line.variant_id]
        line_total = evaluation.line_total(priced.line.quantity)
        assert evaluation.variant_price is not None and line_total is not None  # noqa: S101
        item_id = await session.scalar(
            insert(OrderItem)
            .values(
                order_id=order.id,
                product_id=product.id,
                variant_id=variant.id,
                product_name=product.name,
                variant_name=variant.name,
                sku=variant.sku,
                unit_price=evaluation.variant_price,
                quantity=priced.line.quantity,
                total_price=line_total,
                special_instructions=priced.line.special_instructions,
            )
            .returning(OrderItem.id)
        )
        if evaluation.modifiers:
            await session.execute(
                insert(OrderItemModifier),
                [
                    {
                        "order_item_id": item_id,
                        "modifier_id": m.modifier_id,
                        "group_name": m.group_name or "",
                        "modifier_name": m.name,
                        "quantity": m.quantity,
                        "unit_price": m.unit_price,
                        "total_price": m.unit_price * m.quantity,
                    }
                    for m in evaluation.modifiers
                ],
            )

    if payload.delivery_type == "delivery":
        assert calc.zone is not None  # noqa: S101 - checked by calculate()
        await session.execute(
            insert(Delivery).values(
                order_id=order.id,
                delivery_zone_id=calc.zone.id,
                delivery_comment=delivery_comment,
            )
        )
        if payload.save_address and payload.address is not None:
            await create_address(
                session,
                user_id,
                AddressCreate.model_validate(payload.address.model_dump()),
                commit=False,
            )

    # Payment `pending` (DEC-43, DEC-44, DEC-78, §8.2, DEC-148, DEC-149).
    await add_attempt(
        session,
        order_id=order.id,
        method_id=method_id,
        method_code=method_code,
        amount=calc.total,
    )
    await record_initial_status(session, order_id=order.id, customer_id=user_id, changed_by=user_id)
    assert calc.cart.cart_id is not None  # noqa: S101 - the cart is not empty
    await empty_cart(session, calc.cart.cart_id)

    body = OrderCreated(
        id=order.id,
        order_number=order.order_number,
        status=OrderStatus.PENDING.value,
        delivery_type=payload.delivery_type,
        payment_method_code=method_code,
        payment_status=PaymentStatus.PENDING.value,
        payment_due_at=order.payment_due_at,
        subtotal=calc.subtotal,
        delivery_fee=calc.delivery_fee,
        total_amount=calc.total,
        currency="KGS",
        created_at=order.created_at,
    ).model_dump(mode="json")
    await idempotency.finish(session, key_id, status=CREATED, body=body)
    await session.commit()
    return CreateResult(CREATED, body, replayed=False)
