"""Kitchen responses: a NARROW schema by design (DEC-25, DEC-106, DEC-112).

No customer name, phone, address, customer comment, amounts or payment
data — these fields simply do not exist here, so they cannot leak.
Item wishes (`special_instructions`) are shown: the cook needs them.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel


class KitchenModifierOut(BaseModel):
    group_name: str
    modifier_name: str
    quantity: int


class KitchenItemOut(BaseModel):
    product_name: str
    variant_name: str
    quantity: int
    special_instructions: str | None
    modifiers: list[KitchenModifierOut]


class KitchenOrderOut(BaseModel):
    id: uuid.UUID
    order_number: str
    delivery_type: str
    status: str
    confirmed_at: datetime | None
    preparing_started_at: datetime | None
    items: list[KitchenItemOut]


class KitchenQueue(BaseModel):
    items: list[KitchenOrderOut]
