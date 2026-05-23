---
title: AB对比机制
created: 2026-05-23
updated: 2026-05-23
type: concept
tags: [methodology, weight, ab-comparison]
sources: [raw/articles/review.md, raw/articles/weight-optimizer-v2.md]
---

# AB对比机制

权重变更时用于验证新旧权重优劣的机制。

## 原理

同一份维度评分数据，用新旧两套权重分别计算总分，对比命中率。

**纯数学运算，零API开销**——不重复跑 pipeline。

## 生效条件

当前权重 ≠ 旧权重（`.env` 中配置 `_PREV` 变量）

```
AGENT_WEIGHT_FUNDAMENTAL=1.5
AGENT_WEIGHT_FUNDAMENTAL_PREV=0.7   # 只有不同时才对比
```

## 评分函数

使用 [[五维度评分体系#总分计算-V2.5+]] 的加权Top3择优公式。

## 固化规则

权重变更后至少观察**3个交易日**：

1. 新旧权重同时跑 AB 对比
2. 连续 3 天新权重优于旧 → 固化
3. 否则回滚或继续观察

## 执行时机

每日 18:00 收盘复盘时自动运行（`zt_daily_review.py`）。

## 输出

在复盘报告的飞书卡片中展示：

```
权重AB对比(加权Top3择优)
旧: 推送3只 命中1只 (33%)
新: 推送3只 命中2只 (67%)
结论: 新权重更优
```

## 相关

- [[权重优化引擎]]
- [[五维度评分体系]]
- [[扫描与推送机制#收盘复盘-18-00]]
