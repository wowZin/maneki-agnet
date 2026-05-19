---
name: zt-surge-fetcher
description: Use when the zt-trigger agent needs to fetch top 100 surge-speed stocks from the API, build a task list, and send it to the team-leader for 涨停 prediction dispatch.
---

# ZT Surge Fetcher

Fetch candidate stocks that show rapid price surges and forward them as a task list to the team-leader.

This skill runs on the **zt-trigger** agent.

## Trigger Schedule

- Every 10 minutes during 09:00–15:00 on weekdays (A-share trading hours).
- Skip holidays and weekends.

## 数据源

Tushare Pro MCP (已配置在 Hermes Agent config.yaml)

使用的 MCP 工具:
- `rt_k`: 实时日K线行情，支持通配符提取全市场实时数据 (pct_chg涨跌幅排序)
- `cls_stock_shock`: 财联社个股异动 — 涨停/连板/炸板/跌停池数据
- `stk_limit`: 每日涨跌停价格 (用于判断是否已封板)
- `stock_st`: ST股票列表 (用于过滤ST股)

## Steps

1. **拉取实时行情并筛选涨速排名**
   - 调用 MCP 工具 `rt_k`，提取全市场实时日K数据
   - 按 `pct_chg` (涨跌幅) 降序排序，取前 100 只
   - 同时调用 `cls_stock_shock` 获取当日涨停池/连板池，作为辅助参考
   - 调用 `stk_limit` 获取当日涨跌停价格，用于判断是否已封板

2. **Filter and deduplicate**
   - Remove stocks already in the current batch's task list (avoid re-processing the same stock within the same 10-minute window unless its surge speed has increased by >2%).
   - Remove stocks that have already hit the 涨停 price (pct_chg >= 涨停价对应涨幅) — those are no longer candidates.
   - 调用 `stock_st` 过滤 ST 股票。

3. **Enrich each candidate with basic metadata**
   - Stock code, stock name, current price, surge speed %, sector, board type (main / STAR / 创业板), timestamp of detection.

4. **Build the task list**
   - Format as a structured JSON array or YAML list, one entry per candidate stock.
   - Each entry must include enough context for sub-agents to begin analysis without additional lookups.

5. **Send to team-leader**
   - Write the task list to the team-leader inbox: `/srv/agent-bus/zt-team-leader/inbox/surge-task-list-{timestamp}.json`
   - Include metadata: batch ID, fetch timestamp, count of candidates, source API version.

6. **Log the batch**
   - Append a summary line to the daily log: `/data/zt-trigger/logs/{date}-surge-fetch.log`
   - Summary includes: batch ID, timestamp, candidate count, top 5 stock codes by surge speed.

7. **Handle API errors**
   - If the API returns an error or timeout, retry once after 30 seconds.
   - If the second attempt fails, log the failure and skip this batch. Do not send an empty or stale task list.

## Task List Format

```json
{
  "batch_id": "20260518-0910",
  "fetch_timestamp": "2026-05-18T09:10:00+08:00",
  "candidate_count": 87,
  "candidates": [
    {
      "code": "600123",
      "name": "示例股份",
      "price": 12.35,
      "surge_speed_pct": 7.8,
      "sector": "半导体",
      "board_type": "main",
      "detected_at": "2026-05-18T09:09:45+08:00"
    }
  ]
}
```

## Pitfalls

- Do not send duplicate candidates across consecutive batches unless surge speed has materially increased (>2%).
- Do not include stocks that have already reached 涨停 price — they are confirmed, not candidates.
- Do not run on holidays; check the A-share calendar.
- Do not block on API failures; skip the batch and log the error.
- Ensure timestamps are in CST (China Standard Time, UTC+8).