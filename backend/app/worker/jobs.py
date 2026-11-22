"""Background job loop of the worker (DEC-104, DEC-149; DATABASE_SCHEMA.md §14.5).

Each job runs on its own interval in its own asyncio task, calls the same
services as the API and opens its own transactions. An exception is logged
and the job runs again at its next interval: one failing job never stops
the worker. Stopping is graceful: the loop finishes the current run and
exits when the stop event is set.

Stage 7 registers only the payment timeout; other jobs (Telegram outbox,
polling, cleanup) arrive with their stages (DEC-148: cleanup — stage 10).
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import app.db.models_registry  # noqa: F401 - register every model before mapping
from app.core.config import get_settings
from app.db.session import get_session_factory
from app.modules.payments.timeouts import cancel_expired_orders

logger = logging.getLogger("app.worker")


@dataclass(frozen=True)
class Job:
    name: str
    interval_seconds: float
    run: Callable[[], Awaitable[object]]


async def run_job(job: Job, stop: asyncio.Event) -> None:
    logger.info("Job %s started (every %ss)", job.name, job.interval_seconds)
    while not stop.is_set():
        try:
            await job.run()
        except Exception:
            logger.exception("Job %s failed; it will run again", job.name)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=job.interval_seconds)
    logger.info("Job %s stopped", job.name)


def default_jobs() -> list[Job]:
    settings = get_settings()

    async def payment_timeout() -> object:
        return await cancel_expired_orders(
            get_session_factory(), batch_size=settings.payment_timeout_batch_size
        )

    return [
        Job(
            name="payment_timeout",
            interval_seconds=settings.payment_timeout_check_interval_seconds,
            run=payment_timeout,
        )
    ]
