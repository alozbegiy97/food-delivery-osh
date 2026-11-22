"""`/auth/telegram/webapp*` — Telegram Mini App (API §2.3; DEC-152, DEC-154).

Thin layer. Each endpoint returns only an access token: no refresh cookie
is set and no CSRF check applies (no cookie is used). Rate limits run as
dependencies, i.e. before any check of the body (DEC-152 п. 4):
`webapp` and `register` share `RATE_LIMIT_TELEGRAM_WEBAPP`; `link` shares
the `/auth/login` counter.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import login_rate_limit, telegram_webapp_rate_limit
from app.core.security import AccessToken, normalize_email
from app.db.session import get_session
from app.modules.auth.schemas import TokenResponse
from app.modules.telegram_auth import service
from app.modules.telegram_auth.schemas import WebAppAuthRequest, WebAppLinkRequest

router = APIRouter(prefix="/auth/telegram/webapp", tags=["auth", "telegram"])

Session = Annotated[AsyncSession, Depends(get_session)]


def _token(access: AccessToken) -> TokenResponse:
    return TokenResponse(access_token=access.token, expires_in=access.expires_in)


@router.post("", response_model=TokenResponse, dependencies=[Depends(telegram_webapp_rate_limit)])
async def webapp_login(data: WebAppAuthRequest, session: Session) -> TokenResponse:
    return _token(await service.login(session, data.init_data))


@router.post(
    "/register",
    response_model=TokenResponse,
    dependencies=[Depends(telegram_webapp_rate_limit)],
)
async def webapp_register(data: WebAppAuthRequest, session: Session) -> TokenResponse:
    return _token(await service.register(session, data.init_data))


@router.post("/link", response_model=TokenResponse, dependencies=[Depends(login_rate_limit)])
async def webapp_link(data: WebAppLinkRequest, session: Session) -> TokenResponse:
    return _token(
        await service.link(session, data.init_data, normalize_email(data.email), data.password)
    )
