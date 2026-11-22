"""Telegram-only accounts (DEC-142 K2-B, DEC-152; DATABASE_SCHEMA.md §3.1).

`users.email` and `users.password_hash` become nullable; CHECK
`ck_users_credentials_pair` keeps them paired: both set or both NULL.
NULLs do not conflict in the unique index on lower(email).

Downgrade restores NOT NULL. If Telegram-only accounts exist it stops with
an error and changes nothing: their data is never deleted by a migration
(decision of 2026-11-13).

Revision ID: 0009_telegram_only_accounts
Revises: 0008_notifications
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_telegram_only_accounts"
down_revision: str | None = "0008_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CREDENTIALS_PAIR = "ck_users_credentials_pair"


def upgrade() -> None:
    op.alter_column("users", "email", existing_type=sa.String(length=255), nullable=True)
    op.alter_column("users", "password_hash", existing_type=sa.Text(), nullable=True)
    op.create_check_constraint(
        op.f(CREDENTIALS_PAIR), "users", "(email IS NULL) = (password_hash IS NULL)"
    )


def downgrade() -> None:
    # The DO block raises before anything is changed; the whole downgrade
    # runs in Alembic's transaction, so a refusal leaves the schema as is.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM users WHERE email IS NULL) THEN
                RAISE EXCEPTION
                    'Downgrade 0009 refused: Telegram-only accounts exist '
                    '(users.email IS NULL); they are not deleted automatically';
            END IF;
        END
        $$
        """
    )
    op.drop_constraint(op.f(CREDENTIALS_PAIR), "users", type_="check")
    op.alter_column("users", "password_hash", existing_type=sa.Text(), nullable=False)
    op.alter_column("users", "email", existing_type=sa.String(length=255), nullable=False)
