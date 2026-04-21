# 模块文档: 执行与风控 `src/execution`

## 1. 目标

负责把信号转换为模拟订单或真实订单，并确保风险暴露始终在可控范围内。

## 2. 对应 PRD

- FR-501
- FR-502
- FR-503
- FR-504
- FR-505
- FR-506
- FR-601
- FR-602
- FR-603
- FR-604
- FR-605
- FR-606

## 3. 建议文件

```text
src/execution/
  order_executor.py
  position_manager.py
  risk_control.py
  settlement_tracker.py
  sizing.py
```

## 4. 输入与输出

### 输入

- `signals`
- 最新价格 / 订单簿
- 当前持仓与当日 PnL
- 风险配置

### 输出

- `orders`
- `fills`
- `positions`
- `pnl_snapshots`
- `risk_events`

## 5. 子模块职责

### 5.1 `order_executor.py`

职责：

- 接收可执行信号
- 先经过 risk pre-check
- 按 `paper` 或 `live` 模式下单
- 记录订单状态生命周期

建议接口：

```python
async def execute_signal(signal_id: int) -> OrderExecutionResult: ...
```

### 5.2 `position_manager.py`

职责：

- 聚合 fills 成为仓位
- 维护平均成本、暴露、未实现盈亏
- 管理开仓、加仓、减仓、平仓

### 5.3 `risk_control.py`

职责：

- 单笔交易限额
- 日内亏损限额
- 最大并发持仓数
- 单城市暴露和单市场暴露
- 低胜率停机

建议接口：

```python
def check_pre_trade_limits(context: RiskContext) -> RiskDecision: ...
def check_runtime_limits(state: RuntimeRiskState) -> list[RiskEvent]: ...
```

### 5.4 `settlement_tracker.py`

职责：

- 在市场结算后更新头寸状态
- 计算 realized PnL
- 验证 settlement 结果来源

### 5.5 `sizing.py`

职责：

- 第一版用固定上限仓位
- 第二版再接 15% fractional Kelly

## 6. 执行模式设计

### Paper Trading

- 不发送链上或真实 API 下单
- 以当前最优价或保守模拟价成交
- 模拟 taker fee / slippage

### Live Trading

- 仅在通过 go-live gate 后启用
- 与 paper 共享同一套风控与仓位逻辑

## 7. 风控优先级

第一版必须实现：

- `max_single_trade_size`
- `max_daily_loss`
- `max_concurrent_positions`

第二版实现：

- `max_city_exposure`
- `max_market_exposure`
- trailing win rate breaker

## 8. 异常处理

- 下单失败：重试并记录失败原因
- 部分成交：持仓按 fill 实际结果更新
- API 故障：暂停新单，不影响状态查询
- 风险触发：写 `risk_events` 并阻断新单

## 9. 测试要求

### 单元测试

- 仓位均价计算
- PnL 计算
- 单笔限额拦截
- 单日亏损拦截
- 并发持仓数拦截

### 集成测试

- 从信号到 paper order 到 position 的完整链路
- partial fill 对仓位的影响
- 日内亏损阈值触发停机

## 10. 完成标准

- 所有订单状态可追踪
- 风控拦截点明确且可测试
- Paper Trading 可连续运行两周
