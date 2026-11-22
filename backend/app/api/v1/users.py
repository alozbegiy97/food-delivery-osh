"""`/users/me` (API_SPECIFICATION.md §4, DEC-152 п. 9).

Any authenticated user (Auth); while `must_change_password` is set the
request is refused like other protected routes (DEC-28). The body of both
operations is that of `GET /auth/me`. Thin layer.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.modules.auth.dependencies import CurrentUser, get_current_user
from app.modules.auth.schemas import MeResponse
from app.modules.users import profile
from app.modules.users.schemas import ProfileUpdate

router = APIRouter(prefix="/users/me", tags=["users"])

Session = Annotated[AsyncSession, Depends(get_session)]
User = Annotated[CurrentUser, Depends(get_current_user)]


@router.get("", response_model=MeResponse)
async def get_profile(user: User) -> MeResponse:
    return MeResponse.from_user(user)


@router.patch("", response_model=MeResponse)
async def update_profile(payload: ProfileUpdate, session: Session, user: User) -> MeResponse:
    return MeResponse.from_user(await profile.update_profile(session, user, payload))
