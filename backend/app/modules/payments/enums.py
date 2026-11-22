from enum import StrEnum


class PaymentMethodCode(StrEnum):
    """Codes seeded in `payment_methods.code` (DATABASE_SCHEMA.md §8.1)."""

    CASH = "cash"
    MOCK_CARD = "mock_card"


class PaymentStatus(StrEnum):
    """`payments.status` (DATABASE_SCHEMA.md §8.2). Transitions: service layer."""

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUNDED = "refunded"
    CANCELLED = "cancelled"
