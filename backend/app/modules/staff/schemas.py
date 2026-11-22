"""Staff requests and responses (DEC-150: only the roles `cook` and `courier`)."""

import uuid
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.addresses.schemas import Pagination
from app.modules.auth.schemas import Email, FullName, NewPassword, Phone

StaffRole = Literal["cook", "courier"]
StaffRoles = Annotated[list[StaffRole], Field(min_length=1, max_length=2)]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _unique(roles: list[str]) -> None:
    if len(roles) != len(set(roles)):
        raise ValueError("каждая роль указывается один раз")


class StaffCreate(_In):
    email: Email
    full_name: FullName
    phone: Phone = None
    roles: StaffRoles
    # Password policy DEC-96; the employee must change it at first login (DEC-28).
    temporary_password: NewPassword

    @model_validator(mode="after")
    def _roles(self) -> Self:
        _unique(self.roles)
        return self


class StaffRolesUpdate(_In):
    roles: StaffRoles

    @model_validator(mode="after")
    def _roles(self) -> Self:
        _unique(self.roles)
        return self


class StaffOut(BaseModel):
    id: uuid.UUID
    email: str | None
    full_name: str
    phone: str | None
    # All roles of the user; only `cook`/`courier` are managed here.
    roles: list[str]
    is_active: bool
    must_change_password: bool
    created_at: datetime


class StaffList(BaseModel):
    items: list[StaffOut]
    pagination: Pagination
