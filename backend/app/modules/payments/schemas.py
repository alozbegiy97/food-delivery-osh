"""Payment requests and responses (API_SPECIFICATION.md §7, DEC-47, DEC-149).

No card data is ever accepted: the mock confirmation carries only the order,
the attempt and the simulated outcome (extra fields -> 422).
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict


class PaymentMethodOut(BaseModel):
    code: str
    sort_order: int


class PaymentMethodList(BaseModel):
    items: list[PaymentMethodOut]


class MockConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: uuid.UUID
    # The payments row being confirmed (DEC-149): a repeat with the same id
    # returns the stored result instead of creating a new attempt.
    attempt_id: uuid.UUID
    outcome: Literal["success", "failure"]


class AttemptOut(BaseModel):
    id: uuid.UUID
    status: str
    transaction_reference: str | None
    amount: Decimal
    currency: str
    created_at: datetime
    paid_at: datetime | None


class MockConfirmOut(BaseModel):
    order_id: uuid.UUID
    order_status: str
    # Payment status of the order: succeeded > pending > latest attempt.
    payment_status: str
    payment_due_at: datetime | None
    attempt: AttemptOut
