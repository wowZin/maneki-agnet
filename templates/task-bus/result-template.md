# 涨停预测结果模板

## 子 Agent 分析结果格式

每个子 agent 对每只股票返回:

```json
{
  "task_id": "zt-20260518-0910-001",
  "agent": "zt-technician",
  "weight": 25,
  "stocks": [
    {
      "code": "600519",
      "name": "贵州茅台",
      "score": 78,
      "confidence": "medium",
      "signals": ["均线多头排列", "MACD金叉", "突破前期高点"],
      "warnings": ["量能稍显不足"],
      "detail": {
        "pattern_score": 82,
        "ma_score": 75,
        "indicator_score": 80
      }
    }
  ],
  "timestamp": "2026-05-18T09:15:00+08:00"
}
```

## 聚合信号表格式

zt-team-leader 输出:

```json
{
  "task_id": "zt-20260518-0910-001",
  "signal_table": [
    {
      "code": "600519",
      "name": "贵州茅台",
      "confidence": 68.5,
      "tier": "中等",
      "technician": 78,
      "volume": 65,
      "fund_flow": 72,
      "sentiment": 55,
      "combined_signals": ["均线多头排列", "主力净流入", "板块共振"],
      "warnings": ["量能稍显不足"]
    }
  ],
  "threshold": 50,
  "total_analyzed": 100,
  "total_signaled": 12,
  "timestamp": "2026-05-18T09:18:00+08:00"
}
```

## 置信度等级

| 等级 | 置信度范围 | 含义 |
|---|---|---|
| 高 | 80-100 | 多维度共振，涨停概率极高 |
| 中高 | 65-79 | 主维度看多，辅助维度部分确认 |
| 中等 | 50-64 | 某些维度看多但整体偏弱 |
| 低 | 0-49 | 涨停概率不足，不纳入信号表 |

## 复盘数据存档格式

每日收盘后存储:

```json
{
  "date": "2026-05-18",
  "predictions": [
    {
      "round": 1,
      "time": "09:10",
      "code": "600519",
      "name": "贵州茅台",
      "predicted_confidence": 68.5,
      "actual_result": "涨停",
      "hit": true
    }
  ],
  "summary": {
    "total_predictions": 120,
    "hits": 45,
    "misses": 75,
    "overall_accuracy": 37.5
  }
}
```