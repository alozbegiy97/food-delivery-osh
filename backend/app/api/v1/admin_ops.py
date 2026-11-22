"""`/admin` operations of stage 8 (API §9; DEC-150): dashboard, orders,
cancellation requests, staff, settings, working hours, delivery zones.

Every route requires the `admin` role, checked in the database on each
request (DEC-66). Thin layer: rules live in the service modules.
"""

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.modules.admin_orders import service as orders
from app.modules.admin_orders.schemas import (
    AdminOrderDetail,
    AdminOrderList,
    AdminRequestList,
    AdminRequestOut,
    RequestRejection,
    RequestStatusFilter,
    StatusChange,
)
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.courier import assignments as couriers
from app.modules.courier.schemas import AssignCourierIn, CourierList, CourierOut, CourierSettingsIn
from app.modules.dashboard import service as dashboard
from app.modules.delivery import zones_admin as zones
from app.modules.restaurant import admin as restaurant
from app.modules.staff import service as staff
from app.modules.staff.schemas import StaffCreate, StaffList, StaffOut, StaffRolesUpdate
from app.modules.users.enums import RoleName

router = APIRouter(prefix="/admin", tags=["admin"])

Session = Annotated[AsyncSession, Depends(get_session)]
Admin = Annotated[CurrentUser, Depends(require_roles(RoleName.ADMIN.value))]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]
DateParam = Annotated[date | None, Query(description="YYYY-MM-DD, Asia/Bishkek")]


# Dashboard (DEC-90, DEC-111, DEC-114) -------------------------------------


@router.get("/dashboard/summary", response_model=dashboard.SummaryOut)
async def dashboard_summary(
    session: Session, _: Admin, date_from: DateParam = None, date_to: DateParam = None
) -> dashboard.SummaryOut:
    return await dashboard.summary(session, date_from, date_to)


@router.get("/dashboard/orders-chart", response_model=dashboard.ChartOut)
async def dashboard_chart(
    session: Session, _: Admin, date_from: DateParam = None, date_to: DateParam = None
) -> dashboard.ChartOut:
    return await dashboard.chart(session, date_from, date_to)


@router.get("/dashboard/top-products", response_model=dashboard.TopProductsOut)
async def dashboard_top(
    session: Session, _: Admin, date_from: DateParam = None, date_to: DateParam = None
) -> dashboard.TopProductsOut:
    return await dashboard.top_products(session, date_from, date_to)


# Orders ---------------------------------------------------------------------


@router.get("/orders", response_model=AdminOrderList)
async def list_orders(
    session: Session,
    _: Admin,
    status_filter: Annotated[
        Literal[
            "pending",
            "confirmed",
            "preparing",
            "ready_for_pickup",
            "out_for_delivery",
            "completed",
            "rejected",
            "cancelled",
        ]
        | None,
        Query(alias="status"),
    ] = None,
    delivery_type: Literal["delivery", "pickup"] | None = None,
    date_from: DateParam = None,
    date_to: DateParam = None,
    number: Annotated[str | None, Query(max_length=40)] = None,
    awaiting_payment: bool = False,
    page: Page = 1,
    page_size: PageSize = 20,
) -> AdminOrderList:
    return await orders.list_orders(
        session,
        status=status_filter,
        delivery_type=delivery_type,
        date_from=date_from,
        date_to=date_to,
        number=number,
        awaiting_payment=awaiting_payment,
        page=page,
        page_size=page_size,
    )


@router.get("/orders/{order_id}", response_model=AdminOrderDetail)
async def get_order(order_id: uuid.UUID, session: Session, _: Admin) -> AdminOrderDetail:
    return await orders.get_order(session, order_id)


@router.patch("/orders/{order_id}/status", response_model=AdminOrderDetail)
async def change_status(
    order_id: uuid.UUID, payload: StatusChange, session: Session, admin: Admin
) -> AdminOrderDetail:
    return await orders.change_order_status(session, order_id, payload, admin_id=admin.id)


@router.post("/orders/{order_id}/assign-courier", response_model=AdminOrderDetail)
async def assign_courier(
    order_id: uuid.UUID, payload: AssignCourierIn, session: Session, admin: Admin
) -> AdminOrderDetail:
    """Manual assignment or reassignment (DEC-48, DEC-51, DEC-151 п. 4)."""
    return await orders.assign_courier(session, order_id, payload.courier_id, admin_id=admin.id)


@router.post("/orders/{order_id}/auto-assign-courier", response_model=AdminOrderDetail)
async def auto_assign_courier(order_id: uuid.UUID, session: Session, _: Admin) -> AdminOrderDetail:
    """DEC-49, DEC-50, DEC-151 п. 3–4."""
    return await orders.auto_assign_courier(session, order_id)


@router.get("/cancellation-requests", response_model=AdminRequestList)
async def list_requests(
    session: Session,
    _: Admin,
    status_filter: Annotated[RequestStatusFilter, Query(alias="status")] = "pending",
    page: Page = 1,
    page_size: PageSize = 20,
) -> AdminRequestList:
    return await orders.list_requests(session, status=status_filter, page=page, page_size=page_size)


@router.post("/cancellation-requests/{request_id}/approve", response_model=AdminRequestOut)
async def approve_request(request_id: uuid.UUID, session: Session, admin: Admin) -> AdminRequestOut:
    return await orders.approve_request(session, request_id, admin_id=admin.id)


@router.post("/cancellation-requests/{request_id}/reject", response_model=AdminRequestOut)
async def reject_request(
    request_id: uuid.UUID, payload: RequestRejection, session: Session, admin: Admin
) -> AdminRequestOut:
    return await orders.reject_request(session, request_id, payload, admin_id=admin.id)


# Staff (DEC-150) --------------------------------------------------------------


@router.get("/staff", response_model=StaffList)
async def list_staff(
    session: Session, _: Admin, page: Page = 1, page_size: PageSize = 50
) -> StaffList:
    return await staff.list_staff(session, page=page, page_size=page_size)


@router.post("/staff", status_code=status.HTTP_201_CREATED, response_model=StaffOut)
async def create_staff(payload: StaffCreate, session: Session, _: Admin) -> StaffOut:
    return await staff.create_staff(session, payload)


@router.patch("/staff/{user_id}/roles", response_model=StaffOut)
async def update_roles(
    user_id: uuid.UUID, payload: StaffRolesUpdate, session: Session, _: Admin
) -> StaffOut:
    return await staff.update_roles(session, user_id, payload)


@router.post("/staff/{user_id}/deactivate", response_model=StaffOut)
async def deactivate(user_id: uuid.UUID, session: Session, _: Admin) -> StaffOut:
    return await staff.deactivate(session, user_id)


@router.post("/staff/{user_id}/reactivate", response_model=StaffOut)
async def reactivate(user_id: uuid.UUID, session: Session, _: Admin) -> StaffOut:
    return await staff.reactivate(session, user_id)


# Couriers (DEC-151 п. 2) --------------------------------------------------------


@router.get("/couriers", response_model=CourierList)
async def list_couriers(session: Session, _: Admin) -> CourierList:
    return await couriers.list_couriers(session)


@router.patch("/couriers/{user_id}/availability", response_model=CourierOut)
async def update_courier(
    user_id: uuid.UUID, payload: CourierSettingsIn, session: Session, _: Admin
) -> CourierOut:
    return await couriers.update_courier(session, user_id, payload)


# Settings and working hours ---------------------------------------------------


@router.get("/settings", response_model=restaurant.SettingsOut)
async def get_settings(session: Session, _: Admin) -> restaurant.SettingsOut:
    return await restaurant.get_settings_admin(session)


@router.patch("/settings", response_model=restaurant.SettingsOut)
async def update_settings(
    payload: restaurant.SettingsUpdate, session: Session, _: Admin
) -> restaurant.SettingsOut:
    return await restaurant.update_settings(session, payload)


@router.get("/working-hours", response_model=restaurant.WeekHours)
async def get_hours(session: Session, _: Admin) -> restaurant.WeekHours:
    return await restaurant.get_hours(session)


@router.put("/working-hours", response_model=restaurant.WeekHours)
async def put_hours(
    payload: restaurant.WeekHoursIn, session: Session, _: Admin
) -> restaurant.WeekHours:
    return await restaurant.replace_hours(session, payload)


# Delivery zones (DEC-150) -----------------------------------------------------


@router.get("/delivery-zones", response_model=zones.AdminZoneList)
async def list_zones(session: Session, _: Admin) -> zones.AdminZoneList:
    return await zones.list_zones(session)


@router.post(
    "/delivery-zones", status_code=status.HTTP_201_CREATED, response_model=zones.AdminZoneOut
)
async def create_zone(payload: zones.ZoneCreate, session: Session, _: Admin) -> zones.AdminZoneOut:
    return await zones.create_zone(session, payload)


@router.patch("/delivery-zones/{zone_id}", response_model=zones.AdminZoneOut)
async def update_zone(
    zone_id: uuid.UUID, payload: zones.ZoneUpdate, session: Session, _: Admin
) -> zones.AdminZoneOut:
    return await zones.update_zone(session, zone_id, payload)


@router.delete("/delivery-zones/{zone_id}", response_model=zones.AdminZoneOut)
async def deactivate_zone(zone_id: uuid.UUID, session: Session, _: Admin) -> zones.AdminZoneOut:
    return await zones.deactivate_zone(session, zone_id)
