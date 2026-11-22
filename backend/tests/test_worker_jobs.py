"""Worker job loop (stage 7; DEC-104, DEC-149): a failing run is logged and the
job runs again; the loop stops gracefully when the stop event is set."""

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

from app.worker.jobs import Job, default_jobs, run_job


async def test_failing_job_does_not_stop_the_loop(caplog: pytest.LogCaptureFixture) -> None:
    calls = 0
    stop = asyncio.Event()

    async def flaky() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("boom")
        if calls >= 3:
            stop.set()

    await asyncio.wait_for(run_job(Job("flaky", 0.01, flaky), stop), timeout=5)
    assert calls == 3
    assert "Job flaky failed" in caplog.text


async def test_stop_interrupts_the_wait() -> None:
    stop = asyncio.Event()

    async def noop() -> None:
        stop.set()

    # A long interval must not delay the shutdown.
    await asyncio.wait_for(run_job(Job("noop", 3600, noop), stop), timeout=2)


def test_payment_timeout_is_registered_with_configured_interval() -> None:
    [job] = default_jobs()
    assert job.name == "payment_timeout"
    assert job.interval_seconds == 60


def test_worker_maps_every_model_in_a_fresh_interpreter() -> None:
    """Regression (stage 7 sandbox check): the worker process does not import
    `app.main`, so it must register all models itself, otherwise the first
    query fails with "failed to locate a name ('Notification')"."""
    code = "; ".join(
        (
            "import app.worker.__main__",
            "from sqlalchemy.orm import configure_mappers",
            "configure_mappers()",
            "print('mappers ok')",
        )
    )
    result = subprocess.run(  # noqa: S603 - fixed interpreter and code
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        timeout=180,  # a fresh interpreter imports the whole app; slow under load
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "mappers ok" in result.stdout
