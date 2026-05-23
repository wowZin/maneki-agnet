# 数据接口审计层设计

## 背景

当前 `health_patrol.py` 只监控**进程存活**（Bot 在不在、pipeline 卡没卡死），对**数据接口本身的质量**完全无感知。当 Tushare 返回空数据、Eastmoney 代理挂掉、某个 agent 静默输出全默认值时，系统没有任何主动告警手段。

## 目标

在开盘日和收盘后，主动检测每个数据接口的状态，在评分结果失真之前发现问题。

## 审计维度

| 维度 | 检测项 | 严重度 |
|------|--------|--------|
| 接口可达性 | Tushare/Eastmoney/DeepSeek 能否正常响应 | 🔴 致命 |
| 数据合法性 | 返回的字段是否完整、数值是否在合理范围 | 🟡 业务失真 |
| 性能退化 | 单次调用耗时是否突然飙升 | 🟡 卡顿 |
| Agent 健康 | 各 agent 的输出分布是否异常（全 0、全默认值） | 🟡 静默失效 |
| 链路完整性 | 扫描→评分→推送→wiki 编译全链路通达 | 🟡 断链 |

## 审计脚本 `scripts/data_audit.py`

### 数据源

| 数据源 | 测试方式 | 预期 |
|--------|---------|------|
| Tushare `daily` | 查一只股票最近 5 日数据，检查 `items` 长度 > 0 | 周末返回 0，交易日返回 ≥1 |
| Tushare `limit_list_d` | 查今日全市场涨停，检查 `items` 长度 | 交易日开盘 >0，盘前/周末 =0 |
| Tushare `daily_basic` | 查一只股票，检查 `circ_mv` > 0 | 交易日有数据 |
| Eastmoney clist | 批量查涨跌幅，检查返回数组长度 > 50 | 任何时间都应有效 |
| Eastmoney stock/get | 查一只股票实时行情，检查 f43 是否正数 | 任何时间都应有效 |
| DeepSeek API | 发一条简单请求，检查 status code | 在线 |
| 代理代理池 `scripts/proxy_utils` | import 是否成功 | 应该正常加载 |

### 数据记录（本地持久化）

审计结果写入 `plays/limit_up/data/audit/` 目录，JSON 格式：

```json
{
  "timestamp": "2026-05-23T19:00:00",
  "tushare": {
    "daily": {"ok": true, "ms": 320, "items": 5, "error": null},
    "limit_list_d": {"ok": true, "ms": 450, "items": 85, "error": null},
    "daily_basic": {"ok": true, "ms": 280, "items": 1, "error": null},
    "error_count_1h": 3
  },
  "eastmoney": {
    "clist": {"ok": true, "ms": 890, "items": 4872},
    "stock_get": {"ok": true, "ms": 120}
  },
  "deepseek": {"ok": true, "ms": 1500},
  "proxy_utils": {"ok": true},
  "agents": {
    "shortterm": {"ok": true, "ms": 3400, "score_mean": 42.5, "anomaly": false},
    "sentiment": {"ok": true, "ms": 5200, "score_mean": 18.3, "anomaly": false},
    "fundflow": {"ok": true, "ms": 4800, "score_mean": 35.1, "anomaly": false},
    "fundamental": {"ok": true, "ms": 6200, "score_mean": 55.2, "anomaly": false}
  },
  "pipeline": {
    "candidates": 187,
    "pushed": 12,
    "elapsed_s": 45
  }
}
```

### 告警规则（时间感知）

不同接口在盘前/盘后/周末有合理的空返回，审计规则需要感知交易时段：

| 数据源 | 盘前/盘后行为 | 审计判定 |
|--------|--------------|----------|
| Tushare `daily` (查询今日) | 返回最近交易日数据，若今日是交易日且已收盘才有今日数据 | 非交易日 `items=0` → ✅ 正常；交易日 **且** 已过 15:00 `items=0` → 🔴 告警 |
| Tushare `limit_list_d` (查询今日) | 交易日 9:30 开始有数据；盘前/周末 = 0 | 非交易日 → ✅ 正常；交易日 10:00 后 `items=0` → 🟡 关注；交易日 14:00 后 `items=0` → 🔴 告警 |
| Tushare `daily_basic` | T+1 数据，当日收盘后更新 | 交易日 **且** 已过 18:00 → 应可查到；否则 → ✅ 容忍 |
| Eastmoney clist/stock/get | 实时接口，非交易时段返回上一交易日收盘数据 | HTTP 200 且返回结构完整 → ✅ 正常；HTTP 失败 → 🔴 告警；返回为空 → 🟡 关注 |
| DeepSeek | 无时间依赖 | 任何时段失败 → 🔴 告警 |
| proxy_utils | 无时间依赖 | import 失败 → 🔴 告警 |

时间判定函数：

```python
def _is_trading_time() -> bool:
    """判断当前是否在可交易时段"""
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    h, m = now.hour, now.minute
    return (h == 9 and m >= 30) or (10 <= h < 11) or (h == 11 and m < 30) or (13 <= h < 15)

def _is_market_closed() -> bool:
    """判断今日是否已收盘"""
    now = datetime.now()
    return now.weekday() < 5 and (now.hour > 15 or (now.hour == 15 and now.minute >= 5))

def _is_today_a_trading_day() -> bool:
    """判断今天是否是交易日（通过 Tushare trade_cal）"""
    ...
```

### 告警动作表

| 条件 | 动作 |
|------|------|
| 🔴 Tushare 接口不可达 | 立即发飞书告警 |
| 🔴 交易日 14:00 后 limit_list_d 仍为 0 | 立即发飞书告警 |
| 🔴 Eastmoney 请求失败 | 立即发飞书告警 |
| 🔴 DeepSeek 超时或失败 | 立即发飞书告警 |
| 🔴 proxy_utils import 失败 | 立即发飞书告警 |
| 🟡 任意 agent 得分均值 < 5 或全部统一值 | 日报汇总 |
| 🟡 pipeline 推送数为 0（交易日且有候选股） | 日报汇总 |
| 🟡 非致命问题累计 ≥ 3 项 | 日报汇总 |

### 调度方案

| 时间 | 用途 | 说明 |
|------|------|------|
| 9:30 | 早盘健康检查 | 确保所有 API 在线后再开始扫描 |
| 11:30 | 盘中巡检 | 确认数据仍在正常流动 |
| 15:05 | 收盘审计 | 检查当日全链路数据质量 |
| 19:00 | 日报 | 与权重优化报告一起发出 |

### 输出

- **实时告警**：通过飞书 Bot 发送卡片消息到指定群
- **日报**：每日审计摘要，包含各接口成功率趋势、各 agent 得分分布统计
- **趋势文件**：`data/audit/trend.json` 保留最近 30 天审计历史

## 与现有系统的关系

```
cron 调度
  ├─ 9:35-14:55 (5min) → zt_pipeline.py (扫描)
  │                           └─ data_audit.py (9:30/11:30 独立跑)
  ├─ 15:05              → data_audit.py (收盘审计)
  ├─ 18:00              → zt_daily_review.py (复盘)
  ├─ 19:00              → optimize_ranking.py (优化)
  │                           └─ data_audit.py (日报)
  ├─ 20:00              → wiki/compile.py (编译)
  └─ 10-14 :00          → health_patrol.py (进程巡检)
```

`data_audit.py` 与 `health_patrol.py` 互补：一个管**数据质量**，一个管**进程存活**。
