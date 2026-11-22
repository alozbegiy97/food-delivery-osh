"""Address requests and responses (API §4, DATABASE_SCHEMA.md §3.5, DEC-148).

Limits (DEC-148): `address_text` and `comment` up to 500 characters,
`label` 80, `entrance` 30, `floor` 20, `apartment` 30. Coordinates are
NUMERIC(10,7): latitude -90..90, longitude -180..180, at most 7 decimal
places, given together or not at all. Delivery needs coordinates (DEC-01).
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

MAX_ADDRESS_TEXT = 500
MAX_ADDRESS_COMMENT = 500
MAX_LABEL = 80
MAX_ENTRANCE = 30
MAX_FLOOR = 20
MAX_APARTMENT = 30


def _optional_text(limit: int):  # noqa: ANN202 - returns a validator
    def validate(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if len(cleaned) > limit:
            raise ValueError(f"не более {limit} символов")
        return cleaned or None

    return validate


def _required_text(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("обязательное поле")
    if len(cleaned) > MAX_ADDRESS_TEXT:
        raise ValueError(f"не более {MAX_ADDRESS_TEXT} символов")
    return cleaned


def _seven_places(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    exponent = value.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -7:
        raise ValueError("не более 7 знаков после запятой")
    return value


AddressText = Annotated[str, Field(max_length=MAX_ADDRESS_TEXT * 2), AfterValidator(_required_text)]
Label = Annotated[
    str | None, Field(max_length=MAX_LABEL * 2), AfterValidator(_optional_text(MAX_LABEL))
]
Entrance = Annotated[
    str | None, Field(max_length=MAX_ENTRANCE * 2), AfterValidator(_optional_text(MAX_ENTRANCE))
]
Floor = Annotated[
    str | None, Field(max_length=MAX_FLOOR * 2), AfterValidator(_optional_text(MAX_FLOOR))
]
Apartment = Annotated[
    str | None, Field(max_length=MAX_APARTMENT * 2), AfterValidator(_optional_text(MAX_APARTMENT))
]
AddressComment = Annotated[
    str | None,
    Field(max_length=MAX_ADDRESS_COMMENT * 2),
    AfterValidator(_optional_text(MAX_ADDRESS_COMMENT)),
]
Latitude = Annotated[Decimal, Field(ge=-90, le=90), AfterValidator(_seven_places)]
Longitude = Annotated[Decimal, Field(ge=-180, le=180), AfterValidator(_seven_places)]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _pair(latitude: Decimal | None, longitude: Decimal | None) -> None:
    if (latitude is None) != (longitude is None):
        raise ValueError("latitude и longitude указываются вместе")


class AddressCreate(_In):
    label: Label = None
    address_text: AddressText
    latitude: Latitude | None = None
    longitude: Longitude | None = None
    entrance: Entrance = None
    floor: Floor = None
    apartment: Apartment = None
    comment: AddressComment = None
    is_default: bool = False

    @model_validator(mode="after")
    def _check(self) -> Self:
        _pair(self.latitude, self.longitude)
        return self


class AddressUpdate(_In):
    """Partial update; an explicit null clears an optional field."""

    label: Label = None
    address_text: AddressText | None = None
    latitude: Latitude | None = None
    longitude: Longitude | None = None
    entrance: Entrance = None
    floor: Floor = None
    apartment: Apartment = None
    comment: AddressComment = None
    is_default: bool | None = None

    @model_validator(mode="after")
    def _check(self) -> Self:
        fields = self.model_fields_set
        if not fields:
            raise ValueError("укажите хотя бы одно поле")
        if "address_text" in fields and self.address_text is None:
            raise ValueError("address_text не может быть null")
        if "is_default" in fields and self.is_default is None:
            raise ValueError("is_default не может быть null")
        if ("latitude" in fields) != ("longitude" in fields):
            raise ValueError("latitude и longitude изменяются вместе")
        _pair(self.latitude, self.longitude)
        return self


class DeliveryAddressIn(_In):
    """A new address given at checkout: coordinates are required (DEC-01)."""

    label: Label = None
    address_text: AddressText
    latitude: Latitude
    longitude: Longitude
    entrance: Entrance = None
    floor: Floor = None
    apartment: Apartment = None
    comment: AddressComment = None


class AddressOut(BaseModel):
    id: uuid.UUID
    label: str | None
    address_text: str
    latitude: Decimal | None
    longitude: Decimal | None
    entrance: str | None
    floor: str | None
    apartment: str | None
    comment: str | None
    is_default: bool
    created_at: datetime
    updated_at: datetime


class Pagination(BaseModel):
    page: int
    page_size: int
    total: int
    pages: int


class AddressList(BaseModel):
    items: list[AddressOut]
    pagination: Pagination
