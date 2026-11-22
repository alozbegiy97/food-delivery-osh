"""Address book of a customer (API §4, DATABASE_SCHEMA.md §3.5, DEC-148).

- every operation is limited to the caller's own rows; another user's
  address is indistinguishable from a missing one (404);
- at most one default address (partial UNIQUE index): changes of the
  default lock all rows of the user (`FOR UPDATE`, by id) first, so two
  concurrent requests are applied one after another;
- deleting an address does not touch orders: they keep their own snapshot
  (DEC-16).
"""

import math
import uuid

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.addresses.schemas import (
    AddressCreate,
    AddressList,
    AddressOut,
    AddressUpdate,
    Pagination,
)
from app.modules.users.models import Address


def not_found() -> AppError:
    return AppError(404, "NOT_FOUND", "Ресурс не найден")


def _out(address: Address) -> AddressOut:
    return AddressOut.model_validate(address, from_attributes=True)


async def _lock_user_addresses(session: AsyncSession, user_id: uuid.UUID) -> None:
    await session.execute(
        select(Address.id).where(Address.user_id == user_id).order_by(Address.id).with_for_update()
    )


async def _clear_default(session: AsyncSession, user_id: uuid.UUID) -> None:
    await session.execute(
        update(Address)
        .where(Address.user_id == user_id, Address.is_default)
        .values(is_default=False)
    )


async def get_own(session: AsyncSession, user_id: uuid.UUID, address_id: uuid.UUID) -> Address:
    address = await session.scalar(
        select(Address).where(Address.id == address_id, Address.user_id == user_id)
    )
    if address is None:
        raise not_found()
    return address


async def list_addresses(
    session: AsyncSession, user_id: uuid.UUID, *, page: int, page_size: int
) -> AddressList:
    total = await session.scalar(
        select(func.count()).select_from(Address).where(Address.user_id == user_id)
    )
    rows = await session.scalars(
        select(Address)
        .where(Address.user_id == user_id)
        .order_by(Address.is_default.desc(), Address.created_at.desc(), Address.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    total = int(total or 0)
    return AddressList(
        items=[_out(row) for row in rows],
        pagination=Pagination(
            page=page,
            page_size=page_size,
            total=total,
            pages=math.ceil(total / page_size) if total else 0,
        ),
    )


async def create_address(
    session: AsyncSession, user_id: uuid.UUID, payload: AddressCreate, *, commit: bool = True
) -> AddressOut:
    if payload.is_default:
        await _lock_user_addresses(session, user_id)
        await _clear_default(session, user_id)
    address_id = await session.scalar(
        insert(Address).values(user_id=user_id, **payload.model_dump()).returning(Address.id)
    )
    address = await get_own(session, user_id, address_id)
    if commit:
        await session.commit()
    return _out(address)


async def update_address(
    session: AsyncSession, user_id: uuid.UUID, address_id: uuid.UUID, payload: AddressUpdate
) -> AddressOut:
    changes = payload.model_dump(include=payload.model_fields_set)
    if changes.get("is_default"):
        await _lock_user_addresses(session, user_id)
    address = await get_own(session, user_id, address_id)
    if changes.get("is_default") and not address.is_default:
        await _clear_default(session, user_id)
        await session.refresh(address)
    for field, value in changes.items():
        setattr(address, field, value)
    await session.flush()
    await session.refresh(address)
    await session.commit()
    return _out(address)


async def set_default(
    session: AsyncSession, user_id: uuid.UUID, address_id: uuid.UUID
) -> AddressOut:
    return await update_address(
        session, user_id, address_id, AddressUpdate.model_validate({"is_default": True})
    )


async def delete_address(session: AsyncSession, user_id: uuid.UUID, address_id: uuid.UUID) -> None:
    deleted = await session.scalar(
        delete(Address)
        .where(Address.id == address_id, Address.user_id == user_id)
        .returning(Address.id)
    )
    if deleted is None:
        await session.rollback()
        raise not_found()
    await session.commit()
