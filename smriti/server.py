"""Sanitized launcher; startup/Uvicorn failures never print their arguments or traceback."""

import argparse
import logging
import sys

import uvicorn

from smriti.observability import (
    SafeLogHandler,
    print_startup_banner,
    safe_event,
    sanitized_logging,
    terminal_line,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    options = parser.parse_args()
    if not 1 <= options.port <= 65535:
        return 1
    try:
        print_startup_banner(options.port)
        with sanitized_logging(None):
            uvicorn.run("smriti.main:app", host="127.0.0.1", port=options.port, access_log=False,
                    log_config={"version": 1, "disable_existing_loggers": False,
                                "handlers": {"safe": {"()": SafeLogHandler}},
                                "loggers": {name: {"handlers": ["safe"], "level": "INFO", "propagate": False}
                                            for name in ("uvicorn", "uvicorn.error", "uvicorn.access")}})
        return 0
    except Exception:
        sys.stdout.write(terminal_line(safe_event("service_error", component="service", code="controller_error")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
