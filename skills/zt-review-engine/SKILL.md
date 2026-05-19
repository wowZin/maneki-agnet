---
name: zt-review-engine
description: Use when the zt-team-leader agent needs to perform a daily 16:00 post-market review — comparing predictions vs actual results, scoring each sub-agent by accuracy, and generating a review report.
---

# ZT Review Engine

Perform a daily post-market review at 16:00, comparing the day's predictions against actual 涨停 results and scoring sub-agent accuracy.

This skill runs on the **zt-team-leader** agent.

## Sub-Agents

| # | Sub-Agent | Role |
|---|-----------|------|
| 1 | zt-fundamental | 基本面分析 |
| 2 | zt-technician | 技术面分析 |
| 3 | zt-sentiment | 情绪面分析 |
| 4 | zt-fund-flow | 资金面分析 |

## Steps

1. **Trigger at 16:00 CST**
   - Only runs on weekdays (A-share trading days).
   - Skip holidays.

2. **Collect today's prediction data**
   - Read all signal tables from today: `/data/zt-team-leader/signals/{date}/*-signal-table.json`
   - Consolidate all predicted stocks across all batches.
   - For each predicted stock, extract: confidence score, confidence level, sub-agent scores, key signals, prediction timestamp.

3. **Fetch actual 涨停 results**
   - 调用 MCP 工具 `limit_list`，获取当日涨跌停统计 (封住/炸板/打开次数)
   - 调用 MCP 工具 `stk_limit`，获取当日涨跌停价格
   - 调用 MCP 工具 `limit_list_d`，获取涨跌停和炸板详细数据
   - Parse: list of all stocks that hit 涨停 today, with timestamps, seal sustainability (封住/炸板).
   - Also identify stocks that approached but did not reach 涨停 (pct_chg > 7% but < 涨停价).

4. **Match predictions to actuals**
   - For each predicted stock, determine the outcome:
     - **命中涨停 (Hit)**: Stock hit 涨停 AND sealed (封住) — full hit.
     - **涨停但炸板 (Hit but broken)**: Stock hit 涨停 but the seal was broken — partial hit.
     - **接近涨停 (Near miss)**: Stock approached 涨停 (> 7% rise) but did not reach it.
     - **未命中 (Miss)**: Stock did not make a significant move.
   - For each stock that actually hit 涨停 but was NOT predicted, record it as a **漏判 (Missed)**.

5. **Calculate overall prediction accuracy**
   - Precision = `命中涨停数 / 总预测数` (of stocks with confidence > 50%)
   - Recall = `命中涨停数 / 实际涨停数` (of all stocks that hit 涨停 today)
   - F1 = `2 * precision * recall / (precision + recall)`
   - High-confidence precision = `命中涨停数(高置信) / 高置信预测数`

6. **Score each sub-agent by accuracy**
   - For each sub-agent (fundamental, technician, sentiment, fund_flow):
     - Calculate the average score given to stocks that actually hit 涨停 (should be high if the agent is accurate).
     - Calculate the average score given to stocks that did NOT hit 涨停 (should be low if the agent is accurate).
     - Discrimination power = `avg_score_hit - avg_score_miss` (higher = better).
     - Score the sub-agent: discrimination power as a percentage.
   - Rank sub-agents by discrimination power.

7. **Identify patterns in errors**
   - Find common traits among false positives (predicted but missed): are they concentrated in certain sectors? Certain board types? Certain confidence levels?
   - Find common traits among false negatives (missed predictions): were they in sectors with low coverage? Were sub-agent scores divergent?

8. **Generate the review report**
   - Write JSON report: `/data/zt-team-leader/reviews/{date}-review.json`
   - Write human-readable report: `/data/zt-team-leader/reviews/{date}-review.md`
   - Include: overall metrics, per-sub-agent scores, error patterns, recommendations for weight adjustment.

9. **Trigger notification**
   - Call the zt-feishu-notifier skill to send the review report to Feishu.

10. **Archive today's data**
    - Compress and archive: signal tables, sub-agent results, actual results.
    - Keep 30 days of detailed data; older data can be aggregated into weekly/monthly summaries.

## Weight Adjustment Policy

权重调整由人工执行，不是自动调整：
- 复盘报告生成各子Agent的准确率排名。
- 排名靠后的子Agent，由操作员决定是否降低其权重。
- 排名靠前的子Agent，由操作员决定是否增加其权重。
- 调整权重时修改配置文件中的 weight 值（默认 = 1），重启后生效。
- 建议至少观察 5 个交易日的趋势后再做调整，不要基于单日结果修改。

## Review Report Format (JSON)

```json
{
  "date": "2026-05-18",
  "review_generated_at": "2026-05-18T16:05:00+08:00",
  "overall_metrics": {
    "total_predictions": 12,
    "total_actual_zt": 45,
    "hits": 8,
    "hits_but_broken": 2,
    "near_misses": 1,
    "misses": 1,
    "missed_opportunities": 37,
    "precision": 0.667,
    "recall": 0.178,
    "f1": 0.282,
    "high_confidence_precision": 0.85
  },
  "sub_agent_scores": {
    "fundamental": {
      "avg_score_hit": 76.3,
      "avg_score_miss": 49.8,
      "discrimination_power": 26.5,
      "rank": 1
    },
    "technician": {
      "avg_score_hit": 78.5,
      "avg_score_miss": 52.3,
      "discrimination_power": 26.2,
      "rank": 2
    },
    "fund_flow": {
      "avg_score_hit": 69.8,
      "avg_score_miss": 51.2,
      "discrimination_power": 18.6,
      "rank": 3
    },
    "sentiment": {
      "avg_score_hit": 71.3,
      "avg_score_miss": 55.8,
      "discrimination_power": 15.5,
      "rank": 4
    }
  },
  "error_patterns": {
    "false_positive_traits": ["创业板股票误判率高", "低置信度信号噪音多"],
    "false_negative_traits": ["午后涨停股预测遗漏", "次新股覆盖率低"]
  },
  "recommendations": ["增加午后轮次扫描", "创业板权重需下调", "基本面分析近期区分力最高，考虑增加权重"]
}
```

## Human-Readable Review Format

```markdown
# 涨停预测复盘 | 2026-05-18

## 整体表现
- 总预测: 12 只 | 实际涨停: 45 只
- 命中涨停: 8 | 涨停但炸板: 2 | 接近: 1 | 未命中: 1
- 精确率: 66.7% | 召回率: 17.8% | F1: 0.282
- 高置信精确率: 85.0%

## 子智能体排名
| 排名 | 智能体 | 命中均分 | 未命中均分 | 区分力 |
|------|--------|----------|-----------|--------|
| 1 | 基本面 | 76.3 | 49.8 | 26.5 |
| 2 | 技术面 | 78.5 | 52.3 | 26.2 |
| 3 | 资金面 | 69.8 | 51.2 | 18.6 |
| 4 | 情绪面 | 71.3 | 55.8 | 15.5 |

## 误判分析
- 误报特征: 创业板股票误判率高, 低置信度信号噪音多
- 漏判特征: 午后涨停股预测遗漏, 次新股覆盖率低

## 权重调整建议
- 基本面分析近期区分力最高，考虑增加权重
- 增加午后轮次扫描
- 创业板权重需下调
```

## 数据源

Tushare Pro MCP (已配置在 Hermes Agent config.yaml)

使用的 MCP 工具:
- `limit_list`: 每日涨跌停统计 (封住/炸板数据)
- `stk_limit`: 每日涨跌停价格 (验证是否达到涨停价)
- `limit_list_d`: 涨跌停和炸板详细数据

## Pitfalls

- The review must use confirmed actual 涨停 data from Tushare MCP, not estimated or partial data. If the MCP is unavailable at 16:00, retry at 16:15 and 16:30. Do not generate the review with incomplete actual data.
- Recall will typically be low (we only predict from the top 100 surge-speed stocks, not the entire market); this is expected and should be noted in the report.
- Do not adjust weights automatically based on a single day's review; weight changes are manual and should consider trends over 5+ trading days.
- 涨停但炸板 (hit but broken) stocks are partial successes; count them separately from full hits in the metrics.
- Sub-agent discrimination power is the most meaningful accuracy metric; raw precision can be misleading because prediction count varies.