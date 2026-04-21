# WeatherEdge 开发文档索引

本文档集基于 `WeatherEdge_PRD_v1.0` 生成，目标是把 PRD 转换为可直接指导编码的模块级开发文档。

## 建议阅读顺序

1. `architecture.md`
2. `design-principles.md`
3. `data-model.md`
4. `modules/data-ingestion.md`
5. `modules/market-ingestion.md`
6. `modules/signal-engine.md`
7. `modules/execution-risk.md`
8. `modules/api-backend.md`
9. `modules/dashboard.md`
10. `modules/backtest.md`
11. `modules/ops-config.md`
12. `development-roadmap.md`

## 文档范围

本目录覆盖以下内容：

- 系统整体架构和进程边界
- 系统原理、关键约束和策略建模解释
- 数据库模型和核心实体
- 各模块职责、输入输出、接口建议、测试要求
- 开发顺序、阶段验收与上线门槛

## 推荐目录结构

```text
weather-edge/
  src/
    data/
    market/
    engine/
    execution/
    api/
    dashboard/
    backtest/
    common/
  config/
  tests/
  docs/
```

## 核心开发原则

- 先做 `Paper Trading`，不要直接接入实盘。
- 所有时间统一存储为 `UTC`，展示层再做时区转换。
- 温度结算按整度截断，不做四舍五入。
- 市场结算站点必须和内部配置站点完全一致。
- 所有交易、信号、行情、观测数据必须落库。

## P0 实现范围

首批必须完成的能力：

- NOAA AWC 的 METAR / TAF 抓取与解析
- Open-Meteo GFS ensemble 抓取
- Polymarket 市场发现、价格、订单簿抓取
- 概率计算、edge 计算、信号过滤
- Paper Trading 下单与持仓管理
- 基础风控
- FastAPI 查询接口
- 最小监控面板

## 建议先做的城市

首批只挑 5 到 10 个市场做验证，优先：

- London `EGLC`
- Seoul `RKSI`
- Chicago `KORD`
- Miami `KMIA`
- Paris `LFPG`

原因：

- 站点映射在 PRD 中明确
- 覆盖摄氏和华氏两种单位
- 便于提前验证单位换算和结算逻辑
