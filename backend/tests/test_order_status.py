"""Order state machine (stage 6; DATABASE_SCHEMA.md §7.1, §14.3; DEC-30…DEC-37,
DEC-45, DEC-79, DEC-83, DEC-91, DEC-132, DEC-148).

Unit tests walk the whole table: every (from, to, actor, order type) pair is
either allowed exactly as §7.1 says or refused. A database test applies one
transition and checks the history row and the domain event.
"""

import itertools
import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.core.errors import AppError
from app.modules.orders import events
from app.modules.orders.enums import OrderStatus
from app.modules.orders.models import Order, OrderStatusHistory
from app.modules.orders.status import (
    Actor,
    DeferredTransitionError,
    OrderState,
    TransitionContext,
    change_status,
    check_transition,
)
from tests.orders_support import API, Clock, add_kompot, ok, order_body
from tests.orders_support import key as idem_key

S = OrderStatus
COURIER = uuid.uuid4()
CONTEXT = TransitionContext(
    has_succeeded_payment=True, active_courier_id=COURIER, assignment_accepted=True
)

# §7.1, written out independently of the implementation:
# (from, to, actor, delivery types, admin override)
EXPECTED = {
    (S.PENDING, S.CONFIRMED, Actor.ADMIN, ("delivery", "pickup"), False),
    (S.PENDING, S.REJECTED, Actor.ADMIN, ("delivery", "pickup"), False),
    (S.CONFIRMED, S.PREPARING, Actor.COOK, ("delivery", "pickup"), False),
    (S.CONFIRMED, S.PREPARING, Actor.ADMIN, ("delivery", "pickup"), False),
    (S.PREPARING, S.READY_FOR_PICKUP, Actor.COOK, ("delivery", "pickup"), False),
    (S.PREPARING, S.READY_FOR_PICKUP, Actor.ADMIN, ("delivery", "pickup"), False),
    (S.READY_FOR_PICKUP, S.OUT_FOR_DELIVERY, Actor.COURIER, ("delivery",), False),
    (S.READY_FOR_PICKUP, S.OUT_FOR_DELIVERY, Actor.ADMIN, ("delivery",), True),
    (S.OUT_FOR_DELIVERY, S.COMPLETED, Actor.COURIER, ("delivery",), False),
    (S.OUT_FOR_DELIVERY, S.COMPLETED, Actor.ADMIN, ("delivery",), True),
    (S.READY_FOR_PICKUP, S.COMPLETED, Actor.ADMIN, ("pickup",), False),
    (S.PENDING, S.CANCELLED, Actor.ADMIN, ("delivery", "pickup"), False),
    (S.PENDING, S.CANCELLED, Actor.SYSTEM, ("delivery", "pickup"), False),
    (S.CONFIRMED, S.CANCELLED, Actor.ADMIN, ("delivery", "pickup"), False),
    (S.PREPARING, S.CANCELLED, Actor.ADMIN, ("delivery", "pickup"), False),
    (S.READY_FOR_PICKUP, S.CANCELLED, Actor.ADMIN, ("delivery", "pickup"), False),
}
ALLOWED = {
    (old, new, actor, kind): override
    for old, new, actor, kinds, override in EXPECTED
    for kind in kinds
}


def _payment_for(actor: Actor) -> str:
    # The system cancels only unpaid mock_card orders (DEC-84).
    return "mock_card" if actor == Actor.SYSTEM else "cash"


@pytest.mark.parametrize(
    ("old", "new", "actor", "kind"),
    [
        (old, new, actor, kind)
        for old, new in itertools.product(S, S)
        for actor in Actor
        for kind in ("delivery", "pickup")
    ],
)
def test_transition_table(old: S, new: S, actor: Actor, kind: str) -> None:
    state = OrderState(old.value, kind, _payment_for(actor))
    expected = ALLOWED.get((old, new, actor, kind))
    attempt = lambda: check_transition(  # noqa: E731
        state, new.value, actor, actor_id=COURIER, comment="причина", context=CONTEXT
    )
    if expected is None:
        with pytest.raises(AppError) as info:
            attempt()
        assert info.value.code in {"INVALID_STATUS_TRANSITION", "FORBIDDEN"}
    else:
        plan = attempt()
        assert (plan.old_status, plan.new_status) == (old.value, new.value)
        assert plan.is_admin_override is expected


def test_terminal_statuses_have_no_way_out() -> None:
    for old in (S.COMPLETED, S.REJECTED, S.CANCELLED, S.OUT_FOR_DELIVERY):
        with pytest.raises(AppError):
            check_transition(
                OrderState(old.value, "delivery", "cash"),
                S.CANCELLED.value,
                Actor.ADMIN,
                comment="x",
                context=CONTEXT,
            )


def _code(callable_) -> str:  # noqa: ANN001
    with pytest.raises(AppError) as info:
        callable_()
    return info.value.code


def test_conditions_of_transitions() -> None:
    cash = OrderState("pending", "delivery", "cash")
    card = OrderState("pending", "delivery", "mock_card")
    # Comment required for rejected/cancelled (DEC-132) and admin overrides (DEC-91).
    for new in ("rejected", "cancelled"):
        assert _code(lambda new=new: check_transition(cash, new, Actor.ADMIN, comment=" ")) == (
            "VALIDATION_ERROR"
        )
    ready = OrderState("ready_for_pickup", "delivery", "cash")
    assert (
        _code(lambda: check_transition(ready, "out_for_delivery", Actor.ADMIN, context=CONTEXT))
        == "VALIDATION_ERROR"
    )
    # mock_card is confirmed only after a successful payment (DEC-45).
    assert _code(lambda: check_transition(card, "confirmed", Actor.ADMIN)) == "PAYMENT_REQUIRED"
    check_transition(card, "confirmed", Actor.ADMIN, context=CONTEXT)
    # The system never cancels a cash order (DEC-84).
    assert _code(lambda: check_transition(cash, "cancelled", Actor.SYSTEM, comment="x")) == (
        "FORBIDDEN"
    )
    # Courier: own active assignment, accepted before pickup (DEC-36, DEC-83).
    other = uuid.uuid4()
    no_assignment = TransitionContext()
    not_accepted = TransitionContext(active_courier_id=COURIER, assignment_accepted=False)
    assert (
        _code(
            lambda: check_transition(
                ready, "out_for_delivery", Actor.COURIER, actor_id=COURIER, context=no_assignment
            )
        )
        == "INVALID_STATUS_TRANSITION"
    )
    assert (
        _code(
            lambda: check_transition(
                ready, "out_for_delivery", Actor.COURIER, actor_id=other, context=CONTEXT
            )
        )
        == "FORBIDDEN"
    )
    assert (
        _code(
            lambda: check_transition(
                ready, "out_for_delivery", Actor.COURIER, actor_id=COURIER, context=not_accepted
            )
        )
        == "ASSIGNMENT_NOT_ACCEPTED"
    )
    # Admin override needs an active assignment, not acceptance (DEC-91).
    check_transition(
        ready, "out_for_delivery", Actor.ADMIN, comment="курьер без телефона", context=not_accepted
    )
    on_the_way = OrderState("out_for_delivery", "delivery", "cash")
    assert (
        _code(
            lambda: check_transition(
                on_the_way, "completed", Actor.COURIER, actor_id=other, context=CONTEXT
            )
        )
        == "FORBIDDEN"
    )
    # Pickup orders never go out for delivery.
    pickup_ready = OrderState("ready_for_pickup", "pickup", "cash")
    assert (
        _code(
            lambda: check_transition(
                pickup_ready, "out_for_delivery", Actor.ADMIN, comment="x", context=CONTEXT
            )
        )
        == "INVALID_STATUS_TRANSITION"
    )


@pytest.mark.db
async def test_change_status_writes_history_and_publishes_event(
    api_client: httpx.AsyncClient,
    demo: AsyncConnection,
    customer: dict,
    clock: Clock,
) -> None:
    await add_kompot(api_client, demo, customer, 3)
    created = ok(
        await api_client.post(
            f"{API}/orders", json=order_body("420.00"), headers=customer | idem_key()
        ),
        201,
    )
    order_id = uuid.UUID(created["id"])
    seen: list[events.OrderStatusChanged] = []

    async def handler(_: AsyncSession, event: events.OrderStatusChanged) -> None:
        seen.append(event)

    events.subscribe(handler)
    try:
        async with AsyncSession(bind=demo, join_transaction_mode="create_savepoint") as session:
            plan = await change_status(session, order_id, "confirmed", Actor.ADMIN, actor_id=None)
            assert (plan.old_status, plan.new_status) == ("pending", "confirmed")
            with pytest.raises(AppError) as info:
                await change_status(session, order_id, "completed", Actor.ADMIN, actor_id=None)
            assert info.value.code == "INVALID_STATUS_TRANSITION"
            # Transitions that need later-stage side effects are not applied (DEC-148).
            with pytest.raises(DeferredTransitionError):
                await change_status(
                    session, order_id, "cancelled", Actor.ADMIN, actor_id=None, comment="тест"
                )
            await session.commit()  # releases the savepoint of the test transaction
    finally:
        events.unsubscribe(handler)

    status = await demo.scalar(select(Order.status).where(Order.id == order_id))
    assert status == "confirmed"
    history = (
        await demo.execute(
            select(OrderStatusHistory.old_status, OrderStatusHistory.new_status).where(
                OrderStatusHistory.order_id == order_id
            )
        )
    ).all()
    assert sorted(history, key=lambda h: h.old_status or "") == [
        (None, "pending"),
        ("pending", "confirmed"),
    ]
    assert [(e.old_status, e.new_status) for e in seen] == [("pending", "confirmed")]
    assert seen[0].order_id == order_id
