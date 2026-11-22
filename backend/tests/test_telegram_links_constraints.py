"""PostgreSQL constraints the Mini App service relies on (DATABASE_SCHEMA §11.2).

The service maps unique violations to API codes by constraint name; these
tests prove the names are the real ones, and that the database itself would
refuse a username longer than 100 characters (why U2 stores NULL instead).
Every test runs in a rolled-back transaction (`db_session`).
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from app.modules.notifications.models import TelegramLink
from app.modules.telegram_auth.init_data import USERNAME_MAX_LENGTH
from app.modules.telegram_auth.service import CHAT_ID_UNIQUE, USER_ID_UNIQUE
from app.modules.users.models import User

pytestmark = pytest.mark.db


def _user(session: Session, name: str) -> User:
    user = User(email=None, password_hash=None, full_name=name)
    session.add(user)
    session.flush()
    return user


def _link(session: Session, user: User, chat_id: int, username: str | None = None) -> None:
    session.add(
        TelegramLink(
            user_id=user.id,
            telegram_chat_id=chat_id,
            telegram_username=username,
            is_active=False,
            linked_at=datetime.now(UTC),
        )
    )
    session.flush()


def _constraint_of(exc: IntegrityError) -> str | None:
    return getattr(getattr(exc.orig, "diag", None), "constraint_name", None)


def test_one_telegram_account_per_user_and_per_chat(db_session: Session) -> None:
    first = _user(db_session, "First")
    second = _user(db_session, "Second")
    _link(db_session, first, 1001)

    with pytest.raises(IntegrityError) as same_chat, db_session.begin_nested():
        _link(db_session, second, 1001)
    assert _constraint_of(same_chat.value) == CHAT_ID_UNIQUE == "uq_telegram_links_telegram_chat_id"

    with pytest.raises(IntegrityError) as same_user, db_session.begin_nested():
        _link(db_session, first, 1002)
    assert _constraint_of(same_user.value) == USER_ID_UNIQUE == "uq_telegram_links_user_id"


def test_bigint_chat_id_holds_the_largest_telegram_id(db_session: Session) -> None:
    _link(db_session, _user(db_session, "Max"), 2**63 - 1)


def test_username_column_refuses_more_than_100_characters(db_session: Session) -> None:
    user = _user(db_session, "Long")
    _link(db_session, user, 2001, "a" * USERNAME_MAX_LENGTH)  # exactly 100: fine
    other = _user(db_session, "Longer")
    with pytest.raises(DataError), db_session.begin_nested():
        _link(db_session, other, 2002, "a" * (USERNAME_MAX_LENGTH + 1))


def test_link_requires_linked_at_and_existing_user(db_session: Session) -> None:
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(
            TelegramLink(user_id=uuid.uuid4(), telegram_chat_id=3001, linked_at=datetime.now(UTC))
        )
        db_session.flush()
    user = _user(db_session, "No date")
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(TelegramLink(user_id=user.id, telegram_chat_id=3002))
        db_session.flush()
