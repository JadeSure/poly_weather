# 模块文档: 回测与研究 `src/backtest`

## 1. 目标

在真实上线前验证策略是否具备统计显著性，并为阈值和参数选择提供依据。

## 2. 对应 PRD

- Phase 4 Backtesting
- 9.1 Go-Live Gate 中所有回测相关条件

## 3. 建议文件

```text
src/backtest/
  data_loader.py
  market_replayer.py
  signal_replayer.py
  execution_simulator.py
  metrics.py
  reports.py
```

## 4. 输入与输出

### 输入

- 历史 METAR
- 历史市场价格快照
- 历史市场元数据
- 策略参数

### 输出

- 回测交易明细
- 汇总指标
- 参数比较报告

## 5. 核心能力

- 加载历史天气和市场数据
- 按时间推进回放
- 在每个时间点运行与线上相同的信号逻辑
- 用模拟成交模型生成交易结果

## 6. 必须统一的逻辑

线上和回测需要共享：

- bucket 解析
- 温度换算
- 结算整度规则
- edge 计算
- 信号过滤
- 风控规则

不能为回测单独重写一套逻辑，否则结果没有可信度。

## 7. 指标要求

- total return
- win rate
- max drawdown
- Sharpe ratio
- average edge
- per-city pnl
- fee-adjusted pnl

## 8. 参数扫描

第一版固定扫描：

- edge threshold: `10% / 12% / 15% / 18% / 20%`
- liquidity threshold
- trend adjustment 强度

## 9. 测试要求

- 给定固定样本得到可复现结果
- 回测交易数、PnL、胜率计算正确

## 10. 完成标准

- 能输出可比的策略报告
- 能支撑 go-live 前的参数选择与风险评估
