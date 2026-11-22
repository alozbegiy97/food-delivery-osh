from enum import StrEnum


class RoleName(StrEnum):
    """Roles seeded in `roles.name` (DATABASE_SCHEMA.md §3.2)."""

    CUSTOMER = "customer"
    ADMIN = "admin"
    COOK = "cook"
    COURIER = "courier"
