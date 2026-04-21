from __future__ import annotations

from collections.abc import Sequence

import httpx

from src.common.http_retry import request_with_retry
from src.common.settings import get_settings
from src.common.time import parse_utc_datetime
from src.db.models import Station
from src.market.contract_parser import is_weather_market_payload


class PolymarketClient:
    def __init__(
        self,
        api_base: str,
        gamma_api_base: str | None = None,
        timeout_seconds: float = 15.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.gamma_api_base = (gamma_api_base or get_settings().polymarket_gamma_api_base).rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._http_client = http_client

    async def list_markets(
        self,
        limit: int = 100,
        offset: int = 0,
        extra_params: dict[str, str | int | bool] | None = None,
    ) -> list[dict]:
        params: dict[str, str | int | bool] = {
            "limit": limit,
            "offset": offset,
        }
        if extra_params:
            params.update(extra_params)
        return await self._get_json(self.gamma_api_base, "/markets", params=params)

    async def list_weather_markets(
        self,
        stations: Sequence[Station],
        page_size: int = 100,
        max_pages: int = 5,
        max_markets_per_station: int = 8,
    ) -> list[dict]:
        matches_by_id: dict[str, dict] = {}

        for station in stations:
            search_payload = await self.public_search(station.city_name, limit_per_type=25)
            station_matches: list[dict] = []
            for event in search_payload.get("events", []):
                for market in event.get("markets", []):
                    if self._is_actionable_weather_market(market, stations):
                        station_matches.append(market)
            for market in search_payload.get("markets", []):
                if self._is_actionable_weather_market(market, stations):
                    station_matches.append(market)

            station_matches.sort(
                key=lambda item: parse_utc_datetime(item.get("endDate")) or parse_utc_datetime(item.get("endDateIso")) or parse_utc_datetime(0),
                reverse=True,
            )
            for market in station_matches[:max_markets_per_station]:
                matches_by_id[str(market.get("id"))] = market

        if matches_by_id:
            return list(matches_by_id.values())

        # Fallback for environments where public-search does not return results.
        matches: list[dict] = []
        for page in range(max_pages):
            payload = await self.list_markets(
                limit=page_size,
                offset=page * page_size,
                extra_params={"active": "true", "closed": "false"},
            )
            if not payload:
                break
            for item in payload:
                if self._is_actionable_weather_market(item, stations):
                    matches.append(item)
            if len(payload) < page_size:
                break
        return matches

    async def get_market_details(self, market_id: str) -> dict:
        return await self._get_object_json(self.gamma_api_base, f"/markets/{market_id}")

    async def get_orderbook(self, token_id: str) -> dict:
        return await self._get_object_json(
            self.api_base,
            "/book",
            params={"token_id": token_id},
        )

    async def public_search(self, query: str, limit_per_type: int = 10) -> dict:
        return await self._get_object_json(
            self.gamma_api_base,
            "/public-search",
            params={
                "q": query,
                "limit_per_type": limit_per_type,
                "search_tags": "false",
                "search_profiles": "false",
            },
        )

    async def _get_json(
        self,
        base_url: str,
        path: str,
        params: dict[str, str | int | bool] | None = None,
    ) -> list[dict]:
        response = await self._get(base_url, path, params=params)
        payload = response.json()
        return payload if isinstance(payload, list) else []

    async def _get_object_json(
        self,
        base_url: str,
        path: str,
        params: dict[str, str | int | bool] | None = None,
    ) -> dict:
        response = await self._get(base_url, path, params=params)
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    async def _get(
        self,
        base_url: str,
        path: str,
        params: dict[str, str | int | bool] | None = None,
    ) -> httpx.Response:
        url = f"{base_url}{path}"
        if self._http_client is not None:
            return await request_with_retry(
                self._http_client,
                "GET",
                url,
                params=params,
                headers={"User-Agent": "WeatherEdge/0.1"},
                timeout=self.timeout_seconds,
            )

        async with httpx.AsyncClient(
            headers={"User-Agent": "WeatherEdge/0.1"},
            timeout=self.timeout_seconds,
        ) as client:
            return await request_with_retry(
                client,
                "GET",
                url,
                params=params,
            )

    @staticmethod
    def _is_actionable_weather_market(payload: dict, stations: Sequence[Station]) -> bool:
        return (
            bool(payload.get("active"))
            and not bool(payload.get("closed"))
            and bool(payload.get("enableOrderBook", True))
            and is_weather_market_payload(payload, list(stations))
        )
