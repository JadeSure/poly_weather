# 系统架构设计

## 1. 目标

WeatherEdge 是一个单机可运行、后续可扩展到多进程部署的自动化天气套利系统。架构重点不是高频，而是稳定、可追溯、可回放。

## 2. 核心模块

### 2.1 数据层

- `src/data`: 天气观测与预测数据采集
- `src/market`: Polymarket 市场、订单簿、价格快照采集

### 2.2 策略层

- `src/engine`: 概率计算、edge 计算、信号生成

### 2.3 执行层

- `src/execution`: 下单、持仓、风控、结算

### 2.4 展示层

- `src/api`: FastAPI 查询与控制接口
- `src/dashboard`: React 监控面板

### 2.5 研究层

- `src/backtest`: 历史回放、回测和指标统计

## 3. 运行模型

建议第一版使用单仓库、单数据库、多循环任务架构：

- `weather_fetcher` 每 60 秒执行
- `market_fetcher` 每 60 秒执行
- `forecast_fetcher` 每 6 小时执行，最好对齐 `00Z / 06Z / 12Z / 18Z`
- `signal_loop` 每 5 分钟执行
- `position_update_loop` 每 30 到 60 秒执行
- `risk_check_loop` 每次下单前和每轮持仓更新后执行

## 4. 逻辑数据流

```text
NOAA AWC ----> weather_fetcher ----> weather tables
Open-Meteo --> forecast_fetcher ---> forecast tables
Polymarket --> market_fetcher -----> market tables / price snapshots / orderbooks

weather + forecast + market ---> signal_engine ---> signals
signals + risk_state -----------> order_executor --> orders / fills / positions
settled markets ----------------> settlement_tracker -> realized pnl

all tables ---------------------> FastAPI ----------> dashboard
historical tables -------------> backtest engine ---> reports
```

## 5. 进程边界建议

第一版可以先做一个 FastAPI 进程和一个 scheduler 进程：

- `app_api`: 提供 REST API
- `app_worker`: 跑 APScheduler 或 async loops

后续再按压力拆成：

- weather worker
- market worker
- signal worker
- execution worker

## 6. 关键设计约束

### 6.1 时间

- 数据库存 `UTC`
- 市场自然日和城市本地日要显式建模
- settlement date 不能只靠系统时区判断

### 6.2 温度

- 内部建议统一保存 `celsius_raw`
- 根据市场配置推导 `settlement_unit_value`
- 结算规则采用整度截断

### 6.3 站点映射

- 市场元数据中的 settlement URL 是一等公民
- 只有站点映射校验通过的市场才允许进入信号计算

### 6.4 可回放

- 原始响应要尽量保留
- 每轮信号要存上下文快照
- 订单状态变化要完整留痕

## 7. 技术选型建议

- Python 3.11+
- FastAPI
- SQLAlchemy 2.x 或 SQLModel
- APScheduler
- SQLite 起步，保留 PostgreSQL 迁移能力
- React + Tailwind CSS

## 8. 非功能要求映射

- 可恢复性：任务状态和业务状态都必须从数据库恢复
- 可观测性：统一 JSON 日志 + 健康检查接口
- 安全性：钱包和 API key 只允许通过环境变量注入
- 延迟：单轮信号生成不超过 10 秒

## 9. MVP 范围

MVP 不包含：

- Claude second opinion
- 自动切换 Iowa Mesonet 备源
- 实盘下单
- Telegram / Discord 告警

MVP 必须包含：

- 实时数据链路
- 概率与信号
- Paper Trading
- 风控
- 面板查询
