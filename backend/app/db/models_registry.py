"""Imports every ORM model so `Base.metadata` is complete for Alembic.

Add each new domain module here when its migration is introduced.
"""

from app.db.base import Base
from app.modules.cart import models as cart_models
from app.modules.catalog import models as catalog_models
from app.modules.delivery import models as delivery_models
from app.modules.notifications import models as notifications_models
from app.modules.orders import models as orders_models
from app.modules.payments import models as payments_models
from app.modules.restaurant import models as restaurant_models
from app.modules.users import models as users_models

__all__ = [
    "Base",
    "cart_models",
    "catalog_models",
    "delivery_models",
    "notifications_models",
    "orders_models",
    "payments_models",
    "restaurant_models",
    "users_models",
]
