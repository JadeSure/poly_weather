from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.routers.health import router as health_router
from src.api.routers.markets import router as markets_router
from src.api.routers.positions import router as positions_router
from src.api.routers.risk import router as risk_router
from src.api.routers.signals import router as signals_router
from src.api.routers.system import router as system_router
from src.api.routers.weather import router as weather_router
from src.common.logging import configure_logging
from src.common.settings import get_settings
from src.db.seeds import seed_stations
from src.db.session import Session, create_db_and_tables, engine


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    create_db_and_tables()
    settings = get_settings()
    with Session(engine) as session:
        seed_stations(session, settings.stations_path)
    yield


app = FastAPI(title="WeatherEdge API", version="0.1.0", lifespan=lifespan)
app.include_router(health_router)
app.include_router(weather_router)
app.include_router(markets_router)
app.include_router(signals_router)
app.include_router(positions_router)
app.include_router(risk_router)
app.include_router(system_router)

