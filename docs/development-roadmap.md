# 开发路线图

## 1. 总体原则

开发顺序必须服从依赖关系，不要先做面板或复杂执行，先确认数据和信号正确。

## 2. 阶段拆分

### Phase 0: 手工验证

目标：

- 确认 edge 不是伪信号
- 建立首批城市和站点映射表

交付物：

- 手工观测记录
- station mapping 校验表

### Phase 1: 数据底座

实现：

- `stations.yaml`
- 数据库 schema
- METAR / TAF 抓取与解析
- 市场发现与价格快照

验收：

- 连续 48 小时数据稳定入库

### Phase 2: 信号引擎

实现：

- ensemble forecast
- probability distribution
- trend adjustment
- signal generation
- signal filters

验收：

- 产生可解释信号
- 人工抽查前 50 条信号

### Phase 3: Paper Trading

实现：

- order executor
- position manager
- risk control

验收：

- 至少 100 笔模拟交易
- PnL 跟踪正确

### Phase 4: 回测

实现：

- 历史数据加载
- 策略回放
- 参数扫描

验收：

- 形成回测报告和 go-live 建议

### Phase 5: 面板与部署

实现：

- dashboard
- API
- docker compose

验收：

- 单页即可监控系统状态、信号、仓位和 PnL

## 3. 编码优先级

### P0

- `src/data`
- `src/market`
- `src/engine`
- `src/execution` 的 paper trading 和核心风控
- `src/api` 的只读接口

### P1

- dashboard 统计增强
- Kelly sizing
- 更丰富的指标和报表

### P2

- second opinion
- 外部告警
- 早退策略
- 自动 failover

## 4. 每阶段 Definition of Done

- 有文档
- 有测试
- 有结构化日志
- 有错误处理
- 有最小可运行入口

## 5. 第一周建议任务

1. 建仓库骨架和配置文件
2. 建数据库和基础模型
3. 完成 METAR / TAF parser
4. 完成 Polymarket market parser
5. 建最小 worker loop

## 6. Go-Live 前硬门槛

- 14 天以上 paper trading
- 100 笔以上模拟交易
- 胜率与 Sharpe 达标
- 所有 P0 风控可被手动触发验证
- 零 station mismatch 交易
