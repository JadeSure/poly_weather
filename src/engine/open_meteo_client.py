from __future__ import annotations

import httpx


class OpenMeteoEnsembleClient:
    def __init__(
        self,
        api_base: str,
        timeout_seconds: float = 20.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._http_client = http_client

    async def fetch_hourly_temperature_ensemble(
        self,
        latitude: float,
        longitude: float,
        timezone_name: str,
        model: str = "gfs_seamless",
        forecast_days: int = 7,
    ) -> dict:
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "models": model,
            "hourly": "temperature_2m",
            "forecast_days": forecast_days,
            "timezone": timezone_name,
        }
        if self._http_client is not None:
            response = await self._http_client.get(
                f"{self.api_base}/ensemble",
                params=params,
                headers={"User-Agent": "WeatherEdge/0.1"},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            return response.json()

        async with httpx.AsyncClient(
            headers={"User-Agent": "WeatherEdge/0.1"},
            timeout=self.timeout_seconds,
        ) as client:
            response = await client.get(f"{self.api_base}/ensemble", params=params)
            response.raise_for_status()
            return response.json()
