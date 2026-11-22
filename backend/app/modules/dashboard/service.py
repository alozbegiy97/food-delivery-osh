"""Dashboard metrics (API §9; DEC-90, DEC-111, DEC-114).

- orders: `created_at` in the period; only mock orders cancelled by
  `payment_timeout` are excluded (cancelled/rejected/unpaid ones count);
- revenue: Σ `total_amount` of `completed` orders with `completed_at` in the
  period; average check = revenue / their number, 2 places, "0.00" if none;
- active orders: now, in `confirmed`…`out_for_delivery`, period-independent;
- chart: per local day `{date, orders_created, revenue}`, missing days = 0;
- top products: top 10 by Σ quantity in completed orders of the period,
  grouped by `product_id`, name from the latest such order's snapshot;
- all day boundaries in Asia/Bishkek (app.core.periods).
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.periods import Period, make_period
from app.modules.orders.enums import CancellationReasonCode, OrderStatus
from app.modules.orders.models import Order, OrderItem

ZERO = Decimal("0.00")
ACTIVE = (
    OrderStatus.CONFIRMED,
    OrderStatus.PREPARING,
    OrderStatus.READY_FOR_PICKUP,
    OrderStatus.OUT_FOR_DELIVERY,
)
LOCAL_TZ = "Asia/Bishkek"


class PeriodOut(BaseModel):
    date_from: date
    date_to: date


class SummaryOut(BaseModel):
    period: PeriodOut
    orders_count: int
    revenue: Decimal
    average_check: Decimal
    active_orders: int
    currency: str = "KGS"


class ChartPoint(BaseModel):
    date: date
    orders_created: int
    revenue: Decimal


class ChartOut(BaseModel):
    period: PeriodOut
    points: list[ChartPoint]


class TopProduct(BaseModel):
    product_id: str | None
    product_name: str
    quantity: int


class TopProductsOut(BaseModel):
    period: PeriodOut
    items: list[TopProduct]


def _counted():  # noqa: ANN202 - SQL condition (DEC-90)
    return or_(
        Order.cancellation_reason_code.is_(None),
        Order.cancellation_reason_code != CancellationReasonCode.PAYMENT_TIMEOUT,
    )


def _created_in(period: Period):  # noqa: ANN202
    return and_(Order.created_at >= period.start, Order.created_at < period.end, _counted())


def _completed_in(period: Period):  # noqa: ANN202
    return and_(
        Order.status == OrderStatus.COMPLETED,
        Order.completed_at >= period.start,
        Order.completed_at < period.end,
    )


def _period_out(period: Period) -> PeriodOut:
    return PeriodOut(date_from=period.date_from, date_to=period.date_to)


async def summary(
    session: AsyncSession, date_from: date | None, date_to: date | None
) -> SummaryOut:
    period = make_period(date_from, date_to)
    orders = int(
        await session.scalar(select(func.count()).select_from(Order).where(_created_in(period)))
        or 0
    )
    revenue, completed = (
        await session.execute(
            select(func.coalesce(func.sum(Order.total_amount), 0), func.count()).where(
                _completed_in(period)
            )
        )
    ).one()
    revenue = Decimal(revenue).quantize(ZERO)
    average = (revenue / completed).quantize(ZERO, rounding=ROUND_HALF_UP) if completed else ZERO
    active = int(
        await session.scalar(
            select(func.count()).select_from(Order).where(Order.status.in_(ACTIVE))
        )
        or 0
    )
    return SummaryOut(
        period=_period_out(period),
        orders_count=orders,
        revenue=revenue,
        average_check=average,
        active_orders=active,
    )


def _local_day(column):  # noqa: ANN001, ANN202
    return func.date(func.timezone(LOCAL_TZ, column))


async def chart(session: AsyncSession, date_from: date | None, date_to: date | None) -> ChartOut:
    period = make_period(date_from, date_to)
    created_day = _local_day(Order.created_at).label("day")
    created = dict(
        (
            await session.execute(
                select(created_day, func.count()).where(_created_in(period)).group_by(created_day)
            )
        ).all()
    )
    completed_day = _local_day(Order.completed_at).label("day")
    revenue = dict(
        (
            await session.execute(
                select(completed_day, func.sum(Order.total_amount))
                .where(_completed_in(period))
                .group_by(completed_day)
            )
        ).all()
    )
    return ChartOut(
        period=_period_out(period),
        points=[
            ChartPoint(
                date=day,
                orders_created=int(created.get(day, 0)),
                revenue=Decimal(revenue.get(day, 0)).quantize(ZERO),
            )
            for day in period.days()
        ],
    )


async def top_products(
    session: AsyncSession, date_from: date | None, date_to: date | None
) -> TopProductsOut:
    period = make_period(date_from, date_to)
    totals = (
        await session.execute(
            select(OrderItem.product_id, func.sum(OrderItem.quantity).label("quantity"))
            .join(Order, Order.id == OrderItem.order_id)
            .where(_completed_in(period))
            .group_by(OrderItem.product_id)
            .order_by(func.sum(OrderItem.quantity).desc(), OrderItem.product_id)
            .limit(10)
        )
    ).all()
    items = []
    for product_id, quantity in totals:
        # Name from the snapshot of the latest such order (DEC-111).
        name_query = (
            select(OrderItem.product_name)
            .join(Order, Order.id == OrderItem.order_id)
            .where(_completed_in(period))
            .order_by(Order.completed_at.desc(), Order.id.desc())
            .limit(1)
        )
        name_query = (
            name_query.where(OrderItem.product_id == product_id)
            if product_id is not None
            else name_query.where(OrderItem.product_id.is_(None))
        )
        items.append(
            TopProduct(
                product_id=str(product_id) if product_id else None,
                product_name=await session.scalar(name_query) or "",
                quantity=int(quantity),
            )
        )
    return TopProductsOut(period=_period_out(period), items=items)
