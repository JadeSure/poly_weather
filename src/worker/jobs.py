from sqlmodel import Session

from src.common.logging import logger
from src.common.settings import get_settings
from src.data.awc_client import AviationWeatherClient
from src.data.weather_fetcher import sync_weather
from src.db.runtime import cleanup_old_data, upsert_heartbeat
from src.db.session import engine
from src.engine.ensemble_fetcher import sync_forecasts
from src.engine.open_meteo_client import OpenMeteoEnsembleClient
from src.engine.signal_generator import sync_signals
from src.market.market_fetcher import snapshot_all_orderbooks, sync_markets
from src.market.polymarket_client import PolymarketClient


def heartbeat_job(worker_name: str, message: str, status: str = "ok") -> None:
    with Session(engine) as session:
        upsert_heartbeat(session, worker_name=worker_name, status=status, message=message)
    logger.info(
        "worker_heartbeat",
        extra={"event": "worker_heartbeat", "worker_name": worker_name, "status": status},
    )


async def weather_job() -> None:
    settings = get_settings()
    try:
        async_client = AviationWeatherClient(settings.noaa_awc_api_base)
        with Session(engine) as session:
            results = await sync_weather(session, client=async_client, engine=engine)
        inserted_metars = sum(item.metar_count for item in results)
        inserted_tafs = sum(item.taf_count for item in results)
        stale_count = sum(1 for item in results if item.stale)
        message = (
            f"stations={len(results)} inserted_metars={inserted_metars} "
            f"inserted_tafs={inserted_tafs} stale={stale_count}"
        )
        heartbeat_job("weather_fetcher", message)
    except Exception:
        logger.exception("weather_job_failed", extra={"event": "weather_job_failed"})
        heartbeat_job("weather_fetcher", "weather job failed", status="error")


async def market_job() -> None:
    settings = get_settings()
    try:
        client = PolymarketClient(
            api_base=settings.polymarket_api_base,
            gamma_api_base=settings.polymarket_gamma_api_base,
        )
        with Session(engine) as session:
            result = await sync_markets(
                session,
                client=client,
                page_size=100,
                max_pages=5,
                max_markets_per_station=20,
            )
        message = (
            f"discovered={result.discovered} "
            f"upserted_markets={result.upserted_markets} "
            f"saved_price_snapshots={result.saved_price_snapshots}"
        )
        heartbeat_job("market_fetcher", message)
    except Exception:
        logger.exception("market_job_failed", extra={"event": "market_job_failed"})
        heartbeat_job("market_fetcher", "market job failed", status="error")


async def forecast_job() -> None:
    settings = get_settings()
    try:
        client = OpenMeteoEnsembleClient(settings.open_meteo_ensemble_api_base)
        with Session(engine) as session:
            results = await sync_forecasts(session, client=client)
        total_days = sum(item.days for item in results)
        message = f"stations={len(results)} forecast_days={total_days}"
        heartbeat_job("forecast_fetcher", message)
    except Exception:
        logger.exception("forecast_job_failed", extra={"event": "forecast_job_failed"})
        heartbeat_job("forecast_fetcher", "forecast job failed", status="error")


def signal_job() -> None:
    try:
        with Session(engine) as session:
            result = sync_signals(session)
        heartbeat_job(
            "signal_engine",
            (
                f"generated={result.generated} actionable={result.actionable} "
                f"skipped={result.skipped}"
            ),
        )
    except Exception:
        logger.exception("signal_job_failed", extra={"event": "signal_job_failed"})
        heartbeat_job("signal_engine", "signal job failed", status="error")


async def orderbook_job() -> None:
    settings = get_settings()
    try:
        client = PolymarketClient(
            api_base=settings.polymarket_api_base,
            gamma_api_base=settings.polymarket_gamma_api_base,
        )
        with Session(engine) as session:
            count = await snapshot_all_orderbooks(session, client=client)
        heartbeat_job("orderbook_fetcher", f"snapshots={count}")
    except Exception:
        logger.exception("orderbook_job_failed", extra={"event": "orderbook_job_failed"})
        heartbeat_job("orderbook_fetcher", "orderbook job failed", status="error")


def cleanup_job() -> None:
    try:
        with Session(engine) as session:
            result = cleanup_old_data(session)
        heartbeat_job(
            "data_cleanup",
            f"metar_deleted={result['metar_deleted']} snapshot_deleted={result['snapshot_deleted']} level_deleted={result['level_deleted']}",
        )
    except Exception:
        logger.exception("cleanup_job_failed", extra={"event": "cleanup_job_failed"})
        heartbeat_job("data_cleanup", "cleanup job failed", status="error")
