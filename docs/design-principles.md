# 原理设计解释

## 1. 系统到底在做什么

WeatherEdge 的目标不是预测“天气会怎样”，而是判断“市场给出的天气概率是否错了”。

对一条天气市场来说，系统会同时看三件事：

- 真实世界已经发生了什么：`METAR`
- 接下来可能发生什么：`ensemble forecast`
- 市场目前怎么定价：`Polymarket yes price`

只要模型概率和市场概率之间出现了足够大的稳定偏差，系统就会生成信号。

## 2. 为什么必须先解决站点映射

天气市场最容易出错的地方不是模型，而是“你到底在预测哪个地方”。

Polymarket 的市场描述通常包含城市名、日期、温度区间和结算来源，但真正有约束力的是结算站点。如果内部使用的观测站点和市场结算站点不一致，哪怕模型再准，信号也是伪信号。

所以系统把下面这件事当作硬约束，而不是软参考：

- 合约解析出的 station code 和本地配置里的 settlement station 必须一致

只有 `station_match_valid = true` 的市场，才可能进入可交易判定。

## 3. 为什么时间一定要分成 UTC 和城市本地日

数据库统一存 `UTC`，这是为了稳定和可回放。但天气市场结算不是按服务器时区，也不是按 UTC 自然日，而是按目标城市的本地日。

这意味着系统必须同时维护两套时间语义：

- 存储和任务调度用 `UTC`
- forecast date、market date、结算归属用 `station.timezone_name`

如果把“今天”错当成服务器所在时区的今天，就会把 forecast、METAR 和市场 bucket 错配到错误的自然日上。这是天气交易里最常见的系统性 bug 之一。

## 4. 温度为什么要先统一再结算

内部 forecast 和 observation 统一使用摄氏度浮点值保存，但最终 market probability 不是直接在浮点温度上计算，而是要走一层“市场结算温度”映射。

核心原因是市场结算是离散的：

- 市场 bucket 是整数温度区间
- 结算规则通常是整度截断，不是四舍五入
- 不同城市可能使用 `C` 或 `F`

因此系统的温度处理流程是：

1. 保留原始浮点温度
2. 按目标市场单位换算
3. 施加市场结算规则
4. 把结果映射到 bucket

只有这样，模型概率和市场概率才是在同一个结算空间里比较。

## 5. 为什么 forecast 要用 ensemble，而不是单条预报

天气市场本质上交易的是概率，不是点预测。

如果只拿一条 deterministic forecast，比如“明天最高 19.4C”，系统只能得到一个点值，无法直接回答：

- 明天落在 `18C` bucket 的概率是多少？
- 明天落在 `20C+` bucket 的概率是多少？

ensemble 的价值在于它天然提供了一组可能路径。系统把每个成员在目标本地日的最高温提取出来，形成一组 daily max samples。然后直接把这些样本当作经验分布，计算 bucket probability：

```text
model_probability = 命中某个 bucket 的成员数 / 总成员数
```

这让模型天然适配二元市场定价。

## 6. 为什么同日修正只对“当前本地日”生效

观测值是强信息，但不能乱用。

如果目标市场是“今天”的市场，那么当天已经观测到的 METAR 温度确实能约束 daily max：

- 当日最高温不可能低于当前已观测到的温度
- 最近几条 METAR 的升温斜率对当天剩余时段有参考价值

但这个修正只适用于“目标市场就是站点当前本地日”的情况。对未来日期强行使用当前观测温度，会把今天的信息泄漏到明天甚至后天，直接污染概率分布。

所以当前实现只在 same-day market 上做两件事：

- 用最近几条 METAR 估计短时升温趋势
- 用最新观测温度给 daily max 加 observation floor

未来日期市场只使用纯 forecast 分布，不吃这个 floor。

## 7. 为什么要先做 market grouping 再出信号

同一个城市同一天通常会有一整条 bucket ladder，例如：

- `<= 14C`
- `15C`
- `16C`
- `17C`
- `>= 18C`

这些市场不是独立的，它们共享同一个 underlying event，也必须共享同一套 forecast distribution。如果逐市场独立建模，会出现两个问题：

- 不同 bucket 之间概率不再自洽
- 容易在互斥 bucket 上同时生成多个 action

因此系统先按 `(city_code, forecast_date_local, bucket_unit)` 把市场分组，然后用同一组 adjusted ensemble members 一次性生成整条 ladder 的概率分布。

这样可以保证：

- 同一组 bucket 的概率来源一致
- 组内比较 edge 时有共同基准
- 后续 selection 和 execution 更简单

## 8. 为什么组内只保留一个 actionable signal

即使 group probability 是统一算出来的，一整条 ladder 里仍然可能有多个 bucket 都看起来“便宜”。但这些市场高度相关，甚至互斥，如果同时进场，风险会被重复放大。

当前策略采用保守做法：

- 先生成整组 signal
- 如果组内有多个 actionable，只保留 `abs(edge_bps)` 最大的那个
- 其余信号降级为 `SKIP`，并标记 `group_dominated`

这相当于明确规定：同一条天气结算事件，一次只表达一个最强观点。

## 9. 为什么 signal 必须去重

数据抓取频率高于市场本身的显著变化频率。如果每轮都把几乎不变的信号重新写入数据库，会带来三个问题：

- 存储噪音过大
- dashboard 难以阅读
- 后续 execution 很容易重复响应同一个信号

所以系统会比较最近一条同市场信号，只要下面这些关键字段都没有明显变化，就不重复落库：

- `signal_type`
- `is_actionable`
- `edge_bps`
- `model_probability`
- `market_probability`
- `reason`

这让信号流更接近“状态变化日志”，而不是“定时重复快照”。

## 10. 为什么交易过滤比 edge 更重要

理论 edge 不代表可交易 edge。系统在 action 之前还会检查：

- 距离结算是否太近
- 市场是否有足够深度
- 天气数据是否 stale
- 站点映射是否有效

只有这些约束都通过，信号才会进入 actionable 状态。原因很直接：天气套利最大的损失常常不是模型错了，而是进了不该进的市场。

## 11. 当前实现边界

当前仓库已经完成：

- 实时天气、forecast、市场数据链路
- 概率建模与 grouped signal engine
- 同日 trend correction
- signal 去重和 tradeability filter

当前还没正式接通：

- `paper trading` 订单执行
- 持仓管理与风险闭环
- 历史回测

所以现在这个系统更准确的定位是：

- 一个已经能持续生成高质量 weather signals 的研究与交易前置系统
- 而不是一个已经 fully automated 的交易系统

## 12. 下一步为什么是 execution

数据链路和 signal quality 基本已经构成闭环，下一步最值得做的不是再加更多模型技巧，而是把 execution 接起来，把以下问题转成可观测的系统行为：

- 信号多久会过期
- 相同 market 是否会重复下单
- 风控会挡掉哪些交易
- 持仓在实时价格下如何变化

一旦 paper trading 接通，系统才能真正从“研究引擎”进入“可验证交易引擎”。
