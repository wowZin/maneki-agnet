# 涨停预测任务模板

## 任务来源

zt-trigger 每10分钟拉取涨速排名前100股票，构建任务列表下发给 zt-team-leader。

## 任务格式

```json
{
  "task_id": "zt-20260518-0910-001",
  "timestamp": "2026-05-18T09:10:00+08:00",
  "type": "surge_scan",
  "stocks": [
    {
      "code": "600519",
      "name": "贵州茅台",
      "surge_speed": 3.21,
      "current_price": 1850.00,
      "change_pct": 5.23,
      "volume_ratio": 2.5,
      "sector": "白酒"
    }
  ],
  "meta": {
    "market_date": "2026-05-18",
    "scan_round": 1,
    "total_stocks": 100
  }
}
```

## 任务分发流程

1. zt-trigger 构建任务 -> 发给 zt-team-leader
2. zt-team-leader 拆分任务 -> 并行分给 4 个子 agent
3. 每个子 agent 对每只股票独立评分 -> 返回结果
4. zt-team-leader 聚合加权 -> 输出信号表

## 每轮超时

- 子 agent 分析超时: 5 分钟
- 整轮聚合超时: 8 分钟
- 超时未返回的子 agent 视为弃权，该维度权重归零