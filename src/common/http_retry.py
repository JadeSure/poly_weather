from __future__ import annotations

import asyncio
import logging

import httpx

logger = logging.getLogger("weatheredge")

RETRYABLE_STATUS_CODES = {502, 503, 504, 429}
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0


async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    **kwargs,
) -> httpx.Response:
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = await client.request(method, url, **kwargs)
            if response.status_code in RETRYABLE_STATUS_CODES and attempt < max_retries:
                delay = min(base_delay * (2**attempt), max_delay)
                logger.warning(
                    "http_retry",
                    extra={
                        "event": "http_retry",
                        "url": url,
                        "status": response.status_code,
                        "attempt": attempt + 1,
                        "delay": delay,
                    },
                )
                await asyncio.sleep(delay)
                continue
            response.raise_for_status()
            return response
        except httpx.TimeoutException as exc:
            last_exc = exc
            if attempt < max_retries:
                delay = min(base_delay * (2**attempt), max_delay)
                logger.warning(
                    "http_timeout_retry",
                    extra={
                        "event": "http_timeout_retry",
                        "url": url,
                        "attempt": attempt + 1,
                        "delay": delay,
                    },
                )
                await asyncio.sleep(delay)
                continue
            raise
        except httpx.HTTPStatusError:
            raise
    raise last_exc  # type: ignore[misc]
