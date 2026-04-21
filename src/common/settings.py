from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = Field(default="development", alias="APP_ENV")
    database_url: str = Field(default="sqlite:///./weatheredge.db", alias="DATABASE_URL")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    sql_echo: bool = Field(default=False, alias="SQL_ECHO")
    trading_mode: str = Field(default="paper", alias="TRADING_MODE")
    noaa_awc_api_base: str = Field(
        default="https://aviationweather.gov/api/data",
        alias="NOAA_AWC_API_BASE",
    )
    open_meteo_api_base: str = Field(
        default="https://api.open-meteo.com/v1",
        alias="OPEN_METEO_API_BASE",
    )
    open_meteo_ensemble_api_base: str = Field(
        default="https://ensemble-api.open-meteo.com/v1",
        alias="OPEN_METEO_ENSEMBLE_API_BASE",
    )
    polymarket_api_base: str = Field(
        default="https://clob.polymarket.com",
        alias="POLYMARKET_API_BASE",
    )
    polymarket_gamma_api_base: str = Field(
        default="https://gamma-api.polymarket.com",
        alias="POLYMARKET_GAMMA_API_BASE",
    )
    polygon_rpc_url: str | None = Field(default=None, alias="POLYGON_RPC_URL")
    polymarket_private_key: str | None = Field(default=None, alias="POLYMARKET_PRIVATE_KEY")
    max_single_trade_usdc: float = Field(default=25.0, alias="MAX_SINGLE_TRADE_USDC")
    max_daily_loss_usdc: float = Field(default=100.0, alias="MAX_DAILY_LOSS_USDC")
    max_concurrent_positions: int = Field(default=20, alias="MAX_CONCURRENT_POSITIONS")
    max_city_exposure_usdc: float = Field(default=50.0, alias="MAX_CITY_EXPOSURE_USDC")
    max_market_exposure_usdc: float = Field(default=25.0, alias="MAX_MARKET_EXPOSURE_USDC")
    execution_signal_max_age_minutes: int = Field(
        default=15,
        alias="EXECUTION_SIGNAL_MAX_AGE_MINUTES",
    )
    stations_config_path: str = Field(
        default="config/stations.yaml",
        alias="STATIONS_CONFIG_PATH",
    )
    logging_config_path: str = Field(
        default="config/logging.json",
        alias="LOGGING_CONFIG_PATH",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def stations_path(self) -> Path:
        return Path(self.stations_config_path)

    @property
    def logging_path(self) -> Path:
        return Path(self.logging_config_path)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
