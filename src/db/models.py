from __future__ import annotations

from datetime import date, datetime

from sqlmodel import Field, SQLModel

from src.common.time import utc_now


class Station(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    city_code: str = Field(index=True, unique=True)
    city_name: str
    icao_code: str = Field(index=True, unique=True)
    country_code: str
    timezone_name: str
    settlement_unit: str
    wunderground_station_code: str
    latitude: float | None = None
    longitude: float | None = None
    is_active: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class MetarObservation(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    station_id: int = Field(index=True, foreign_key="station.id")
    observed_at: datetime = Field(index=True)
    temperature_c: float | None = None
    dewpoint_c: float | None = None
    wind_speed_kt: int | None = None
    wind_direction_deg: int | None = None
    pressure_hpa: float | None = None
    visibility_m: int | None = None
    raw_report: str
    is_stale: bool = False
    fetched_at: datetime = Field(default_factory=utc_now)


class TafReport(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    station_id: int = Field(index=True, foreign_key="station.id")
    issue_time: datetime = Field(index=True)
    valid_time_from: datetime | None = None
    valid_time_to: datetime | None = None
    raw_taf: str
    fetched_at: datetime = Field(default_factory=utc_now)


class TafForecastPeriod(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    taf_report_id: int = Field(index=True, foreign_key="tafreport.id")
    station_id: int = Field(index=True, foreign_key="station.id")
    time_from: datetime | None = Field(default=None, index=True)
    time_to: datetime | None = None
    time_bec: datetime | None = None
    fcst_change: str | None = None
    probability: int | None = None
    wind_direction_deg: int | None = None
    wind_speed_kt: int | None = None
    wind_gust_kt: int | None = None
    visibility: str | None = None
    weather_string: str | None = None
    clouds_json: str | None = None
    temperature_json: str | None = None


class Market(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    polymarket_market_id: str = Field(index=True, unique=True)
    question: str
    city_code: str = Field(index=True)
    forecast_date_local: date | None = Field(default=None, index=True)
    end_at: datetime | None = Field(default=None, index=True)
    bucket_label: str | None = None
    bucket_low: int | None = None
    bucket_high: int | None = None
    bucket_unit: str | None = None
    settlement_url: str | None = None
    parsed_station_code: str | None = None
    station_match_valid: bool = False
    status: str = Field(default="active", index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    last_seen_at: datetime = Field(default_factory=utc_now)


class MarketToken(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    market_id: int = Field(index=True, foreign_key="market.id")
    outcome_index: int
    outcome_name: str
    token_id: str = Field(index=True, unique=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class PriceSnapshot(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    market_id: int = Field(index=True, foreign_key="market.id")
    captured_at: datetime = Field(default_factory=utc_now, index=True)
    yes_bid: float | None = None
    yes_ask: float | None = None
    yes_mid: float | None = None
    yes_spread: float | None = None
    no_bid: float | None = None
    no_ask: float | None = None
    no_mid: float | None = None
    no_spread: float | None = None
    total_depth_usdc: float | None = None


class OrderbookLevel(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    snapshot_id: int = Field(index=True, foreign_key="pricesnapshot.id")
    side: str = Field(index=True)  # "bid" or "ask"
    outcome: str  # "yes" or "no"
    price: float
    size: float
    level_index: int  # 0 = best, 1 = second best, etc.


class EnsembleRun(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    station_id: int = Field(index=True, foreign_key="station.id")
    model_name: str = Field(index=True)
    timezone_name: str
    forecast_days: int
    fetched_at: datetime = Field(default_factory=utc_now, index=True)


class EnsembleForecast(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    ensemble_run_id: int = Field(index=True, foreign_key="ensemblerun.id")
    station_id: int = Field(index=True, foreign_key="station.id")
    forecast_date_local: date = Field(index=True)
    member_index: int = Field(index=True)
    member_name: str
    max_temp_c: float
    created_at: datetime = Field(default_factory=utc_now)


class Signal(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    market_id: int = Field(index=True, foreign_key="market.id")
    signal_at: datetime = Field(default_factory=utc_now, index=True)
    signal_type: str = Field(index=True)
    model_probability: float
    market_probability: float
    edge_bps: int
    confidence: float | None = None
    reasoning_json: str | None = None
    is_actionable: bool = False


class Order(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    signal_id: int | None = Field(default=None, index=True, foreign_key="signal.id")
    market_id: int = Field(index=True, foreign_key="market.id")
    mode: str = Field(default="paper", index=True)
    side: str
    price: float
    size: float
    fill_price: float | None = None
    fill_size: float | None = None
    status: str = Field(default="pending", index=True)
    external_order_id: str | None = None
    submitted_at: datetime = Field(default_factory=utc_now)
    filled_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utc_now)


class Position(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    market_id: int = Field(index=True, foreign_key="market.id")
    entry_side: str
    avg_entry_price: float
    size: float
    exposure_usdc: float
    realized_pnl: float = 0.0
    exit_price: float | None = None
    last_mark_price: float | None = None
    last_marked_at: datetime | None = None
    status: str = Field(default="open", index=True)
    opened_at: datetime = Field(default_factory=utc_now)
    closed_at: datetime | None = None


class RiskEvent(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    event_type: str = Field(index=True)
    severity: str = Field(index=True)
    details_json: str | None = None
    triggered_at: datetime = Field(default_factory=utc_now, index=True)
    resolved_at: datetime | None = None


class SystemHeartbeat(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    worker_name: str = Field(index=True, unique=True)
    status: str = Field(default="ok")
    message: str | None = None
    recorded_at: datetime = Field(default_factory=utc_now, index=True)


class SystemSetting(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(index=True, unique=True)
    value: str
    updated_at: datetime = Field(default_factory=utc_now)
