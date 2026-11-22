from enum import StrEnum


class NotificationType(StrEnum):
    """Notification / Telegram event types of v1 (DEC-126).

    Single source of values for the CHECK on `notifications.type` and on
    `telegram_outbox.event_type`. A new type requires a new DEC and a
    migration that changes both CHECKs.
    """

    ORDER_STATUS_CHANGED = "order_status_changed"
    CANCELLATION_REQUEST_APPROVED = "cancellation_request_approved"
    CANCELLATION_REQUEST_REJECTED = "cancellation_request_rejected"


class TelegramOutboxStatus(StrEnum):
    """`telegram_outbox.status` (DATABASE_SCHEMA.md §11.4). Transitions: worker."""

    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"
