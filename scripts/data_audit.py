#!/usr/bin/env python3
"""数据接口审计层 — 主动检测所有数据源的健康状态

调度方式（独立运行，不依赖 Bot 服务）：
  9:30  → data_audit.py            早盘前检查
  11:30 → data_audit.py            盘中巡检
  15:05 → data_audit.py --summary  收盘后汇总
  19:00 → data_audit.py --summary  日报（与优化器一起跑）

用法:
  python data_audit.py             快速健康检查
  python data_audit.py --summary   收盘汇总（含 agent 得分趋势）
  python data_audit.py --report    发送完整日报到飞书告警群

退出码: 0=正常, 1=有告警
"""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

# 兜底：设置脚本运行目录
if os.getcwd() != str(PROJECT_DIR):
    os.chdir(str(PROJECT_DIR))

# ── 文件路径 ──
AUDIT_DIR = PROJECT_DIR / "data" / "audit"
TREND_FILE = AUDIT_DIR / "trend.json"
REPORT_FILE = AUDIT_DIR / "report.json"
AUDIT_DIR.mkdir(parents=True, exist_ok=True)

# ── 加载配置 ──
from dotenv import load_dotenv
load_dotenv(PROJECT_DIR / ".env")
TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "")
ALERT_CHAT_ID = os.getenv("FEISHU_ALERT_CHAT_ID", "")

# ── 时间判定工具 ──

def _now() -> datetime:
    return datetime.now()

def _today_str() -> str:
    return _now().strftime("%Y%m%d")

def _is_weekend() -> bool:
    return _now().weekday() >= 5

def _is_trading_time() -> bool:
    """9:30 ~ 11:30、13:00 ~ 15:00"""
    if _is_weekend():
        return False
    h, m = _now().hour, _now().minute
    return (h == 9 and m >= 30) or (10 <= h < 11) or (h == 11 and m < 30) or (13 <= h < 15)

def _is_market_closed() -> bool:
    """今日已收盘（15:00 后）"""
    if _is_weekend():
        return False
    return _now().hour >= 15

def _is_after_hours() -> bool:
    """收盘后且数据应该已更新（18:00 后或次日）"""
    if _is_weekend():
        return True
    return _now().hour >= 18

def _is_trading_day() -> bool:
    """通过简单方式检查今天是否是交易日（查有无 limit_list_d 数据）"""
    # 离线判断：工作日且不是节假日
    if _is_weekend():
        return False
    return True  # 精确判断由实际 API 调用完成


# ── API 测试函数 ──

def _test_tushare(api_name: str, params: dict, fields: str = "",
                  label: str = "") -> dict:
    """通用 Tushare API 测试"""
    start = time.time()
    result = {"ok": False, "ms": 0, "items": 0, "error": None}
    try:
        from plays.limit_up.pipeline import call_tushare
        resp = call_tushare(api_name, TUSHARE_TOKEN, params, fields)
        if resp is None:
            result["error"] = "响应为 None"
        else:
            data = resp
            items = data.get("data", {}).get("items", [])
            result["ok"] = data.get("code") == 0
            result["items"] = len(items) if items else 0
            if not result["ok"]:
                result["error"] = data.get("msg", "未知错误")
        result["ms"] = int((time.time() - start) * 1000)
    except Exception as e:
        result["error"] = str(e)[:80]
        result["ms"] = int((time.time() - start) * 1000)
    return result


def _test_tushare_daily(code: str = "000001.SZ") -> dict:
    """检查 daily 接口"""
    return _test_tushare("daily", {"ts_code": code, "start_date": _today_str(), "end_date": _today_str()},
                         "trade_date,close,pct_chg", "daily")


def _test_tushare_limit_list() -> dict:
    """检查 limit_list_d 接口"""
    return _test_tushare("limit_list_d", {"trade_date": _today_str(), "limit_type": "U"},
                         "ts_code,name,pct_chg", "limit_list_d")


def _test_tushare_daily_basic(code: str = "000001.SZ") -> dict:
    """检查 daily_basic 接口"""
    return _test_tushare("daily_basic", {"ts_code": code},
                         "trade_date,close,turnover_rate,circ_mv", "daily_basic")


def _test_eastmoney() -> dict:
    """检查东方财富 clist 接口"""
    start = time.time()
    result = {"ok": False, "ms": 0, "items": 0, "error": None}
    try:
        from scripts.proxy_utils import get_proxies_dict, is_proxy_enabled
        import requests as _req
        proxies = get_proxies_dict() if is_proxy_enabled() else None
        url = (
            "https://push2.eastmoney.com/api/qt/clist/get?"
            "np=1&fltt=2&invt=2&"
            "fs=m:0+t:6+f:!2,m:0+t:80+f:!2,m:1+t:2+f:!2,m:1+t:23+f:!2&"
            "fields=f12,f3&fid=f3&pn=1&pz=100&po=1&dect=1&"
            "ut=fa5fd1943c7b386f172d6893dbfba10b"
        )
        resp = _req.get(url, proxies=proxies, timeout=10)
        data = resp.json()
        items = data.get("data", {}).get("diff", [])
        result["ok"] = len(items) > 0
        result["items"] = len(items)
        result["ms"] = int((time.time() - start) * 1000)
    except Exception as e:
        result["error"] = str(e)[:80]
        result["ms"] = int((time.time() - start) * 1000)
    return result


def _test_deepseek() -> dict:
    """检查 DeepSeek API（可选，未配则不报错）"""
    start = time.time()
    result = {"ok": True, "ms": 0, "error": None, "skipped": False}
    try:
        import yaml
        config_path = PROJECT_DIR / "config.yaml"
        if config_path.exists():
            cfg = yaml.safe_load(config_path.read_text())
            provider = cfg.get("provider", {})
            api_key = provider.get("api_key", "") or provider.get("apiKey", "")
            base_url = provider.get("base_url", "https://api.deepseek.com")
        else:
            api_key = os.getenv("DEEPSEEK_API_KEY", "")
            base_url = "https://api.deepseek.com"

        if not api_key:
            result["ok"] = True
            result["skipped"] = True
            result["error"] = "未配置（跳过）"
        else:
            import requests as _req
            resp = _req.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": "deepseek-chat", "messages": [{"role": "user", "content": "ping"}], "max_tokens": 5},
                timeout=10,
            )
            result["ok"] = resp.status_code == 200
            result["ms"] = int((time.time() - start) * 1000)
            if not result["ok"]:
                result["error"] = f"HTTP {resp.status_code}"
    except Exception as e:
        result["error"] = str(e)[:80]
        result["ms"] = int((time.time() - start) * 1000)
    return result


def _test_proxy_utils() -> dict:
    """检查 proxy_utils 模块"""
    result = {"ok": False, "error": None}
    try:
        from scripts import proxy_utils
        result["ok"] = True
    except Exception as e:
        result["error"] = str(e)[:80]
    return result


def _scan_agent_scores() -> dict:
    """分析最近一次扫描的各 agent 得分分布"""
    result = {"candidates": 0, "pushed": 0, "agents": {}}
    try:
        # 取最新 signals 文件
        signals_dir = PROJECT_DIR / "plays" / "limit_up" / "data" / "signals"
        files = sorted(signals_dir.glob(f"{_today_str()}*.json"), reverse=True)
        if not files:
            return result

        data = json.loads(files[0].read_text())
        result["candidates"] = len(data)
        pushed = [s for s in data if s.get("final", 0) >= 35]
        result["pushed"] = len(pushed)

        # 收集各 agent 得分
        agent_scores = {}
        for s in data:
            scores = s.get("scores", {})
            for ag, val in scores.items():
                if ag not in agent_scores:
                    agent_scores[ag] = []
                if isinstance(val, (int, float)):
                    agent_scores[ag].append(val)

        for ag, vals in agent_scores.items():
            if not vals:
                continue
            mean_v = sum(vals) / len(vals)
            result["agents"][ag] = {
                "mean": round(mean_v, 1),
                "min": round(min(vals), 1),
                "max": round(max(vals), 1),
                "count": len(vals),
                "all_zero": all(v == 0 for v in vals),
                "all_same": len(set(round(v, 1) for v in vals)) == 1,
            }
    except Exception as e:
        result["_error"] = str(e)[:80]
    return result


# ── 告警判定（时间感知） ──

def _judge_alerts(ts_daily: dict, ts_limit: dict, ts_basic: dict,
                  em: dict, ds: dict, proxy: dict,
                  agent_scores: dict) -> list:
    """根据测试结果和时间段，返回告警列表 [(severity, msg), ...]"""
    alerts = []
    now = _now()
    h = now.hour
    is_weekend = _is_weekend()
    is_closed = _is_market_closed()
    is_trading = _is_trading_time()

    # ── Tushare daily ──
    if not ts_daily["ok"]:
        alerts.append(("🔴", f"Tushare daily 不可达: {ts_daily['error']}"))
    elif is_closed and ts_daily["items"] == 0:
        alerts.append(("🔴", f"Tushare daily 已收盘但返回 0 条"))
    elif not is_weekend and h >= 10 and ts_daily["items"] == 0:
        alerts.append(("🟡", f"Tushare daily 返回 0 条（交易日{h}点）"))

    # ── Tushare limit_list_d ──
    if not ts_limit["ok"]:
        alerts.append(("🔴", f"Tushare limit_list_d 不可达: {ts_limit['error']}"))
    elif is_trading and ts_limit["items"] == 0:
        alerts.append(("🔴", f"盘中 limit_list_d 返回 0 只涨停"))
    elif not is_weekend and not is_trading and h >= 14 and ts_limit["items"] == 0:
        alerts.append(("🟡", f"14点后 limit_list_d 仍为 0"))

    # ── Tushare daily_basic ──
    if not ts_basic["ok"]:
        alerts.append(("🔴", f"Tushare daily_basic 不可达: {ts_basic['error']}"))
    elif _is_after_hours() and ts_basic["items"] == 0:
        alerts.append(("🟡", f"收盘后 daily_basic 仍为 0"))

    # ── Eastmoney ──
    if not em["ok"]:
        alerts.append(("🔴", f"Eastmoney 接口不可达: {em['error']}"))
    elif em["items"] < 50:
        alerts.append(("🔴", f"Eastmoney 仅返回 {em['items']} 只股票（预期 > 50）"))

    # ── DeepSeek ──
    if not ds["ok"]:
        alerts.append(("🔴", f"DeepSeek 不可达: {ds['error']}"))

    # ── proxy_utils ──
    if not proxy["ok"]:
        alerts.append(("🔴", f"proxy_utils 加载失败: {proxy['error']}"))

    # ── Agent 得分异常 ──
    for ag, info in agent_scores.get("agents", {}).items():
        if info.get("all_zero"):
            alerts.append(("🟡", f"Agent {ag}: ∀ 得分 = 0"))
        elif info.get("all_same"):
            alerts.append(("🟡", f"Agent {ag}: 均一值 {info['mean']}"))
        elif info.get("mean", 100) < 5:
            alerts.append(("🟡", f"Agent {ag}: 均值仅 {info['mean']}"))

    # pipeline 推送为 0
    if is_trading and agent_scores.get("candidates", 0) > 20 and agent_scores.get("pushed", -1) == 0:
        alerts.append(("🟡", f"pipeline 推送为 0（{agent_scores['candidates']} 只候选）"))

    return alerts


# ── 报告生成 ──

def _build_report_text(results: dict, alerts: list) -> str:
    """生成可读的审计报告文本"""
    lines = []
    now = _now()
    lines.append(f"📊 数据接口审计 | {now.strftime('%Y-%m-%d %H:%M')}")
    lines.append("")

    if alerts:
        sev = max(a[0] for a in alerts)
        lines.append(f"{sev} 发现 {len(alerts)} 项问题:")
        for sev_, msg in alerts:
            lines.append(f"  {sev_} {msg}")
        lines.append("")
    else:
        lines.append("✅ 所有接口正常")
        lines.append("")

    lines.append("— 接口状态 —")
    for name, r in results.get("tushare", {}).items():
        icon = "✅" if r["ok"] else "❌"
        ms = r.get("ms", 0)
        items = r.get("items", "?")
        err = f" ({r['error']})" if r.get("error") else ""
        lines.append(f"  {icon} {name}: {items}条 {ms}ms{err}")
    for name, r in results.get("other", {}).items():
        icon = "✅" if r["ok"] else "❌"
        items = r.get("items", "")
        ms = r.get("ms", "")
        err = f" ({r['error']})" if r.get("error") else ""
        items_str = f" {items}只" if isinstance(items, int) else ""
        ms_str = f" {ms}ms" if ms else ""
        lines.append(f"  {icon} {name}:{items_str}{ms_str}{err}")

    lines.append("")
    lines.append("— Agent 得分 —")
    agent_scores = results.get("agents", {})
    for ag, info in agent_scores.items():
        if isinstance(info, dict) and "mean" in info:
            flag = "⚠️" if info.get("all_zero") or info.get("all_same") else "  "
            lines.append(f"  {flag} {ag}: μ={info['mean']} [{info['min']}–{info['max']}] n={info['count']}")

    candidates = results.get("candidates", 0)
    pushed = results.get("pushed", 0)
    if candidates > 0:
        lines.append("")
        lines.append("— Pipeline —")
        lines.append(f"  候选 {candidates} 只 → 推送 {pushed} 只")

    return "\n".join(lines)


# ── 核心入口 ──

async def run_audit(summary_mode: bool = False, send_report: bool = False) -> list:
    """执行审计，返回告警列表。summary_mode=True 时附加 agent 得分分析"""
    results = {}
    alerts = []

    # 1. Tushare
    ts_daily = _test_tushare_daily()
    ts_limit = _test_tushare_limit_list()
    ts_basic = _test_tushare_daily_basic()
    results["tushare"] = {
        "daily": ts_daily,
        "limit_list_d": ts_limit,
        "daily_basic": ts_basic,
    }

    # 2. Eastmoney
    em = _test_eastmoney()
    results["other"] = {"eastmoney": em}

    # 3. DeepSeek
    ds = _test_deepseek()
    results["other"]["deepseek"] = ds

    # 4. proxy_utils
    proxy = _test_proxy_utils()
    results["other"]["proxy_utils"] = proxy

    # 5. Agent 得分分析（summary/report 模式）
    agent_scores = {}
    if summary_mode or send_report:
        agent_scores = _scan_agent_scores()
        results["candidates"] = agent_scores.get("candidates", 0)
        results["pushed"] = agent_scores.get("pushed", 0)
        results["agents"] = agent_scores.get("agents", {})

    # 6. 告警判定
    alerts = _judge_alerts(ts_daily, ts_limit, ts_basic, em, ds, proxy, agent_scores)

    # 7. 持久化
    record = {
        "timestamp": _now().isoformat(),
        "summary": summary_mode or send_report,
        "alerts": [{"severity": s, "msg": m} for s, m in alerts],
        "tushare": results["tushare"],
        "eastmoney": em,
        "deepseek": ds,
        "agents": results.get("agents", {}),
        "candidates": results.get("candidates", 0),
        "pushed": results.get("pushed", 0),
    }
    RECORD_FILE = AUDIT_DIR / f"audit_{_today_str()}_{_now().strftime('%H%M%S')}.json"
    RECORD_FILE.write_text(json.dumps(record, ensure_ascii=False, indent=2))

    # 8. 趋势合并
    _update_trend(record)

    # 9. 输出到终端
    report_text = _build_report_text(results, alerts)
    print(report_text)

    # 10. 发送到飞书告警群
    if send_report or alerts:
        await _send_feishu(report_text, alert_only=not send_report)

    return alerts


def _update_trend(record: dict):
    """合并当天审计记录到趋势文件"""
    today = _today_str()
    try:
        if TREND_FILE.exists():
            trend = json.loads(TREND_FILE.read_text())
        else:
            trend = {"days": []}

        # 找到或创建今日记录
        day_entry = None
        for d in trend["days"]:
            if d["date"] == today:
                day_entry = d
                break
        if not day_entry:
            day_entry = {"date": today, "audits": []}
            trend["days"].append(day_entry)

        day_entry["audits"].append({
            "time": _now().strftime("%H:%M:%S"),
            "summary": record.get("summary", False),
            "alert_count": len(record.get("alerts", [])),
        })

        # 保留最近 30 天
        trend["days"] = trend["days"][-30:]
        TREND_FILE.write_text(json.dumps(trend, ensure_ascii=False, indent=2))
    except Exception:
        pass


async def _send_feishu(text: str, alert_only: bool = False):
    """发送消息到飞书告警群"""
    if not ALERT_CHAT_ID:
        print("⚠️ 未配置 FEISHU_ALERT_CHAT_ID，跳过飞书推送")
        return
    try:
        from feishu_bot.feishu_client import FEISHU_CLIENT
        await FEISHU_CLIENT.send_text(ALERT_CHAT_ID, text)
        print(f"✅ 已推送审计报告到飞书告警群")
    except Exception as e:
        print(f"⚠️ 飞书推送失败: {e}")


# ── 命令行入口 ──

def main():
    parser = argparse.ArgumentParser(description="数据接口审计")
    parser.add_argument("--summary", action="store_true", help="收盘后汇总模式（含 agent 得分分析）")
    parser.add_argument("--report", action="store_true", help="发送完整日报到飞书")
    args = parser.parse_args()

    alerts = asyncio.run(run_audit(
        summary_mode=args.summary or args.report,
        send_report=args.report,
    ))
    sys.exit(1 if alerts else 0)


if __name__ == "__main__":
    main()
