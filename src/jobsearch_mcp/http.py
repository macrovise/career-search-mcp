"""Bounded HTTPS reads, no automatic redirects, and no sensitive URL logging."""

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse

import httpx

from .security import _validate_url

MAX_BYTES = 8_000_000
_RECEIPTS: ContextVar[list[dict] | None] = ContextVar("provider_http_receipts", default=None)


@contextmanager
def capture_receipts():
    """Collect sanitized transport outcomes within one adapter task."""
    receipts = []
    token = _RECEIPTS.set(receipts)
    try:
        yield receipts
    finally:
        _RECEIPTS.reset(token)


def _record_receipt(receipt: dict) -> None:
    if (receipts := _RECEIPTS.get()) is not None:
        receipts.append(receipt)


async def fetch(url: str, params: dict | None = None) -> bytes:
    body, _ = await fetch_with_receipt(url, params)
    return body


async def fetch_with_receipt(url: str, params: dict | None = None) -> tuple[bytes, dict]:
    """Return actual transport evidence without logging URLs or query credentials."""
    async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
        for _ in range(6):
            await asyncio.to_thread(_validate_url, url)
            async with client.stream(
                "GET", url, params=params, headers={"User-Agent": "CareerSearchMCP/3.0"}
            ) as response:
                if response.is_redirect:
                    target = urljoin(str(response.url), response.headers["location"])
                    # Never forward API keys to a different origin via redirects.
                    if params or urlparse(target).netloc != urlparse(url).netloc:
                        raise ValueError("Source redirect not allowed")
                    url = target
                    continue
                if response.is_error:
                    checked_at = datetime.now(UTC).isoformat()
                    _record_receipt(
                        {
                            "http_code": response.status_code,
                            "checked_at": checked_at,
                            "outcome": "HTTP_ERROR",
                        }
                    )
                    response.raise_for_status()
                chunks = bytearray()
                async for chunk in response.aiter_bytes():
                    chunks.extend(chunk)
                    if len(chunks) > MAX_BYTES:
                        raise ValueError("Source response exceeds size limit")
                checked_at = datetime.now(UTC).isoformat()
                receipt = {
                    "http_code": response.status_code,
                    "fetched_at": checked_at,
                    "outcome": "SUCCESS",
                    "timestamp_basis": "caller_observed_response_completion",
                }
                _record_receipt(receipt)
                return bytes(chunks), receipt
        raise ValueError("Too many redirects")
