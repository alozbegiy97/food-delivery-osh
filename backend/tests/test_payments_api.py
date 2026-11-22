"""Payments (stage 7; API §7; DATABASE_SCHEMA.md §8.2, §14.3, §14.5; DEC-43…DEC-47,
DEC-84, DEC-97, DEC-99, DEC-148, DEC-149).

Inside the rolled-back transaction of `api_client`. In one transaction
`now()` is constant, so deadlines are moved explicitly to test expiry.
"""

import uuid
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import func, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.core.errors import AppError
from app.modules.delivery.models import CourierAssignment
from app.modules.orders import events
from app.modules.orders.cancel import cancel_order
from app.modules.orders.models import CancellationRequest, Order, OrderStatusHistory
from app.modules.orders.status import Actor, change_status
from app.modules.payments.models import Payment, PaymentMethod
from app.modules.payments.timeouts import cancel_expired_orders
from app.modules.users.enums import RoleName
from app.modules.users.models import User
from tests.orders_support import API, Clock, add_kompot, error, key, make_user, ok, order_body

pytestmark = pytest.mark.db

CONFIRM = f"{API}/payments/mock/confirm"


async def _mock_order(client: httpx.AsyncClient, conn: AsyncConnection, headers: dict) -> dict:
    await add_kompot(client, conn, headers, 3)  # 420 pickup
    return ok(
        await client.post(
            f"{API}/orders",
            json=order_body("420.00", payment_method_code="mock_card"),
            headers=headers | key(),
        ),
        201,
    )


async def _attempts(conn: AsyncConnection, order_id: str) -> list:
    return (
        await conn.execute(
            select(Payment)
            .where(Payment.order_id == order_id)
            .order_by(Payment.created_at, Payment.id)
        )
    ).all()


async def _pending_attempt(conn: AsyncConnection, order_id: str) -> str:
    return str(
        await conn.scalar(
            select(Payment.id).where(Payment.order_id == order_id, Payment.status == "pending")
        )
    )


async def _confirm(
    client: httpx.AsyncClient, headers: dict, order_id: str, attempt_id: str, outcome: str
):
    return await client.post(
        CONFIRM,
        json={"order_id": order_id, "attempt_id": attempt_id, "outcome": outcome},
        headers=headers,
    )


async def _expire(conn: AsyncConnection, order_id: str) -> None:
    await conn.execute(
        update(Order)
        .where(Order.id == order_id)
        .values(payment_due_at=func.now() - text("interval '1 minute'"))
    )


def _savepoint_factory(conn: AsyncConnection):  # noqa: ANN202
    return lambda: AsyncSession(
        bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
    )


# --------------------------------------------------------------------------
# Methods and order creation
# --------------------------------------------------------------------------


async def test_payment_methods_are_public_and_only_active(
    api_client: httpx.AsyncClient, demo: AsyncConnection
) -> None:
    body = ok(await api_client.get(f"{API}/payment-methods"))
    assert [m["code"] for m in body["items"]] == ["cash", "mock_card"]
    await demo.execute(
        update(PaymentMethod).where(PaymentMethod.code == "mock_card").values(is_active=False)
    )
    assert [m["code"] for m in ok(await api_client.get(f"{API}/payment-methods"))["items"]] == [
        "cash"
    ]


async def test_mock_card_order_creates_a_simulated_attempt_with_deadline(
    api_client: httpx.AsyncClient, demo: AsyncConnection, customer: dict, clock: Clock
) -> None:
    created = await _mock_order(api_client, demo, customer)
    assert created["payment_method_code"] == "mock_card"
    assert created["payment_status"] == "pending"
    due = datetime.fromisoformat(created["payment_due_at"])
    made = datetime.fromisoformat(created["created_at"])
    assert (due - made).total_seconds() == 30 * 60  # DEC-97, PAYMENT_TIMEOUT_MINUTES
    [attempt] = await _attempts(demo, created["id"])
    assert (attempt.status, attempt.is_simulated, attempt.amount, attempt.currency) == (
        "pending",
        True,
        attempt.amount,
        "KGS",
    )
    assert str(attempt.amount) == "420.00"
    assert attempt.transaction_reference.startswith("MOCK-")
    detail = ok(await api_client.get(f"{API}/orders/{created['id']}", headers=customer))
    assert detail["payments"][0]["id"] == str(attempt.id)
    assert detail["payments"][0]["is_simulated"] is True


async def test_cash_is_unchanged_and_inactive_methods_are_refused(
    api_client: httpx.AsyncClient, demo: AsyncConnection, customer: dict, clock: Clock
) -> None:
    await add_kompot(api_client, demo, customer, 3)
    created = ok(
        await api_client.post(f"{API}/orders", json=order_body("420.00"), headers=customer | key()),
        201,
    )
    assert created["payment_due_at"] is None
    [attempt] = await _attempts(demo, created["id"])
    assert (attempt.status, attempt.is_simulated, attempt.transaction_reference) == (
        "pending",
        False,
        None,
    )
    # Cash cannot be "confirmed" by the mock endpoint.
    error(
        await _confirm(api_client, customer, created["id"], str(attempt.id), "success"),
        409,
        "PAYMENT_NOT_ALLOWED",
    )

    await demo.execute(
        update(PaymentMethod).where(PaymentMethod.code == "mock_card").values(is_active=False)
    )
    await add_kompot(api_client, demo, customer, 3)
    body = error(
        await api_client.post(
            f"{API}/orders",
            json=order_body("420.00", payment_method_code="mock_card"),
            headers=customer | key(),
        ),
        422,
        "VALIDATION_ERROR",
    )
    assert body["details"][0]["field"] == "payment_method_code"


# --------------------------------------------------------------------------
# Confirmation
# --------------------------------------------------------------------------


async def test_failure_then_retry_then_success(
    api_client: httpx.AsyncClient, demo: AsyncConnection, customer: dict, clock: Clock
) -> None:
    created = await _mock_order(api_client, demo, customer)
    first = await _pending_attempt(demo, created["id"])

    failed = ok(await _confirm(api_client, customer, created["id"], first, "failure"))
    assert failed["attempt"]["id"] == first and failed["attempt"]["status"] == "failed"
    assert failed["order_status"] == "pending"
    assert failed["payment_status"] == "pending"  # the next attempt waits
    # Both attempts are created inside the single test transaction, so their
    # created_at is equal and the list order is arbitrary: identify them by id.
    attempts = {str(a.id): a for a in await _attempts(demo, created["id"])}
    assert len(attempts) == 2 and attempts[first].status == "failed"
    [retry] = [a for a_id, a in attempts.items() if a_id != first]
    assert retry.status == "pending"  # the next attempt (DEC-46, DEC-99)
    assert retry.transaction_reference != attempts[first].transaction_reference

    # The same request again (lost response): stored result, no third attempt.
    again = ok(await _confirm(api_client, customer, created["id"], first, "failure"))
    assert again["attempt"] == failed["attempt"]
    assert len(await _attempts(demo, created["id"])) == 2
    # A finished attempt cannot be turned into a success.
    error(
        await _confirm(api_client, customer, created["id"], first, "success"),
        409,
        "PAYMENT_NOT_ALLOWED",
    )

    second = str(retry.id)
    paid = ok(await _confirm(api_client, customer, created["id"], second, "success"))
    assert paid["attempt"]["status"] == "succeeded" and paid["attempt"]["paid_at"]
    assert paid["payment_status"] == "succeeded"
    assert paid["payment_due_at"] is None  # DEC-97
    assert paid["order_status"] == "pending"  # waits for the staff (stage 8)

    # Repeated success: current state, nothing changes (DEC-149 В6).
    repeat = ok(await _confirm(api_client, customer, created["id"], second, "success"))
    assert repeat["attempt"] == paid["attempt"]
    # Success with the old failed attempt of a paid order: current state too.
    ok(await _confirm(api_client, customer, created["id"], first, "success"))
    # Failure after a successful payment is refused.
    error(
        await _confirm(api_client, customer, created["id"], second, "failure"),
        409,
        "PAYMENT_NOT_ALLOWED",
    )
    statuses = {str(a.id): a.status for a in await _attempts(demo, created["id"])}
    assert statuses == {first: "failed", second: "succeeded"}
    assert list(statuses.values()).count("succeeded") == 1


async def test_confirmation_is_refused_when_not_allowed(
    api_client: httpx.AsyncClient, demo: AsyncConnection, customer: dict, clock: Clock
) -> None:
    created = await _mock_order(api_client, demo, customer)
    attempt = await _pending_attempt(demo, created["id"])

    # Card data or any extra field is rejected (DEC-47).
    for extra in ({"card_number": "4111111111111111"}, {"cvv": "123"}, {"amount": "1.00"}):
        error(
            await api_client.post(
                CONFIRM,
                json={
                    "order_id": created["id"],
                    "attempt_id": attempt,
                    "outcome": "success",
                    **extra,
                },
                headers=customer,
            ),
            422,
            "VALIDATION_ERROR",
        )
    error(
        await _confirm(api_client, customer, created["id"], attempt, "maybe"),
        422,
        "VALIDATION_ERROR",
    )
    # Another customer's order and an unknown attempt are not found.
    other = await make_user(demo, RoleName.CUSTOMER.value)
    error(await _confirm(api_client, other, created["id"], attempt, "success"), 404, "NOT_FOUND")
    error(
        await _confirm(api_client, customer, created["id"], str(uuid.uuid4()), "success"),
        404,
        "NOT_FOUND",
    )
    error(await api_client.post(CONFIRM, json={}), 401, "UNAUTHORIZED")

    # The deadline has passed: no payment any more.
    await _expire(demo, created["id"])
    error(
        await _confirm(api_client, customer, created["id"], attempt, "success"),
        409,
        "PAYMENT_NOT_ALLOWED",
    )
    error(
        await _confirm(api_client, customer, created["id"], attempt, "failure"),
        409,
        "PAYMENT_NOT_ALLOWED",
    )
    assert [a.status for a in await _attempts(demo, created["id"])] == ["pending"]


async def test_payment_required_before_confirmation(
    api_client: httpx.AsyncClient, demo: AsyncConnection, customer: dict, clock: Clock
) -> None:
    created = await _mock_order(api_client, demo, customer)
    order_id = uuid.UUID(created["id"])
    async with AsyncSession(bind=demo, join_transaction_mode="create_savepoint") as session:
        with pytest.raises(AppError) as info:
            await change_status(session, order_id, "confirmed", Actor.ADMIN, actor_id=None)
        assert info.value.code == "PAYMENT_REQUIRED"  # DEC-45
    ok(
        await _confirm(
            api_client,
            customer,
            created["id"],
            await _pending_attempt(demo, created["id"]),
            "success",
        )
    )
    async with AsyncSession(bind=demo, join_transaction_mode="create_savepoint") as session:
        await change_status(session, order_id, "confirmed", Actor.ADMIN, actor_id=None)
        await session.commit()
    assert await demo.scalar(select(Order.status).where(Order.id == order_id)) == "confirmed"


# --------------------------------------------------------------------------
# Timeout job and the single cancellation operation
# --------------------------------------------------------------------------


async def test_timeout_cancels_only_expired_unpaid_orders(
    api_client: httpx.AsyncClient, demo: AsyncConnection, customer: dict, clock: Clock
) -> None:
    unpaid = await _mock_order(api_client, demo, customer)
    paid = await _mock_order(api_client, demo, customer)
    fresh = await _mock_order(api_client, demo, customer)
    await add_kompot(api_client, demo, customer, 3)
    cash = ok(
        await api_client.post(f"{API}/orders", json=order_body("420.00"), headers=customer | key()),
        201,
    )
    ok(
        await _confirm(
            api_client, customer, paid["id"], await _pending_attempt(demo, paid["id"]), "success"
        )
    )
    # A cancellation request waiting for the staff is approved by the operation (§14.3).
    ok(
        await api_client.post(
            f"{API}/orders/{unpaid['id']}/cancellation-requests",
            json={"reason": "долго"},
            headers=customer,
        ),
        201,
    )
    for order in (unpaid, paid, cash):
        await _expire(demo, order["id"])  # cash and paid have no deadline in reality; still ignored

    seen: list[events.OrderStatusChanged] = []

    async def handler(_: AsyncSession, event: events.OrderStatusChanged) -> None:
        seen.append(event)

    events.subscribe(handler)
    try:
        run = await cancel_expired_orders(_savepoint_factory(demo), batch_size=50)
        repeat = await cancel_expired_orders(_savepoint_factory(demo), batch_size=50)
    finally:
        events.unsubscribe(handler)

    assert [str(i) for i in run.cancelled] == [unpaid["id"]] and run.failed == []
    assert repeat.cancelled == [] and repeat.failed == []  # nothing happens twice
    rows = dict((await demo.execute(select(Order.id, Order.status))).all())
    assert rows[uuid.UUID(unpaid["id"])] == "cancelled"
    assert rows[uuid.UUID(paid["id"])] == "pending"
    assert rows[uuid.UUID(fresh["id"])] == "pending"
    assert rows[uuid.UUID(cash["id"])] == "pending"

    order = (await demo.execute(select(Order).where(Order.id == unpaid["id"]))).one()
    assert order.cancellation_reason_code == "payment_timeout" and order.cancelled_at is not None
    assert [a.status for a in await _attempts(demo, unpaid["id"])] == ["cancelled"]
    history = (
        await demo.execute(
            select(
                OrderStatusHistory.old_status,
                OrderStatusHistory.new_status,
                OrderStatusHistory.comment,
                OrderStatusHistory.changed_by,
            ).where(
                OrderStatusHistory.order_id == unpaid["id"],
                OrderStatusHistory.new_status == "cancelled",
            )
        )
    ).all()
    assert history == [("pending", "cancelled", "payment_timeout", None)]
    request = await demo.scalar(
        select(CancellationRequest.status).where(CancellationRequest.order_id == unpaid["id"])
    )
    assert request == "approved"
    assert [(e.old_status, e.new_status, e.changed_by) for e in seen] == [
        ("pending", "cancelled", None)
    ]

    # The customer sees the reason; the cancelled order cannot be paid.
    detail = ok(await api_client.get(f"{API}/orders/{unpaid['id']}", headers=customer))
    assert detail["cancellation_reason_code"] == "payment_timeout"
    assert detail["payment_status"] == "cancelled"
    attempt = str((await _attempts(demo, unpaid["id"]))[0].id)
    error(
        await _confirm(api_client, customer, unpaid["id"], attempt, "success"),
        409,
        "PAYMENT_NOT_ALLOWED",
    )


async def test_timeout_respects_the_batch_size(
    api_client: httpx.AsyncClient, demo: AsyncConnection, customer: dict, clock: Clock
) -> None:
    orders = [await _mock_order(api_client, demo, customer) for _ in range(3)]
    for order in orders:
        await _expire(demo, order["id"])
    first = await cancel_expired_orders(_savepoint_factory(demo), batch_size=2)
    second = await cancel_expired_orders(_savepoint_factory(demo), batch_size=2)
    assert len(first.cancelled) == 2 and len(second.cancelled) == 1


async def test_cancel_operation_refunds_and_releases_courier(
    api_client: httpx.AsyncClient, demo: AsyncConnection, customer: dict, clock: Clock
) -> None:
    created = await _mock_order(api_client, demo, customer)
    ok(
        await _confirm(
            api_client,
            customer,
            created["id"],
            await _pending_attempt(demo, created["id"]),
            "success",
        )
    )
    courier = await demo.scalar(
        insert(User)
        .values(email=f"{uuid.uuid4().hex}@example.com", password_hash="x", full_name="Курьер")
        .returning(User.id)
    )
    await demo.execute(
        insert(CourierAssignment).values(
            order_id=created["id"],
            courier_id=courier,
            assignment_type="manual",
            status="active",
            assigned_at=datetime.now(UTC),
        )
    )
    order_id = uuid.UUID(created["id"])
    async with AsyncSession(bind=demo, join_transaction_mode="create_savepoint") as session:
        with pytest.raises(AppError) as info:  # DEC-132: a reason is required
            await cancel_order(
                session,
                order_id,
                reason_code="admin_decision",
                comment=" ",
                actor=Actor.ADMIN,
                actor_id=None,
            )
        assert info.value.code == "VALIDATION_ERROR"
        with pytest.raises(
            AppError
        ) as info:  # the system cancels only unpaid orders... of mock type
            await cancel_order(
                session,
                order_id,
                reason_code="payment_timeout",
                comment="x",
                actor=Actor.COOK,
                actor_id=None,
            )
        assert info.value.code == "FORBIDDEN"
        result = await cancel_order(
            session,
            order_id,
            reason_code="admin_decision",
            comment="Нет продуктов",
            actor=Actor.ADMIN,
            actor_id=None,
        )
        assert result.changed is True
        again = await cancel_order(
            session,
            order_id,
            reason_code="admin_decision",
            comment="ещё раз",
            actor=Actor.ADMIN,
            actor_id=None,
        )
        assert again.changed is False  # idempotent: no second refund or history row
        await session.commit()

    [payment] = await _attempts(demo, created["id"])
    assert payment.status == "refunded" and payment.refunded_at is not None  # simulated (DEC-40)
    assert await demo.scalar(select(CourierAssignment.status)) == "cancelled"  # DEC-41
    cancelled_rows = await demo.scalar(
        select(func.count())
        .select_from(OrderStatusHistory)
        .where(
            OrderStatusHistory.order_id == order_id, OrderStatusHistory.new_status == "cancelled"
        )
    )
    assert cancelled_rows == 1
