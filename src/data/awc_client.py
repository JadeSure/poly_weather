from __future__ import annotations

from collections.abc import Sequence

import httpx

from src.common.http_retry import request_with_retry


class AviationWeatherClient:
    def __init__(
        self,
        api_base: str,
        timeout_seconds: float = 15.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._http_client = http_client

    async def fetch_metar(self, station_codes: Sequence[str]) -> list[dict]:
        return await self._get_json(
            "metar",
            params={
                "ids": ",".join(station_codes),
                "format": "json",
            },
        )

    async def fetch_taf(self, station_codes: Sequence[str]) -> list[dict]:
        return await self._get_json(
            "taf",
            params={
                "ids": ",".join(station_codes),
                "format": "json",
            },
        )

    async def _get_json(self, endpoint: str, params: dict[str, str]) -> list[dict]:
        url = f"{self.api_base}/{endpoint}"
        if self._http_client is not None:
            response = await request_with_retry(
                self._http_client,
                "GET",
                url,
                params=params,
                headers={"User-Agent": "WeatherEdge/0.1"},
                timeout=self.timeout_seconds,
            )
            return response.json()

        async with httpx.AsyncClient(
            headers={"User-Agent": "WeatherEdge/0.1"},
            timeout=self.timeout_seconds,
        ) as client:
            response = await request_with_retry(
                client,
                "GET",
                url,
                params=params,
            )
            return response.json()

