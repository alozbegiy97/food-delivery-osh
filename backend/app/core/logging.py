"""Logging configuration.

Rules (CLAUDE.md, security): never log passwords, tokens, secrets or card
data. Request logs contain method, path (without query string), status and
duration only.
"""

import logging
import logging.config

from app.core.request_context import get_request_id


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


def configure_logging(level: str) -> None:
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {"request_id": {"()": RequestIdFilter}},
            "formatters": {
                "default": {
                    "format": "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s",
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "filters": ["request_id"],
                }
            },
            "root": {"handlers": ["console"], "level": level},
            "loggers": {
                # Access logs are produced by RequestContextMiddleware instead:
                # uvicorn's access log would include query strings.
                "uvicorn.access": {"handlers": [], "propagate": False},
                "uvicorn.error": {"level": level},
            },
        }
    )
