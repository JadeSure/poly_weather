# WeatherEdge

WeatherEdge 是一个面向 `Polymarket` 天气市场的自动化研究系统。它的目标不是做“天气展示”，而是把 `NOAA AWC` 的观测数据、`Open-Meteo ensemble` 的温度分布，以及 `Polymarket` 的市场价格接到同一条链路里，持续寻找天气合约的概率错价。

## 当前实现状态

当前仓库已经跑通了从数据采集到信号生成的主干链路：

- `NOAA AWC` 的 `METAR / TAF` 抓取、解析和入库
- `Open-Meteo ensemble` 抓取，并按站点本地自然日聚合 daily max 成员分布
- `Polymarket` 天气市场发现、bucket 解析、价格快照和 orderbook 深度抓取
- `signal engine` 的概率建模、同日 trend correction、market grouping 和 signal 去重
- `FastAPI` 查询接口、`APScheduler` worker、SQLite 持久化和 worker heartbeat

当前还没有正式接通的部分：

- `paper trading` 执行层
- 持仓生命周期与风控闭环
- dashboard 前端
- 回测与结算追踪

## 系统原理

系统的基本判断逻辑很简单：

1. 用 forecast ensemble 估计某个城市某个本地日的最高温分布。
2. 把这个分布映射到 Polymarket 的离散 bucket 上，得到 `model probability`。
3. 用市场最新 `yes` 价格近似 `market probability`。
4. 计算 `edge = model_probability - market_probability`。
5. 当 edge 足够大，且流动性、站点映射、数据新鲜度、结算时间都满足约束时，生成 actionable signal。

更完整的设计解释见 [docs/design-principles.md](docs/design-principles.md)。

## 运行流程

```text
NOAA AWC ----> weather_fetcher ----> metar / taf tables
Open-Meteo --> forecast_fetcher ---> ensemble tables
Polymarket --> market_fetcher -----> market / price snapshot tables

weather + forecast + market -------> signal_engine -------> signals
all tables ------------------------> FastAPI -------------> query APIs
```

## 项目结构

```text
src/
  api/         FastAPI 查询接口
  common/      配置、日志、时间工具
  data/        NOAA AWC 采集与解析
  db/          SQLModel 模型、session、seed、runtime settings
  engine/      概率建模、trend correction、signal 生成
  execution/   执行、持仓、风控（当前仍在补全）
  market/      Polymarket 市场发现与价格采集
  worker/      APScheduler 任务调度
config/        站点映射和日志配置
docs/          设计和模块开发文档
tests/         单元测试
```

## 快速开始

初始化环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
./.venv/bin/pip install -e ".[dev]"
cp .env.example .env
```

启动 API：

```bash
./.venv/bin/uvicorn src.api.main:app --reload
```

启动 worker：

```bash
./.venv/bin/python -m src.worker.main
```

运行测试：

```bash
./.venv/bin/python -m pytest -v
```

代码检查：

```bash
./.venv/bin/ruff check src/ tests/
```

默认数据库文件是仓库根目录下的 `weatheredge.db`。

## 当前可用接口

### 系统

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/health` | 系统状态 + 各 worker 最近心跳（最多 10 条） |
| `GET` | `/system/stats` | 各表行数、时间范围、全部 worker 心跳 |
| `POST` | `/system/trading/pause` | 暂停或恢复交易，body: `{"paused": true/false}` |

### 天气

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/weather/stations` | 所有站点 + 各站最新 METAR 观测温度 |
| `GET` | `/weather/taf/latest` | 各站最新 TAF 结构化数据；支持 `?city_code=` 过滤 |
| `GET` | `/weather/taf/summary` | 同上，附带中文解释；支持 `?city_code=` 过滤 |
| `GET` | `/weather/forecast/latest` | 各站最新 ensemble 成员原始数据（日最高温）；支持 `?city_code=` 过滤 |
| `GET` | `/weather/forecast/summary` | 同上，附均值/中位数/分位数摘要；支持 `?city_code=` 过滤 |

### 市场

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/markets/active` | 所有活跃市场 + 各市场最新价格快照 |
| `GET` | `/markets/{market_id}/price-history` | 指定市场的价格历史；支持 `?limit=`（默认 500，最大 5000） |
| `GET` | `/markets/{market_id}/orderbook` | 指定市场最新 orderbook 深度（yes/no 双边） |

### 信号

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/signals` | 信号列表；支持 `?actionable=true/false`、`?city_code=`、`?limit=`（默认 50） |
| `GET` | `/signals/summary` | 按城市和日期汇总的信号统计（数量、edge bps） |

### 持仓与风控

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/positions` | 所有持仓记录（按开仓时间倒序） |
| `GET` | `/risk/state` | 当前风控状态：是否暂停、持仓数量、最近风控事件 |

## 查看天气数据

当前 `weather` 相关接口分成三类：

- `GET /weather/stations`
  返回每个站点最新的 `METAR` 观测，适合看“当前温度”
- `GET /weather/taf/latest`
  返回每个站点最新的 `TAF` 原始结构化数据
- `GET /weather/taf/summary`
  返回带中文解释的 `TAF` 摘要
- `GET /weather/forecast/latest`
  返回 `Open-Meteo ensemble` 的原始日最高温成员数据
- `GET /weather/forecast/summary`
  返回 `Open-Meteo ensemble` 的中文摘要，包括均值、中位数、分位数和区间

几个常用命令：

```bash
curl -s http://127.0.0.1:8000/weather/stations | python -m json.tool
curl -s "http://127.0.0.1:8000/weather/taf/summary?city_code=london" | python -m json.tool
curl -s "http://127.0.0.1:8000/weather/forecast/summary?city_code=london" | python -m json.tool
```

这些接口的数据来源分别是：

- `METAR / TAF` 来自 `NOAA AWC`
- `forecast` 来自 `Open-Meteo ensemble`

其中 `GET /weather/forecast/latest` 的 `days[].members[].max_temp_c` 表示：

- 不是某个时刻的温度
- 而是某个 ensemble 成员对“该本地自然日最高温”的预测值
- 后续信号引擎会用这组成员分布去计算 bucket probability

## 关键设计约束$$

- 所有时间统一以 `UTC` 存储，城市结算逻辑按站点 `timezone` 转换到本地自然日。
- 温度结算按市场规则做整度结算，不做四舍五入。
- 只有 `station_match_valid = true` 的市场才允许进入可交易判断。
- 对同一城市同一日期的一整条 bucket ladder，必须使用同一组 forecast members 统一计算概率。
- 同一 ladder 内只保留最强的 actionable signal，避免在互斥 bucket 上重复下注。

## 文档入口

- [docs/README.md](docs/README.md)
- [docs/architecture.md](docs/architecture.md)
- [docs/design-principles.md](docs/design-principles.md)
- [docs/data-model.md](docs/data-model.md)
- [docs/development-roadmap.md](docs/development-roadmap.md)
