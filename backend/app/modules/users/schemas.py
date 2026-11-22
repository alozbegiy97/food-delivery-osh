"""Request schemas of `/users/me` (API_SPECIFICATION.md §4, DEC-152 п. 9).

Field rules are those of registration (DEC-141): `full_name` stripped,
1-150 Unicode characters without control characters; `phone` normalized
(DEC-89); `preferred_language` one of `ru` / `ky` / `uz`. The response is
`MeResponse`, the body of `GET /auth/me`.
"""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from app.modules.auth.schemas import FullName, Phone


class ProfileUpdate(BaseModel):
    """Partial update; only these three fields exist.

    Email, roles, flags and anything else are unknown fields -> 422. An
    explicit null clears `phone` only; an empty body changes nothing.
    """

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    full_name: FullName | None = None
    phone: Phone = None
    preferred_language: Literal["ru", "ky", "uz"] | None = None

    @model_validator(mode="after")
    def _required_values(self) -> Self:
        for name in ("full_name", "preferred_language"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} не может быть null")
        return self
