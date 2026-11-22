"""Aggregates all `/api/v1` routers. Domain routers are added in later stages."""

from fastapi import APIRouter

from app.api.v1 import (
    addresses,
    admin_catalog,
    admin_ops,
    auth,
    cart,
    catalog,
    checkout,
    courier,
    health,
    kitchen,
    orders,
    payments,
    telegram_auth,
    users,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(telegram_auth.router)
api_router.include_router(catalog.router)
api_router.include_router(cart.router)
api_router.include_router(users.router)
api_router.include_router(addresses.router)
api_router.include_router(checkout.router)
api_router.include_router(orders.router)
api_router.include_router(payments.router)
api_router.include_router(admin_catalog.router)
api_router.include_router(admin_ops.router)
api_router.include_router(kitchen.router)
api_router.include_router(courier.router)
