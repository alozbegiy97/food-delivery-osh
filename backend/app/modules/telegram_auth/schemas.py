"""Request schemas of `/auth/telegram/webapp*` (API §2.3).

`init_data` has no length limit here on purpose (D5): any length problem is
part of the `initData` verification and answers `401 INVALID_TELEGRAM_AUTH`,
never 422. Unknown fields are rejected; error texts never echo input.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.modules.auth.schemas import AnyPassword


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, strict=True)


class WebAppAuthRequest(_Request):
    """`POST /auth/telegram/webapp` and `/register`."""

    init_data: str


class WebAppLinkRequest(_Request):
    """`POST /auth/telegram/webapp/link`; email and password as in `/auth/login`."""

    init_data: str
    email: Annotated[str, Field(min_length=1, max_length=1024)]
    password: AnyPassword
