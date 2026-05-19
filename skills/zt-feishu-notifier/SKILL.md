---
name: zt-feishu-notifier
description: Use when the zt-team-leader agent needs to send 涨停 signal tables and daily review reports to a Feishu webhook for team notification.
---

# ZT Feishu Notifier

Send 涨停 signal tables and daily review reports to a Feishu group via webhook.

This skill runs on the **zt-team-leader** agent.

## Steps

1. **Receive notification trigger**
   - Triggered by zt-signal-aggregator when new signal table is ready (high-confidence signals sent immediately, others batched).
   - Triggered by zt-review-engine when daily review report is ready at ~15:30.

2. **Load the Feishu webhook configuration**
   - Read webhook URL from environment: `FEISHU_ZT_WEBHOOK_URL`
   - Read optional secret from environment: `FEISHU_ZT_WEBHOOK_SECRET` (for sign verification)
   - If webhook URL is not configured, log a warning and skip notification. Do not fail the pipeline.

3. **Format the signal table notification**
   - For real-time signal notifications (during trading hours):
     - Build a Feishu interactive card message.
     - Title: "🚨 涨停信号 | {date} {time}"
     - Content: top signals in a table format (stock code, name, confidence, level, key signals summary).
     - Color coding: 🔴 red for high confidence (≥80%), 🟡 yellow for medium-high (65–80%), 🟢 green for medium (50–65%).
     - Footer: "共 {total} 只信号 | 评估 {candidates} 只 | 批次 {batch_id}"
   - For high-confidence signals (≥ 80%), send immediately as a separate urgent notification with a bell icon 🔔.

4. **Format the review report notification**
   - For daily review notifications (15:30):
     - Build a Feishu interactive card message.
     - Title: "📊 涨停预测复盘 | {date}"
     - Content: overall metrics (precision, recall, F1), sub-agent ranking table, top error patterns, recommendations.
     - Include a summary of the day's best and worst predictions.
     - Footer: "明日继续优化 | 子智能体区分力: {best_agent} > {worst_agent}"

5. **Construct the Feishu message payload**
   - Use Feishu interactive card format (`msg_type: interactive`).
   - Card structure:
     - `config`: wide_screen_mode = true
     - `header`: title, template color (based on signal type)
     - `elements`: markdown content, table, action buttons
   - Add an action button linking to the detailed JSON report: "查看详情 → {report_url}"

6. **Send to Feishu webhook**
   - POST to: `{FEISHU_ZT_WEBHOOK_URL}`
   - Headers: `Content-Type: application/json`
   - If `FEISHU_ZT_WEBHOOK_SECRET` is set, calculate sign: `timestamp + "\n" + secret`, then SHA256, base64 encode, add as `X-Lark-Signature` header.
   - Timeout: 10 seconds.
   - On success (HTTP 200), log the notification ID.
   - On failure, retry up to 3 times with 5-second intervals.
   - If all retries fail, log the error and write the unsent message to `/data/zt-team-leader/notifications/pending/` for manual retry.

7. **Log the notification**
   - Append to daily notification log: `/data/zt-team-leader/logs/{date}-feishu-notifications.log`
   - Include: timestamp, message type (signal/review), signal count, Feishu response status, notification ID.

## Feishu Card Message Example (Signal)

```json
{
  "msg_type": "interactive",
  "card": {
    "config": { "wide_screen_mode": true },
    "header": {
      "title": { "tag": "plain_text", "content": "🚨 涨停信号 | 2026-05-18 09:12" },
      "template": "red"
    },
    "elements": [
      {
        "tag": "markdown",
        "content": "**高置信信号 🔴**\n| 代码 | 名称 | 置信度 | 关键信号 |\n|------|------|--------|----------|\n| 600123 | 示例股份 | 82.5% | 多头排列,放量3倍,板块4股涨停 |\n\n**中高置信信号 🟡**\n| 代码 | 名称 | 置信度 | 关键信号 |\n|------|------|--------|----------|\n| 300456 | 示例科技 | 73.2% | MACD金叉,主力净流入,2连板 |"
      },
      {
        "tag": "markdown",
        "content": "共 12 只信号 | 评估 87 只 | 批次 20260518-0910"
      },
      {
        "tag": "action",
        "actions": [
          {
            "tag": "button",
            "text": { "tag": "plain_text", "content": "查看详情" },
            "type": "primary",
            "url": "https://internal-dashboard/zt-signals/20260518"
          }
        ]
      }
    ]
  }
}
```

## Feishu Card Message Example (Review)

```json
{
  "msg_type": "interactive",
  "card": {
    "config": { "wide_screen_mode": true },
    "header": {
      "title": { "tag": "plain_text", "content": "📊 涨停预测复盘 | 2026-05-18" },
      "template": "blue"
    },
    "elements": [
      {
        "tag": "markdown",
        "content": "**整体表现**\n精确率: 66.7% | 召回率: 17.8% | F1: 0.282\n高置信精确率: 85.0%\n命中: 8 / 预测: 12 / 实际涨停: 45\n\n**子智能体排名**\n1. 技术分析 (区分力 26.2)\n2. 量价分析 (区分力 23.2)\n3. 资金流向 (区分力 18.6)\n4. 市场情绪 (区分力 15.5)\n\n**建议**: 增加午后轮次扫描, 创业板权重下调"
      },
      {
        "tag": "action",
        "actions": [
          {
            "tag": "button",
            "text": { "tag": "plain_text", "content": "查看完整复盘" },
            "type": "primary",
            "url": "https://internal-dashboard/zt-reviews/20260518"
          }
        ]
      }
    ]
  }
}
```

## Pitfalls

- Do not send more than 5 notifications per 10-minute window to avoid Feishu rate limits.
- Do not include the raw JSON signal table in the notification body; use the human-readable summary instead.
- The webhook URL and secret are sensitive; never log them. Log only the notification ID and response status.
- If the Feishu webhook is not configured (env var missing), log a warning and continue the pipeline without failing. The signal table and review report are still written to local files.
- For high-confidence signals (≥ 80%), send immediately even if it exceeds the 5-per-window soft limit; these are urgent and should not be delayed.
- Feishu card markdown does not support all standard markdown features; test formatting before deploying. In particular, Feishu cards do not support HTML tags.