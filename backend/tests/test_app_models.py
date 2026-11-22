"""The running application registers every ORM model by itself.

conftest.py imports `app.db.models_registry` for all tests, which hid a
production failure: in a real process the User -> "Notification"
relationship could not be resolved and every ORM query failed. A fresh
interpreter that imports only `app.main` must configure all mappers.
"""

import os
import subprocess
import sys

from tests.conftest import BACKEND_DIR

CODE = """
import app.main  # noqa: F401
from sqlalchemy.orm import configure_mappers
configure_mappers()
print("mappers ok")
"""


def test_app_main_configures_all_mappers() -> None:
    result = subprocess.run(  # noqa: S603 - fixed command, no user input
        [sys.executable, "-c", CODE],
        cwd=BACKEND_DIR,
        env={**os.environ},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert "mappers ok" in result.stdout
