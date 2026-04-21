# 模块文档: 数据采集 `src/data`

## 1. 目标

负责天气观测和机场预报数据的抓取、解析、标准化和持久化，为信号引擎提供可信输入。

## 2. 对应 PRD

- FR-101
- FR-102
- FR-103
- FR-104
- FR-105
- FR-106

## 3. 建议文件

```text
src/data/
  metar_parser.py
  taf_parser.py
  weather_fetcher.py
  weather_repository.py
  weather_models.py
  stale_detector.py
```

## 4. 输入与输出

### 输入

- NOAA AWC METAR API 响应
- NOAA AWC TAF API 响应
- `config/stations.yaml`

### 输出

- `raw_metar_reports`
- `metar_observations`
- `raw_taf_reports`
- `taf_periods`
- stale 状态和异常日志

## 5. 模块职责

### 5.1 `metar_parser.py`

职责：

- 解析 raw METAR
- 提取温度、露点、风向、风速、气压、能见度、观测时间
- 对无法解析的字段给出结构化错误

建议接口：

```python
def parse_metar(report_text: str) -> MetarObservationParsed: ...
```

### 5.2 `taf_parser.py`

职责：

- 解析 TAF 报文和 forecast periods
- 提取时段边界和温度相关信息

建议接口：

```python
def parse_taf(report_text: str) -> list[TafPeriodParsed]: ...
```

### 5.3 `weather_fetcher.py`

职责：

- 定时抓取所有启用站点的 METAR / TAF
- 去重写入
- 调用 stale detector

建议接口：

```python
async def fetch_weather_for_station(station: StationConfig) -> WeatherFetchResult: ...
async def run_weather_loop() -> None: ...
```

### 5.4 `stale_detector.py`

职责：

- 判断站点在过去 4 小时是否有新观测
- 发现 stale 时记录风险事件或告警事件

## 6. 关键业务规则

- 观测时间取报文中的 `observed_at`，不是抓取时间
- 同一观测若重复抓到，需要幂等写入
- NOAA 响应异常不应导致整个循环中断
- 超过 4 小时未更新的数据标记为 stale

## 7. 错误处理

- HTTP 失败：指数退避重试
- 解析失败：记录 raw 文本并标记失败原因
- 单站点失败：不影响其他站点
- 全站点失败：上升为系统级告警

## 8. 测试要求

### 单元测试

- 正常 METAR 解析
- 含负温度的 METAR 解析
- 缺失字段的容错
- TAF 多时间段解析
- stale 判定

### 集成测试

- 模拟 3 个站点成功抓取并入库
- 模拟 NOAA 超时与重试
- 模拟重复观测去重

## 9. 完成标准

- 能连续运行 48 小时
- 每分钟抓取不会写入重复观测
- 面向信号引擎能稳定提供最新观测和最新 TAF
