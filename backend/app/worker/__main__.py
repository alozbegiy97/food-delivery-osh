"""Background worker entry point: `python -m app.worker` (DEC-104).

A single asyncio process: writes a heartbeat file (used by the Docker
healthcheck), runs the background jobs of `app.worker.jobs` (stage 7: the
mock_card payment timeout) and shuts down gracefully on SIGTERM/SIGINT.
Other jobs (Telegram outbox, polling, cleanup) arrive with their stages.
"""

import asyncio
import contextlib
import logging
import signal
import time
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import dispose_engine
from app.worker.jobs import default_jobs, run_job

logger = logging.getLogger("app.worker")


def _write_heartbeat(path: Path) -> None:
    path.write_text(str(int(time.time())), encoding="utf-8")


def _remove_heartbeat(path: Path) -> None:
    path.unlink(missing_ok=True)


async def run(stop: asyncio.Event) -> None:
    settings = get_settings()
    heartbeat = Path(settings.worker_heartbeat_file)
    interval = settings.worker_heartbeat_interval_seconds
    logger.info("Worker started (heartbeat every %ss)", interval)
    jobs = [asyncio.create_task(run_job(job, stop)) for job in default_jobs()]
    try:
        while not stop.is_set():
            await asyncio.to_thread(_write_heartbeat, heartbeat)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=interval)
    finally:
        stop.set()
        await asyncio.gather(*jobs, return_exceptions=True)
        await dispose_engine()
        await asyncio.to_thread(_remove_heartbeat, heartbeat)
    logger.info("Worker stopped")


async def main() -> None:
    configure_logging(get_settings().log_level)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        # Signal handlers are unavailable on Windows event loops; the worker
        # runs in a Linux container where they are supported.
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    await run(stop)


if __name__ == "__main__":
    asyncio.run(main())
