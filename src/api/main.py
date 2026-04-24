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


app = FastAPI(
    title="WeatherEdge API",
    version="0.2.0",
    description=(
        "WeatherEdge 是一个天气预测市场的信号监控系统。\n\n"
        "系统从 Polymarket 抓取天气相关预测市场数据，结合 Open-Meteo ensemble 气象预报，"
        "生成模型概率与市场概率的对比信号，用于识别市场定价偏差。\n\n"
        "**核心模块：**\n"
        "- **Weather** — 气象站、METAR 观测、TAF 预报、Ensemble 集合预报\n"
        "- **Markets** — Polymarket 天气市场数据、价格历史、订单簿\n"
        "- **Signals** — 模型 vs 市场概率对比信号、edge 计算\n"
        "- **Positions** — 持仓管理（当前未启用执行层）\n"
        "- **Risk** — 风控状态、交易开关\n"
        "- **System** — 系统统计、Worker 心跳、运维控制\n\n"
        "**注意：** 当前系统为信号监控后端，尚未启用交易执行功能。"
    ),
    lifespan=lifespan,
)
app.include_router(health_router)
app.include_router(weather_router)
app.include_router(markets_router)
app.include_router(signals_router)
app.include_router(positions_router)
app.include_router(risk_router)
app.include_router(system_router)

