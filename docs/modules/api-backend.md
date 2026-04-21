# 模块文档: API 后端 `src/api`

## 1. 目标

向 Dashboard、运营排查和后续自动化工具提供统一查询入口，并暴露健康检查和基础控制接口。

## 2. 建议文件

```text
src/api/
  main.py
  deps.py
  schemas.py
  routers/
    health.py
    weather.py
    markets.py
    signals.py
    positions.py
    risk.py
    system.py
```

## 3. 主要职责

- 提供只读查询接口
- 提供健康检查
- 提供最小控制接口，例如暂停交易、恢复 paper trading

## 4. 建议路由

### `GET /health`

返回：

- 服务状态
- 数据库连接状态
- 最近 weather fetch 时间
- 最近 market fetch 时间
- 最近 signal loop 时间

### `GET /weather/stations`

返回：

- 全部站点
- 最近观测
- stale 状态

### `GET /markets/active`

返回：

- 活跃市场
- bucket
- 单位
- 最新价格
- 流动性
- station mapping 状态

### `GET /signals`

查询参数建议：

- `actionable`
- `city`
- `since`

### `GET /positions`

返回：

- 开放持仓
- 平均成本
- 当前价格
- unrealized pnl
- settlement countdown

### `GET /pnl/summary`

返回：

- 当日
- 7 日
- 全部

### `GET /risk/state`

返回：

- 是否允许开新仓
- 当前日亏损
- 当前并发持仓
- 最近风险事件

### `POST /system/trading/pause`

说明：

- 第一版只做本地保护开关
- 需要简单鉴权

## 5. API 设计原则

- 返回结构统一
- 使用分页和时间过滤避免全表扫描
- 错误返回带 `code` 和 `message`
- 时间统一 ISO 8601 UTC

## 6. 响应结构建议

```json
{
  "data": {},
  "meta": {
    "generated_at": "2026-04-08T12:00:00Z"
  },
  "error": null
}
```

## 7. 安全要求

- 控制类接口必须鉴权
- 不返回敏感密钥
- 日志中不打印钱包私钥和完整 token

## 8. 测试要求

- health endpoint
- 信号和持仓分页查询
- 异常查询参数校验
- 暂停交易接口鉴权

## 9. 完成标准

- Dashboard 所需数据均可经 API 获取
- 能快速回答系统是否健康、是否允许交易、当前仓位和 PnL 状态
