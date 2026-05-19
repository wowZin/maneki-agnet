# 飞书通知模板

## 涨停信号通知

每轮分析完成后，置信度 > 50% 的股票通过飞书 webhook 发送。

### 信号卡片格式

```json
{
  "msg_type": "interactive",
  "card": {
    "header": {
      "title": {
        "tag": "plain_text",
        "content": "🔴 涨停信号 [09:10 第1轮]"
      },
      "template": "red"
    },
    "elements": [
      {
        "tag": "markdown",
        "content": "**今日涨停信号 (置信度 > 50%)**\n扫描 100 只 | 信号 12 只"
      },
      {
        "tag": "markdown",
        "content": "| 代码 | 名称 | 置信度 | 等级 | 技术面 | 量价 | 资金 | 情绪 |\n|---|---|---|---|---|---|---|---|\n| 600519 | 贵州茅台 | 78.5 | 中高 | 82 | 75 | 72 | 65 |\n| 000858 | 五粮液 | 72.0 | 中高 | 70 | 68 | 80 | 60 |"
      },
      {
        "tag": "markdown",
        "content": "**关键信号**: 均线多头排列、主力净流入、板块共振\n**风险提示**: 量能稍显不足"
      },
      {
        "tag": "action",
        "actions": [
          {
            "tag": "button",
            "text": {
              "tag": "plain_text",
              "content": "查看详情"
            },
            "type": "primary",
            "url": "https://your-dashboard-url/detail/zt-20260518-0910-001"
          }
        ]
      }
    ]
  }
}
```

### 等级颜色映射

| 等级 | 置信度 | Header模板色 |
|---|---|---|
| 高 | 80-100 | red |
| 中高 | 65-79 | orange |
| 中等 | 50-64 | yellow |

---

## 复盘报告通知

每日 15:30 收盘后，zt-team-leader 发送复盘报告。

### 复盘卡片格式

```json
{
  "msg_type": "interactive",
  "card": {
    "header": {
      "title": {
        "tag": "plain_text",
        "content": "📊 涨停预测复盘 [2026-05-18]"
      },
      "template": "blue"
    },
    "elements": [
      {
        "tag": "markdown",
        "content": "**今日统计**\n总预测: 120 次 | 命中: 45 | 未命中: 75 | 准确率: 37.5%"
      },
      {
        "tag": "markdown",
        "content": "**子 Agent 准确率评分**\n| Agent | 权重 | 鉴别力 | 命中率 | 调整建议 |\n|---|---|---|---|---|\n| zt-technician | 25 | 0.72 | 42% | 维持 |\n| zt-volume-analyst | 25 | 0.55 | 35% | 建议降至20 |\n| zt-fund-flow | 25 | 0.80 | 48% | 建议升至30 |\n| zt-sentiment | 25 | 0.45 | 30% | 建议降至20 |"
      },
      {
        "tag": "markdown",
        "content": "**权重调整方案** (自下次开盘生效)\n技术面: 25→25 | 量价: 25→20 | 资金: 25→30 | 情绪: 25→20"
      },
      {
        "tag": "action",
        "actions": [
          {
            "tag": "button",
            "text": {
              "tag": "plain_text",
              "content": "查看完整复盘"
            },
            "type": "primary",
            "url": "https://your-dashboard-url/review/2026-05-18"
          }
        ]
      }
    ]
  }
}
```

### 发送规则

- 信号通知: 每轮分析完成后立即发送，无信号时静默不发送
- 复盘报告: 每日 15:30 固定发送，即使当天无预测也发送零记录报告
- 通知失败: 重试 3 次，间隔 5s，全部失败后写入本地日志等待手动重发