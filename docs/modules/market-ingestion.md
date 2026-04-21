# 模块文档: 市场采集 `src/market`

## 1. 目标

负责发现 Polymarket 天气市场、解析合约元数据、抓取价格与订单簿，并验证市场结算站点是否可信。

## 2. 对应 PRD

- FR-301
- FR-302
- FR-303
- FR-304
- FR-305
- FR-306

## 3. 建议文件

```text
src/market/
  polymarket_client.py
  contract_parser.py
  market_fetcher.py
  market_repository.py
  liquidity.py
```

## 4. 输入与输出

### 输入

- Polymarket CLOB API 市场列表
- Polymarket orderbook API
- `stations.yaml`

### 输出

- `markets`
- `market_tokens`
- `price_snapshots`
- `orderbook_snapshots`
- `market_station_mappings`

## 5. 模块职责

### 5.1 `polymarket_client.py`

职责：

- 获取天气类市场列表
- 获取单市场价格和订单簿
- 统一处理 API 错误和重试

建议接口：

```python
async def list_weather_markets() -> list[dict]: ...
async def get_orderbook(token_id: str) -> dict: ...
async def get_market_details(market_id: str) -> dict: ...
```

### 5.2 `contract_parser.py`

职责：

- 从 question / description / settlement URL 中提取
  - 城市
  - 日期
  - bucket
  - 单位
  - station code
- 生成标准化 market 记录

重点：

- settlement URL 中的站点码必须可解析
- 如果 bucket 是 `32-33F` 这种区间，要转成统一 low/high 表示

### 5.3 `market_fetcher.py`

职责：

- 定时同步市场主数据
- 定时抓价格与订单簿
- 识别不活跃和已关闭市场

### 5.4 `liquidity.py`

职责：

- 计算订单簿总深度
- 标记低于阈值的 illiquid 市场

## 6. 关键业务规则

- 只允许 `station mapping` 校验通过的市场进入后续交易链路
- 价格快照至少按 1 分钟粒度保存
- 流动性低于 `$50` 的市场默认不产生可执行信号

## 7. 解析风险

- 市场标题格式可能变动
- settlement URL 可能缺失或不规范
- 市场单位可能不一致
- 一个城市可能同时有多个不同 bucket 市场

## 8. 测试要求

### 单元测试

- 标题解析为城市和日期
- URL 解析为 station code
- 摄氏 / 华氏 bucket 解析
- 订单簿深度计算

### 集成测试

- 从 mock 市场列表中抽取天气市场
- 落库价格快照
- 标记 illiquid 市场
- 拒绝 station mismatch 市场

## 9. 完成标准

- 可稳定发现活跃天气市场
- 市场和 token 关系明确
- 可按市场维度查询最近价格、深度、站点映射状态
