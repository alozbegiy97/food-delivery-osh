"""Password forgot/reset (DEC-108, DEC-140; package S3-C).

Outgoing mail is captured by replacing the sender used by the router; one
test also sends a real letter to Mailpit when it is reachable.
"""

import hashlib
import json
import os
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.v1 import auth as auth_router
from app.core.mailer import OutgoingEmail, send_email
from app.core.security import decode_access_token
from app.modules.auth.refresh_sessions import hash_refresh_token
from app.modules.users.enums import RoleName
from app.modules.users.models import PasswordResetToken, RefreshToken, Role, User
from tests.auth_http import NEW_PASSWORD, PASSWORD, call, login, register

pytestmark = pytest.mark.db

EMAIL = "reset@example.com"
ACCEPTED = {"message": "Если аккаунт существует, мы отправили письмо"}


@pytest.fixture
async def roles(api_conn: AsyncConnection) -> None:
    await api_conn.execute(insert(Role).values([{"name": name.value} for name in RoleName]))


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> list[OutgoingEmail]:
    sent: list[OutgoingEmail] = []

    def capture(message: OutgoingEmail) -> bool:
        sent.append(message)
        return True

    monkeypatch.setattr(auth_router, "send_email", capture)
    return sent


def _token_from(message: OutgoingEmail) -> str:
    link = next(word for word in message.body.split() if "/reset-password?token=" in word)
    assert link.startswith("http://localhost:5173/reset-password?token=")
    return parse_qs(urlsplit(link).query)["token"][0]


async def _forgot(client: httpx.AsyncClient, email: str) -> httpx.Response:
    return await call(client, "POST", "/password/forgot", json={"email": email})


async def _reset(client: httpx.AsyncClient, token: str, password: str = NEW_PASSWORD):  # noqa: ANN202
    return await call(
        client, "POST", "/password/reset", json={"token": token, "new_password": password}
    )


async def test_forgot_sends_link_and_reset_changes_password(
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: None,
    outbox: list[OutgoingEmail],
) -> None:
    session = await register(api_client, EMAIL)
    user_id = decode_access_token(session.access)

    response = await _forgot(api_client, "  Reset@Example.com ")
    assert response.status_code == 202
    assert response.json() == ACCEPTED
    assert len(outbox) == 1 and outbox[0].to == EMAIL
    assert outbox[0].subject == "Сброс пароля"
    token = _token_from(outbox[0])
    stored = await api_conn.scalar(
        select(PasswordResetToken.token_hash).where(PasswordResetToken.user_id == user_id)
    )
    assert stored == hashlib.sha256(token.encode()).hexdigest()  # only the hash is stored

    await api_conn.execute(update(User).where(User.id == user_id).values(must_change_password=True))
    assert (await _reset(api_client, token)).status_code == 204

    old = await call(api_client, "POST", "/login", json={"email": EMAIL, "password": PASSWORD})
    assert old.status_code == 401
    await login(api_client, EMAIL, NEW_PASSWORD)
    assert (
        await api_conn.scalar(select(User.must_change_password).where(User.id == user_id)) is False
    )
    refresh_row = await api_conn.scalar(
        select(RefreshToken.revoked_at).where(
            RefreshToken.token_hash == hash_refresh_token(session.refresh)
        )
    )
    assert refresh_row is not None  # every earlier session is revoked

    reused = await _reset(api_client, token, "another3pass")
    assert reused.status_code == 400
    assert reused.json()["error"]["code"] == "INVALID_OR_EXPIRED_TOKEN"


async def test_forgot_answers_the_same_for_everyone(
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: None,
    outbox: list[OutgoingEmail],
) -> None:
    session = await register(api_client, "inactive@example.com")
    await api_conn.execute(
        update(User).where(User.id == decode_access_token(session.access)).values(is_active=False)
    )
    responses = [
        await _forgot(api_client, "nobody@example.com"),
        await _forgot(api_client, "inactive@example.com"),
        await _forgot(api_client, "not an email at all"),
    ]
    assert {r.status_code for r in responses} == {202}
    assert all(r.json() == ACCEPTED for r in responses)
    assert outbox == []


async def test_new_request_invalidates_previous_link(
    api_client: httpx.AsyncClient, roles: None, outbox: list[OutgoingEmail]
) -> None:
    await register(api_client, EMAIL)
    await _forgot(api_client, EMAIL)
    await _forgot(api_client, EMAIL)
    first, second = (_token_from(message) for message in outbox)
    assert (await _reset(api_client, first)).status_code == 400
    assert (await _reset(api_client, second)).status_code == 204


async def test_expired_and_unknown_tokens(
    api_client: httpx.AsyncClient,
    api_conn: AsyncConnection,
    roles: None,
    outbox: list[OutgoingEmail],
) -> None:
    await register(api_client, EMAIL)
    await _forgot(api_client, EMAIL)
    token = _token_from(outbox[0])
    await api_conn.execute(
        update(PasswordResetToken).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    for candidate in (token, "unknown-token", "x" * 200):
        response = await _reset(api_client, candidate)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_OR_EXPIRED_TOKEN"


async def test_reset_applies_password_policy(
    api_client: httpx.AsyncClient, roles: None, outbox: list[OutgoingEmail]
) -> None:
    await register(api_client, EMAIL)
    await _forgot(api_client, EMAIL)
    response = await _reset(api_client, _token_from(outbox[0]), "short1")
    assert response.status_code == 422
    assert "short1" not in response.text
    # The token is still usable after a rejected policy check.
    assert (await _reset(api_client, _token_from(outbox[0]))).status_code == 204


async def test_letter_language_follows_user(
    api_client: httpx.AsyncClient, roles: None, outbox: list[OutgoingEmail]
) -> None:
    await register(api_client, EMAIL, preferred_language="uz")
    await _forgot(api_client, EMAIL)
    assert outbox[0].subject == "Parolni tiklash"
    assert "30" in outbox[0].body


async def test_tokens_and_links_are_not_logged(
    api_client: httpx.AsyncClient,
    roles: None,
    outbox: list[OutgoingEmail],
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    caplog.set_level(logging.DEBUG)
    await register(api_client, EMAIL)
    await _forgot(api_client, EMAIL)
    token = _token_from(outbox[0])
    await _reset(api_client, token)
    assert token not in caplog.text
    assert "reset-password" not in caplog.text
    assert NEW_PASSWORD not in caplog.text


def _mailpit_api() -> str | None:
    url = os.environ.get("MAILPIT_API_URL", "http://mailpit:8025/api/v1")
    try:
        with urllib.request.urlopen(f"{url}/info", timeout=5):  # noqa: S310 - fixed host
            return url
    except OSError:
        return None


def test_real_letter_reaches_mailpit() -> None:
    api = _mailpit_api()
    if api is None:
        pytest.skip("Mailpit is not reachable from this environment")
    marker = f"s3c-{uuid.uuid4().hex}"
    assert send_email(OutgoingEmail(to=f"{marker}@example.com", subject=marker, body="body"))
    with urllib.request.urlopen(f"{api}/search?query={marker}", timeout=5) as resp:  # noqa: S310
        found = json.load(resp)
    assert found["messages_count"] >= 1
