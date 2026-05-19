---
name: zt-signal-aggregator
description: Use when the zt-team-leader agent needs to aggregate weighted scores from all sub-agents, calculate overall 涨停 confidence, filter confidence > 50%, and output the signal table for notification.
---

# ZT Signal Aggregator

Aggregate weighted analysis scores from all sub-agents into a single 涨停 confidence score, filter, and output the signal table.

This skill runs on the **zt-team-leader** agent.

## Sub-Agents

| # | Sub-Agent | Role | Inbox Path |
|---|-----------|------|------------|
| 1 | zt-fundamental | 基本面分析 | `/srv/agent-bus/zt-fundamental/outbox/` |
| 2 | zt-technician | 技术面分析 | `/srv/agent-bus/zt-technician/outbox/` |
| 3 | zt-sentiment | 情绪面分析 | `/srv/agent-bus/zt-sentiment/outbox/` |
| 4 | zt-fund-flow | 资金面分析 | `/srv/agent-bus/zt-fund-flow/outbox/` |

## Steps

1. **Collect sub-agent results**
   - Read results from all 4 sub-agent outboxes listed above.
   - Match results by stock code and batch ID.
   - If any sub-agent result is missing for a stock, mark it as "pending" and wait up to 60 seconds. If still missing, proceed with available scores and flag the gap.

2. **Apply weights to each sub-agent score**
   - Default weight for every sub-agent = **1** (equal weight, adjustable via config).
   - Confidence formula: `Σ(score_i × weight_i) / Σ(weight_i)`
   - With default weights (all = 1): confidence = average of available sub-agent scores.

3. **Calculate overall 涨停 confidence**
   - Confidence = Σ(score_i × weight_i) / Σ(weight_i)  (0–100 scale).
   - Round to one decimal place.

4. **Apply confidence filter**
   - Only stocks with confidence > 50% proceed to the signal table.
   - Categorize confidence levels:
     - **80–100%**: 🔴 高置信 (high confidence) — very likely to hit 涨停
     - **65–80%**: 🟡 中高置信 (medium-high confidence) — likely to hit 涨停
     - **50–65%**: 🟢 中等置信 (medium confidence) — possible 涨停
     - **< 50%**: ❌ 不通过 (filtered out) — not included in signal table

5. **Build the signal table**
   - Sort by confidence descending.
   - For each stock, include the 4 core fields:
     - **序号** (rank)
     - **股票名称** (stock name)
     - **参与预测的agent** (which sub-agents contributed scores)
     - **综合置信分** (overall confidence score)
   - Also preserve in JSON: sub-agent individual scores, key signals, missing agents, confidence level.
   - Add metadata: batch ID, aggregation timestamp, total candidates evaluated, total signals produced.

6. **Write signal table to shared location**
   - Write to: `/data/zt-team-leader/signals/{date}/{batch_id}-signal-table.json`
   - Also write a human-readable summary: `/data/zt-team-leader/signals/{date}/{batch_id}-signal-summary.md`

7. **Trigger notification**
   - If there are any high-confidence signals (≥ 80%), immediately trigger the zt-feishu-notifier skill.
   - For medium and medium-high signals, batch and send at the next 10-minute mark.

8. **Archive sub-agent results**
   - Move processed sub-agent result files to archive: `/data/zt-team-leader/archive/{date}/`
   - Keep results for 30 days for review purposes.

## Signal Table Format (JSON)

```json
{
  "batch_id": "20260518-0910",
  "aggregated_at": "2026-05-18T09:12:45+08:00",
  "total_candidates": 87,
  "total_signals": 12,
  "confidence_filter": ">50%",
  "weights": {
    "fundamental": 1,
    "technician": 1,
    "sentiment": 1,
    "fund_flow": 1
  },
  "signals": [
    {
      "序号": 1,
      "股票名称": "示例股份",
      "stock_code": "600123",
      "参与预测的agent": ["fundamental", "technician", "sentiment", "fund_flow"],
      "综合置信分": 73.2,
      "confidence_level": "中高置信",
      "sub_scores": {
        "fundamental": 70,
        "technician": 72,
        "sentiment": 78,
        "fund_flow": 75
      },
      "missing_agents": [],
      "key_signals": [
        "业绩超预期", "多头排列", "MACD金叉",
        "涨停基因强", "板块4股涨停+有逻辑",
        "主力净流入5%以上", "北向资金连续3日增持"
      ]
    }
  ]
}
```

## Human-Readable Summary Format

```markdown
# 涨停信号表 | 2026-05-18 09:12

| 序号 | 股票名称 | 参与预测的agent | 综合置信分 |
|------|----------|-----------------|------------|
| 1 | 示例股份 | fundamental, technician, sentiment, fund_flow | 73.2% 🟡中高 |
| 2 | 示例科技 | technician, sentiment, fund_flow | 65.8% 🟡中高 |

共评估 87 只，发出信号 12 只（高置信 2 / 中高 5 / 中等 5）
```

## Pitfalls

- Do not proceed if 2 or more sub-agent results are missing for a stock; flag it as "incomplete" and exclude from the signal table.
- Weight changes are made manually by the operator based on review engine recommendations; do not change weights dynamically within a trading day.
- If all sub-agents return low scores but one returns an extremely high score (> 90%), investigate for data errors before including in the signal table.
- The signal table can get large (100 candidates × 4 sub-scores); keep the JSON compact and the human-readable summary to top 20 signals.
- Timestamps must be consistent across all sub-agent results; if results span more than 5 minutes, flag as "stale" and consider re-requesting.