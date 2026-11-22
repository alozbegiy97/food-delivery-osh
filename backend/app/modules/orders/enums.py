from enum import StrEnum


class OrderStatus(StrEnum):
    """Order statuses of v1 (DATABASE_SCHEMA.md §7.1). Transitions: service layer."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    PREPARING = "preparing"
    READY_FOR_PICKUP = "ready_for_pickup"
    OUT_FOR_DELIVERY = "out_for_delivery"
    COMPLETED = "completed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class DeliveryType(StrEnum):
    DELIVERY = "delivery"
    PICKUP = "pickup"


class CancellationReasonCode(StrEnum):
    """`orders.cancellation_reason_code` (DEC-82, DEC-84, DEC-98)."""

    CUSTOMER_REQUEST = "customer_request"
    ADMIN_DECISION = "admin_decision"
    PAYMENT_TIMEOUT = "payment_timeout"


class CancellationRequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class IdempotencyScope(StrEnum):
    """`idempotency_keys.scope` values used by the service (§14.2, DEC-109)."""

    CREATE_ORDER = "create_order"


# Statuses that require a non-empty history comment (DEC-132).
STATUSES_REQUIRING_COMMENT = (OrderStatus.REJECTED, OrderStatus.CANCELLED)
CURRENCY_KGS = "KGS"
