"""`/users/me/addresses` (API_SPECIFICATION.md §4, DEC-148).

Only users with the `customer` role (DEC-23); every row is checked for
ownership in the service. Thin layer.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.modules.addresses import service
from app.modules.addresses.schemas import AddressCreate, AddressList, AddressOut, AddressUpdate
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.users.enums import RoleName

router = APIRouter(prefix="/users/me/addresses", tags=["addresses"])

Session = Annotated[AsyncSession, Depends(get_session)]
Customer = Annotated[CurrentUser, Depends(require_roles(RoleName.CUSTOMER.value))]


@router.get("", response_model=AddressList)
async def list_addresses(
    session: Session,
    user: Customer,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AddressList:
    return await service.list_addresses(session, user.id, page=page, page_size=page_size)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=AddressOut)
async def create_address(payload: AddressCreate, session: Session, user: Customer) -> AddressOut:
    return await service.create_address(session, user.id, payload)


@router.patch("/{address_id}", response_model=AddressOut)
async def update_address(
    address_id: uuid.UUID, payload: AddressUpdate, session: Session, user: Customer
) -> AddressOut:
    return await service.update_address(session, user.id, address_id, payload)


@router.delete("/{address_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_address(address_id: uuid.UUID, session: Session, user: Customer) -> None:
    await service.delete_address(session, user.id, address_id)


@router.post("/{address_id}/default", response_model=AddressOut)
async def set_default(address_id: uuid.UUID, session: Session, user: Customer) -> AddressOut:
    return await service.set_default(session, user.id, address_id)
