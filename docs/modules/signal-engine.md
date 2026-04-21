# 模块文档: 概率与信号引擎 `src/engine`

## 1. 目标

把天气观测、机场预报和市场价格转换为可执行信号，是系统的核心 alpha 模块。

## 2. 对应 PRD

- FR-201
- FR-202
- FR-203
- FR-204
- FR-205
- FR-206
- FR-401
- FR-402
- FR-403
- FR-404
- FR-405
- FR-406

## 3. 建议文件

```text
src/engine/
  ensemble_fetcher.py
  probability.py
  rounding.py
  trend_adjustment.py
  signal_generator.py
  signal_filters.py
```

## 4. 输入与输出

### 输入

- 最新 METAR 观测
- 最新 TAF 时段
- GFS ensemble 成员预报
- 最新市场价格和订单簿

### 输出

- `probability_distributions`
- `signals`

## 5. 子模块职责

### 5.1 `ensemble_fetcher.py`

职责：

- 拉取 GFS ensemble 数据
- 存储 31-member max temperature forecast
- 对齐到市场关注的本地自然日

### 5.2 `probability.py`

职责：

- 计算 `P(max_temp >= T)`
- 输出完整 bucket distribution
- 支持摄氏 / 华氏转换

建议接口：

```python
def build_probability_distribution(
    ensemble_members: list[float],
    latest_observation_c: float | None,
    market_buckets: list[Bucket],
    unit: str,
) -> ProbabilityDistribution: ...
```

### 5.3 `rounding.py`

职责：

- 实现结算整度规则
- 统一处理 `C -> F` 换算后的截断逻辑

必须明确：

- `23.7C -> 23C`
- 不能使用四舍五入

### 5.4 `trend_adjustment.py`

职责：

- 依据最新 METAR 温度轨迹相对 TAF 的偏离，对分布做轻量偏移
- 第一版保持可解释，不要上复杂模型

### 5.5 `signal_generator.py`

职责：

- 计算 `edge = model_prob - market_prob`
- 生成 `BUY / SELL / SKIP`
- 写入 reasoning context

### 5.6 `signal_filters.py`

职责：

- 过滤距离结算小于 6 小时的市场
- 过滤低流动性市场
- 过滤 stale weather data
- 过滤 station mismatch 市场

## 6. 核心算法说明

第一版建议采用可解释算法，而不是黑盒模型：

1. 从 ensemble 成员取出目标日 `max_temp_c`
2. 依据最新 METAR 与 TAF 偏差计算一个小幅 `trend_adjustment_c`
3. 将每个 ensemble 成员整体平移
4. 按市场单位做转换
5. 应用整度截断
6. 统计每个 bucket 的命中频率，形成概率分布
7. 与市场价格比较得到 edge

## 7. 信号规则

- `edge > 0.15` 生成 `BUY`
- 已持仓时，`edge < -0.15` 允许 `SELL`
- `0.10 <= edge < 0.15` 仅记录为弱信号，后续可接 second opinion

## 8. 信号日志要求

每条信号至少保留：

- 观测时间
- 市场时间
- 最新温度
- TAF 参考值
- trend adjustment
- model probability
- market implied probability
- edge
- liquidity
- skip reason 或 buy/sell reason

## 9. 测试要求

### 单元测试

- 温度单位转换
- 结算整度截断
- bucket distribution 求和约等于 1
- edge 计算
- filter 行为

### 集成测试

- 给定历史天气和价格样本能生成预期信号
- stale / illiquid / near settlement 市场被正确过滤

## 10. 完成标准

- 生成的每条信号都可解释和可追溯
- 同一输入在重复执行时结果稳定
- 概率与价格比较逻辑可用于 paper trading
