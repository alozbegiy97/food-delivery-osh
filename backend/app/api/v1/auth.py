"""`/auth` endpoints (API_SPECIFICATION.md §2, DEC-140, DEC-141, DEC-142).

Thin layer: validation by schemas, rules in `app.modules.auth.service`.
Cookies are set or cleared only after the service returned, i.e. after its
COMMIT succeeded; on any exception the client gets an error without cookie
changes.
"""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.mailer import send_email
from app.core.rate_limit import forgot_allowed, login_rate_limit
from app.core.security import normalize_email
from app.db.session import get_session
from app.modules.auth import password_reset, service
from app.modules.auth.cookies import REFRESH_COOKIE_NAME, clear_refresh_cookie, set_refresh_cookie
from app.modules.auth.dependencies import (
    CurrentUser,
    csrf_protect,
    get_authenticated_user,
    get_current_user,
)
from app.modules.auth.schemas import (
    AcceptedResponse,
    CredentialsRequest,
    LoginRequest,
    MeResponse,
    PasswordChangeRequest,
    PasswordForgotRequest,
    PasswordResetRequest,
    RegisterRequest,
    TokenResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])

Session = Annotated[AsyncSession, Depends(get_session)]
RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)]


def _token_response(response: Response, issued: service.IssuedSession) -> TokenResponse:
    set_refresh_cookie(response, issued.refresh_token)
    return TokenResponse(access_token=issued.access.token, expires_in=issued.access.expires_in)


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=TokenResponse)
async def register(data: RegisterRequest, response: Response, session: Session) -> TokenResponse:
    issued = await service.register(session, data)
    return _token_response(response, issued)


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(login_rate_limit)])
async def login(data: LoginRequest, response: Response, session: Session) -> TokenResponse:
    issued = await service.login(session, normalize_email(data.email), data.password)
    return _token_response(response, issued)


@router.post("/refresh", response_model=TokenResponse, dependencies=[Depends(csrf_protect)])
async def refresh(
    response: Response, session: Session, refresh_token: RefreshCookie = None
) -> TokenResponse:
    issued = await service.refresh(session, refresh_token)
    return _token_response(response, issued)


@router.post(
    "/logout", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(csrf_protect)]
)
async def logout(response: Response, session: Session, refresh_token: RefreshCookie = None) -> None:
    await service.logout(session, refresh_token)
    clear_refresh_cookie(response)


@router.get("/me", response_model=MeResponse)
async def me(user: Annotated[CurrentUser, Depends(get_authenticated_user)]) -> MeResponse:
    return MeResponse.from_user(user)


@router.post("/credentials", status_code=status.HTTP_204_NO_CONTENT)
async def add_credentials(
    data: CredentialsRequest,
    session: Session,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> None:
    """Add email and password to a Telegram-only account (API §2.3, DEC-142)."""
    await service.add_credentials(session, user.id, data.email, data.password)


@router.post("/password/change", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    data: PasswordChangeRequest,
    response: Response,
    session: Session,
    user: Annotated[CurrentUser, Depends(get_authenticated_user)],
) -> None:
    await service.change_password(session, user.id, data.current_password, data.new_password)
    clear_refresh_cookie(response)


# Same body for every outcome: existing or not, active or not, limited or not.
_FORGOT_ACCEPTED = AcceptedResponse(message="Если аккаунт существует, мы отправили письмо")


@router.post(
    "/password/forgot", status_code=status.HTTP_202_ACCEPTED, response_model=AcceptedResponse
)
async def password_forgot(
    data: PasswordForgotRequest,
    request: Request,
    background: BackgroundTasks,
    session: Session,
) -> AcceptedResponse:
    email = normalize_email(data.email)
    if forgot_allowed(request, email):
        mail = await password_reset.request_reset(session, email)
        if mail is not None:
            background.add_task(send_email, mail.email)  # after the response
    return _FORGOT_ACCEPTED


@router.post("/password/reset", status_code=status.HTTP_204_NO_CONTENT)
async def password_reset_confirm(data: PasswordResetRequest, session: Session) -> None:
    await password_reset.reset_password(session, data.token, data.new_password)
