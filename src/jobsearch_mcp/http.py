"""Bounded HTTPS reads, no automatic redirects, and no sensitive URL logging."""

import asyncio
from urllib.parse import urljoin, urlparse

import httpx

from .security import _validate_url

MAX_BYTES = 8_000_000


async def fetch(url: str, params: dict | None = None) -> bytes:
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
                response.raise_for_status()
                chunks = bytearray()
                async for chunk in response.aiter_bytes():
                    chunks.extend(chunk)
                    if len(chunks) > MAX_BYTES:
                        raise ValueError("Source response exceeds size limit")
                return bytes(chunks)
        raise ValueError("Too many redirects")
