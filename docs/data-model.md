# 数据模型设计

## 1. 设计原则

- 原始数据和标准化数据分开存储
- 快照型表和状态型表分开
- 所有关键实体保留 `created_at` 和 `updated_at`
- 统一 `UTC` 时间戳字段命名：`*_at`

## 2. 配置类实体

### 2.1 stations

用途：维护城市和 METAR/结算站点映射。

建议字段：

- `id`
- `city_code`
- `city_name`
- `icao_code`
- `country_code`
- `timezone_name`
- `settlement_unit` (`C` / `F`)
- `wunderground_station_code`
- `latitude`
- `longitude`
- `is_active`

### 2.2 market_station_mappings

用途：保存市场解析出的站点和内部站点配置的比对结果。

建议字段：

- `id`
- `market_id`
- `configured_station_code`
- `parsed_station_code`
- `is_match`
- `validation_status`
- `validated_at`
- `notes`

## 3. 天气数据实体

### 3.1 raw_metar_reports

- `id`
- `station_id`
- `source`
- `report_text`
- `observed_at`
- `fetched_at`

### 3.2 metar_observations

- `id`
- `station_id`
- `observed_at`
- `temperature_c`
- `dewpoint_c`
- `wind_speed_kt`
- `wind_direction_deg`
- `pressure_hpa`
- `visibility_m`
- `raw_report_id`
- `is_stale`

### 3.3 raw_taf_reports

- `id`
- `station_id`
- `report_text`
- `issued_at`
- `fetched_at`

### 3.4 taf_periods

- `id`
- `station_id`
- `taf_report_id`
- `period_start_at`
- `period_end_at`
- `temperature_c`
- `wind_summary`
- `cloud_summary`

## 4. 预报数据实体

### 4.1 ensemble_runs

- `id`
- `station_id`
- `model_name`
- `run_at`
- `fetched_at`
- `member_count`
- `status`

### 4.2 ensemble_members

- `id`
- `ensemble_run_id`
- `member_index`
- `forecast_date_local`
- `max_temp_c`

### 4.3 probability_distributions

- `id`
- `market_id`
- `run_at`
- `forecast_date_local`
- `method_version`
- `trend_adjustment_c`
- `distribution_json`
- `computed_at`

## 5. 市场数据实体

### 5.1 markets

- `id`
- `polymarket_market_id`
- `question`
- `city_code`
- `forecast_date_local`
- `bucket_label`
- `bucket_low`
- `bucket_high`
- `bucket_unit`
- `market_type`
- `settlement_url`
- `parsed_station_code`
- `status`
- `last_seen_at`

### 5.2 market_tokens

- `id`
- `market_id`
- `yes_token_id`
- `no_token_id`

### 5.3 price_snapshots

- `id`
- `market_id`
- `captured_at`
- `yes_bid`
- `yes_ask`
- `yes_mid`
- `no_bid`
- `no_ask`
- `no_mid`
- `last_trade_price`

### 5.4 orderbook_snapshots

- `id`
- `market_id`
- `captured_at`
- `total_bid_depth_usdc`
- `total_ask_depth_usdc`
- `book_json`

## 6. 信号与执行实体

### 6.1 signals

- `id`
- `market_id`
- `signal_at`
- `signal_type` (`BUY` / `SELL` / `SKIP`)
- `model_probability`
- `market_probability`
- `edge_bps`
- `confidence`
- `reasoning_json`
- `is_actionable`

### 6.2 orders

- `id`
- `signal_id`
- `market_id`
- `mode` (`paper` / `live`)
- `side`
- `price`
- `size`
- `status`
- `external_order_id`
- `submitted_at`
- `updated_at`

### 6.3 fills

- `id`
- `order_id`
- `fill_price`
- `fill_size`
- `fee_paid`
- `filled_at`

### 6.4 positions

- `id`
- `market_id`
- `entry_side`
- `avg_entry_price`
- `size`
- `exposure_usdc`
- `status`
- `opened_at`
- `closed_at`

### 6.5 pnl_snapshots

- `id`
- `snapshot_at`
- `unrealized_pnl`
- `realized_pnl`
- `fees_paid`
- `daily_pnl`

### 6.6 risk_events

- `id`
- `event_type`
- `severity`
- `details_json`
- `triggered_at`
- `resolved_at`

## 7. 回测实体

### 7.1 backtest_runs

- `id`
- `name`
- `started_at`
- `completed_at`
- `params_json`
- `summary_json`

### 7.2 backtest_trades

- `id`
- `backtest_run_id`
- `market_id`
- `signal_id`
- `entry_price`
- `exit_price`
- `pnl`

## 8. 建议索引

- `metar_observations(station_id, observed_at desc)`
- `ensemble_runs(station_id, run_at desc)`
- `markets(city_code, forecast_date_local, status)`
- `price_snapshots(market_id, captured_at desc)`
- `signals(market_id, signal_at desc)`
- `orders(status, submitted_at desc)`
- `positions(status, opened_at desc)`

## 9. 必须先做的数据约束

- `markets.polymarket_market_id` 唯一
- `stations.icao_code` 唯一
- `market_station_mappings.is_match = false` 的市场不得参与交易
- 所有概率字段统一使用 `0.0 - 1.0` 浮点表示
