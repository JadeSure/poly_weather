# 模块文档: 监控面板 `src/dashboard`

## 1. 目标

为人工监督提供实时可视化，帮助确认信号质量、仓位风险和系统健康状态。

## 2. 对应 PRD

- FR-701
- FR-702
- FR-703
- FR-704
- FR-705
- FR-706
- FR-707

## 3. MVP 页面范围

第一版只做一个单页 dashboard，包含 4 个核心区块：

- 站点天气
- 活跃信号
- 当前持仓
- PnL 概览

## 4. 建议页面结构

```text
src/dashboard/
  src/
    pages/
      DashboardPage.tsx
    components/
      WeatherStationTable.tsx
      SignalTable.tsx
      PositionTable.tsx
      PnlSummary.tsx
      SystemHealthBar.tsx
```

## 5. 页面模块说明

### 5.1 SystemHealthBar

展示：

- worker 心跳
- 最近数据更新时间
- 当前 trading mode
- 是否触发风险暂停

### 5.2 WeatherStationTable

展示：

- 城市
- 站点
- 最新温度
- 观测时间
- stale 标记

### 5.3 SignalTable

展示：

- 城市
- 市场
- model probability
- market probability
- edge
- 建议动作
- skip reason

### 5.4 PositionTable

展示：

- 市场
- 方向
- 仓位
- 成本
- 当前价格
- 未实现盈亏
- 距结算剩余时间

### 5.5 PnlSummary

展示：

- 今日 PnL
- 累计 PnL
- 手续费
- 胜率

## 6. 数据交互建议

- 页面首屏拉取 REST API
- 每 30 到 60 秒轮询刷新
- 不必第一版就上 WebSocket

## 7. 交互要求

- 风险暂停状态要明显
- station mismatch 或 stale 数据用红色高亮
- 高 edge 信号要有视觉强调

## 8. 后续增强

- 桌面通知
- 每城市统计面板
- 信号详情抽屉
- 价格与温度时间序列图

## 9. 测试要求

- 关键表格渲染
- API 异常降级展示
- 空数据和 stale 数据场景

## 10. 完成标准

- 人工值守时，能在一个页面完成观察、判断、排查
