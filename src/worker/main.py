import asyncio
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlmodel import Session

from src.common.logging import configure_logging, logger
from src.common.settings import get_settings
from src.db.seeds import seed_stations
from src.db.session import create_db_and_tables, engine
from src.worker.jobs import (
    cleanup_job,
    forecast_job,
    market_job,
    orderbook_job,
    signal_job,
    weather_job,
)


def build_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    now = datetime.now(timezone.utc)
    scheduler.add_job(
        weather_job,
        "interval",
        seconds=30,
        id="weather_job",
        next_run_time=now,
    )
    scheduler.add_job(
        market_job,
        "interval",
        seconds=30,
        id="market_job",
        next_run_time=now + timedelta(seconds=10),
    )
    scheduler.add_job(
        forecast_job,
        "interval",
        hours=3,
        id="forecast_job",
        next_run_time=now + timedelta(seconds=5),
    )
    scheduler.add_job(
        signal_job,
        "interval",
        minutes=2,
        id="signal_job",
        next_run_time=now + timedelta(seconds=15),
    )
    scheduler.add_job(
        orderbook_job,
        "interval",
        seconds=15,
        id="orderbook_job",
        next_run_time=now + timedelta(seconds=20),
    )
    scheduler.add_job(
        cleanup_job,
        "interval",
        hours=24,
        id="cleanup_job",
        next_run_time=now + timedelta(minutes=5),
    )
    return scheduler


async def async_main() -> None:
    configure_logging()
    create_db_and_tables()
    settings = get_settings()
    with Session(engine) as session:
        seeded = seed_stations(session, settings.stations_path)
    logger.info(
        "worker_bootstrap",
        extra={"event": "worker_bootstrap", "seeded_stations": seeded},
    )

    scheduler = build_scheduler()
    scheduler.start()
    logger.info("worker_started", extra={"event": "worker_started"})

    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("worker_stopping", extra={"event": "worker_stopping"})
    finally:
        scheduler.shutdown(wait=False)


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
