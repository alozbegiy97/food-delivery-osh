from enum import StrEnum


class SelectionType(StrEnum):
    """`modifier_groups.selection_type` (DATABASE_SCHEMA.md §5.1)."""

    SINGLE = "single"
    MULTIPLE = "multiple"
