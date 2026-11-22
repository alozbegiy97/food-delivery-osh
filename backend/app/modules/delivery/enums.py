from enum import StrEnum


class AssignmentType(StrEnum):
    """`courier_assignments.assignment_type` (DATABASE_SCHEMA.md §9.3)."""

    MANUAL = "manual"
    AUTOMATIC = "automatic"


class AssignmentStatus(StrEnum):
    """`courier_assignments.status` (§9.3). Transitions: service layer."""

    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    DECLINED = "declined"
