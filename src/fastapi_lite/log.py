"""Uvicorn-style access-log middleware for FastAPI."""

from __future__ import annotations

import logging
import sys
import time
from http import HTTPStatus

from fastapi import FastAPI, Request, Response
from uvicorn.logging import DefaultFormatter

RESET = "\033[0m"
BRIGHT_WHITE = "\033[97m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
BRIGHT_RED = "\033[91m"


def format_status(status_code: int) -> str:
    """Return a coloured ``'<code> <phrase>'`` string for terminal output."""
    try:
        phrase = HTTPStatus(status_code).phrase
    except ValueError:
        phrase = "UNKNOWN"

    color = BRIGHT_WHITE

    if 200 <= status_code < 300:
        color = GREEN
    elif 300 <= status_code < 400:
        color = YELLOW
    elif 400 <= status_code < 500:
        color = RED
    elif status_code >= 500:
        color = BRIGHT_RED

    return f"{color}{status_code} {phrase}{RESET}"


def get_logger(name: str = "fastapi_lite") -> logging.Logger:
    """Create a logger with uvicorn-style formatting."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        DefaultFormatter(
            fmt="%(levelprefix)s %(asctime)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            use_colors=True,
        )
    )

    logger.handlers.clear()
    logger.addHandler(handler)
    return logger


def add_uvicorn_like_access_log(app: FastAPI, logger_name: str = "fastapi_lite") -> None:
    """Register an HTTP middleware that logs every request in uvicorn style.

    Args:
        app: The FastAPI application instance.
        logger_name: Logger name to use (default ``"fastapi_lite"``).
    """
    _logger = get_logger(logger_name)

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        start = time.perf_counter()
        method = request.method
        path = request.url.path
        if request.url.query:
            path += f"?{request.url.query}"
        http_version = request.scope.get("http_version", "1.1")

        try:
            response: Response = await call_next(request)
        except Exception:
            duration = (time.perf_counter() - start) * 1000
            _logger.exception(
                '- "%s %s HTTP/%s" %s (%.1f ms)',
                method,
                path,
                http_version,
                format_status(500),
                duration,
            )
            raise

        duration = (time.perf_counter() - start) * 1000
        _logger.info(
            '- "%s %s HTTP/%s" %s (%.1f ms)',
            method,
            path,
            http_version,
            format_status(response.status_code),
            duration,
        )
        return response
