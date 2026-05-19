#!/usr/bin/env python3
"""
涨停预测日报复盘脚本
流程：检查交易日 → 汇总当日信号/分析 → 对比涨停结果 → 生成报告 → 飞书推送

用法:
  python scripts/zt_daily_review.py
"""

import json
import os
import sys
import requests
from datetime import datetime, date
from pathlib import Path
from collections import defaultdict

# 项目根目录
PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))

# 从.env加载配置
def load_env():
    env_file = PROJECT_DIR / ".env"
    config = {}
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                config[key] = value
    return config

CONFIG = load_env()

TUSHARE_TOKEN = CONFIG.get("TUSHARE_TOKEN", "")
FEISHU_APP_ID = CONFIG.get("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = CONFIG.get("FEISHU_APP_SECRET", "")
FEISHU_CHAT_ID_REPORT = CONFIG.get("FEISHU_CHAT_ID_REPORT", "")

# ===== 1. 检查交易日 =====
def is_trade_day(check_date: str) -> bool:
    """用Tushare trade_cal检查是否交易日"""
    url = "http://api.tushare.pro"
    payload = {
        "api_name": "trade_cal",
        "token": TUSHARE_TOKEN,
        "params": {
            "exchange": "SSE",
            "start_date": check_date,
            "end_date": check_date
        }
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        data = resp.json()
        if data.get("code") == 0 and data.get("data"):
            fields = data["data"]["fields"]
            records = data["data"]["items"]
            if records:
                is_open_idx = fields.index("is_open")
                return str(records[0][is_open_idx]) == "1"
    except Exception as e:
        print(f"检查交易日失败: {e}")
    return False

# ===== 2. 汇总当日信号 =====
def load_today_signals(today: str) -> list:
    """读取data/signals下今天的所有信号文件"""
    signals_dir = PROJECT_DIR / "data" / "signals"
    all_signals = []
    
    for f in signals_dir.glob(f"{today}*.json"):
        try:
            with open(f) as fp:
                raw = json.load(fp)
            if isinstance(raw, dict) and "stocks" in raw:
                all_signals.extend(raw["stocks"])
            elif isinstance(raw, list):
                all_signals.extend(raw)
        except Exception as e:
            print(f"读取信号文件失败 {f}: {e}")
    
    return all_signals

# ===== 3. 汇总当日分析结果（仅取推送池：综合分>=50） =====
def load_today_analysis(today: str) -> list:
    """
    读取data/analysis下今天的所有分析文件。
    只返回综合分>=50的推送候选（即真正可能推送给用户的股票）。
    """
    analysis_dir = PROJECT_DIR / "data" / "analysis"
    stock_best = {}
    
    for f in analysis_dir.glob(f"{today}*.json"):
        try:
            with open(f) as fp:
                data = json.load(fp)
            if not isinstance(data, list):
                continue
            for item in data:
                code = item.get("code", "")
                total = item.get("total", 0) or 0
                if code not in stock_best or total > stock_best[code].get("total", 0):
                    stock_best[code] = item
        except Exception as e:
            print(f"读取分析文件失败 {f}: {e}")
    
    # 只保留综合分>=50的推送候选
    pushed = [item for item in stock_best.values() if item.get("total", 0) >= 50]
    return pushed

# ===== 4. 获取当日涨停股票 =====
def get_today_limit_up(today: str) -> list:
    """用Tushare limit_list_d获取当日涨停股票（limit_list数据不全，用_d后缀的日度接口）"""
    url = "http://api.tushare.pro"
    payload = {
        "api_name": "limit_list_d",
        "token": TUSHARE_TOKEN,
        "params": {
            "trade_date": today,
            "limit_type": "U"
        }
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        data = resp.json()
        if data.get("code") == 0 and data.get("data"):
            fields = data["data"]["fields"]
            records = data["data"]["items"]
            ts_code_idx = fields.index("ts_code")
            return [r[ts_code_idx] for r in records if r[ts_code_idx]]
    except Exception as e:
        print(f"获取涨停列表失败: {e}")
    return []

# ===== 5. 计算命中 =====
def calculate_hits(predicted_signals: list, actual_limit: list) -> dict:
    """
    计算预测命中率
    predicted_signals: 当日所有信号文件中的股票（去重）
    actual_limit: 当日实际涨停列表
    """
    # 提取所有被推荐过的股票代码（去重）
    predicted_codes = set()
    for p in predicted_signals:
        code = p.get("ts_code") or p.get("code") or p.get("代码", "")
        if "." not in str(code):
            if str(code).startswith("6"):
                code = f"{code}.SH"
            else:
                code = f"{code}.SZ"
        predicted_codes.add(code)
    
    actual_codes = set(actual_limit)
    hits = predicted_codes & actual_codes
    
    return {
        "predicted_count": len(predicted_codes),
        "actual_limit_count": len(actual_codes),
        "hit_count": len(hits),
        "hit_rate": len(hits) / len(predicted_codes) * 100 if predicted_codes else 0,
        "hit_codes": list(hits),
        "miss_codes": list(predicted_codes - actual_codes)
    }

# ===== 6. 分析各维度表现 =====
def analyze_dimension_performance(analysis_results: list) -> dict:
    """统计各评分维度的表现"""
    dim_stats = defaultdict(lambda: {"total": 0, "hit_scores": [], "miss_scores": []})
    
    for r in analysis_results:
        code = r.get("ts_code", "")
        scores = r.get("scores", {})
        hit = r.get("hit", False)
        
        for dim, score in scores.items():
            dim_stats[dim]["total"] += 1
            if hit:
                dim_stats[dim]["hit_scores"].append(score)
            else:
                dim_stats[dim]["miss_scores"].append(score)
    
    # 计算平均分
    result = {}
    for dim, stats in dim_stats.items():
        hit_avg = sum(stats["hit_scores"]) / len(stats["hit_scores"]) if stats["hit_scores"] else 0
        miss_avg = sum(stats["miss_scores"]) / len(stats["miss_scores"]) if stats["miss_scores"] else 0
        result[dim] = {
            "total": stats["total"],
            "hit_avg": round(hit_avg, 1),
            "miss_avg": round(miss_avg, 1)
        }
    
    return result

# ===== 7. 置信度分布 =====
def confidence_distribution(analysis_results: list) -> dict:
    """统计置信度分布"""
    dist = {"high": 0, "medium": 0, "low": 0}
    for r in analysis_results:
        conf = r.get("confidence", 0)
        if conf >= 70:
            dist["high"] += 1
        elif conf >= 50:
            dist["medium"] += 1
        else:
            dist["low"] += 1
    return dist

# ===== 8. 飞书推送 =====
def send_feishu_report(report: dict):
    """发送飞书卡片消息"""
    # 获取token
    token_url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    token_resp = requests.post(token_url, json={
        "app_id": FEISHU_APP_ID,
        "app_secret": FEISHU_APP_SECRET
    }, timeout=10)
    token_data = token_resp.json()
    if token_data.get("code") != 0:
        print(f"获取飞书token失败: {token_data}")
        return False
    token = token_data["tenant_access_token"]
    
    # 构建卡片
    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "📊 涨停预测日报复盘"},
            "template": "blue"
        },
        "elements": [
            {
                "tag": "div",
                "fields": [
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"**日期**\n{report['date']}"}},
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"**预测信号**\n{report['predicted_count']}只"}}
                ]
            },
            {
                "tag": "div",
                "fields": [
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"**实际涨停**\n{report['actual_limit_count']}只"}},
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"**命中数量**\n{report['hit_count']}只"}}
                ]
            },
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**命中率**\n{report['hit_rate']:.1f}%"}
            },
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": "**各维度平均分(命中/未命中)**"}
            },
            {
                "tag": "div",
                "fields": [
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"基本面: {report['dim_performance'].get('fundamental', {}).get('hit_avg', 0)}/{report['dim_performance'].get('fundamental', {}).get('miss_avg', 0)}"}},
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"技术面: {report['dim_performance'].get('technical', {}).get('hit_avg', 0)}/{report['dim_performance'].get('technical', {}).get('miss_avg', 0)}"}}
                ]
            },
            {
                "tag": "div",
                "fields": [
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"资金面: {report['dim_performance'].get('fundflow', {}).get('hit_avg', 0)}/{report['dim_performance'].get('fundflow', {}).get('miss_avg', 0)}"}},
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"情绪面: {report['dim_performance'].get('sentiment', {}).get('hit_avg', 0)}/{report['dim_performance'].get('sentiment', {}).get('miss_avg', 0)}"}}
                ]
            },
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**置信度分布**: 高(≥70): {report['confidence_dist']['high']} | 中(50-70): {report['confidence_dist']['medium']} | 低(<50): {report['confidence_dist']['low']}"}
            }
        ]
    }
    
    # 发送消息
    msg_url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.post(msg_url, headers=headers, json={
        "receive_id": FEISHU_CHAT_ID_REPORT,
        "msg_type": "interactive",
        "content": json.dumps(card)
    }, timeout=10)
    
    result = resp.json()
    if result.get("code") == 0:
        print(f"飞书推送成功: {result.get('data', {}).get('message_id')}")
        return True
    else:
        print(f"飞书推送失败: {result}")
        return False

# ===== 9. 生成Markdown报告 =====
def generate_markdown_report(report: dict) -> str:
    """生成人类可读的Markdown格式复盘报告"""
    date = report['date']
    predicted = report['predicted_count']
    actual = report['actual_limit_count']
    hit = report['hit_count']
    rate = report['hit_rate']
    hit_codes = report.get('hit_codes', [])
    miss_codes = report.get('miss_codes', [])
    dim_perf = report.get('dim_performance', {})
    conf_dist = report.get('confidence_dist', {})
    
    lines = []
    lines.append(f"# 📊 涨停预测复盘报告 — {date}")
    lines.append("")
    lines.append("## 📈 核心指标")
    lines.append("")
    lines.append(f"| 指标 | 数值 |")
    lines.append(f"|------|------|")
    lines.append(f"| 今日推荐股票（去重） | **{predicted}** 只 |")
    lines.append(f"| 今日实际涨停 | **{actual}** 只 |")
    lines.append(f"| 命中涨停 | **{hit}** 只 |")
    lines.append(f"| 命中率 | **{rate:.1f}%** |")
    lines.append("")
    
    # 命中详情
    if hit_codes:
        lines.append("## ✅ 命中股票")
        lines.append("")
        for code in hit_codes:
            lines.append(f"- {code}")
        lines.append("")
    else:
        lines.append("## ✅ 命中股票")
        lines.append("")
        lines.append("_无_")
        lines.append("")
    
    # 未命中详情（最多显示30只，避免过长）
    if miss_codes:
        lines.append(f"## ❌ 未命中股票（共 {len(miss_codes)} 只，显示前30）")
        lines.append("")
        for code in miss_codes[:30]:
            lines.append(f"- {code}")
        if len(miss_codes) > 30:
            lines.append(f"- ... 等共 {len(miss_codes)} 只")
        lines.append("")
    
    # 各维度表现
    lines.append("## 📊 各维度评分表现")
    lines.append("")
    lines.append("基于今日被深度分析的股票，统计各维度在命中/未命中上的平均分：")
    lines.append("")
    lines.append("| 维度 | 分析次数 | 命中均分 | 未命中均分 | 差异 |")
    lines.append("|------|----------|----------|------------|------|")
    
    dim_names = {
        'fundamental': '基本面',
        'technical': '技术面',
        'fundflow': '资金面',
        'sentiment': '情绪面'
    }
    
    for dim_key, dim_label in dim_names.items():
        stats = dim_perf.get(dim_key, {})
        total = stats.get('total', 0)
        hit_avg = stats.get('hit_avg', 0)
        miss_avg = stats.get('miss_avg', 0)
        diff = hit_avg - miss_avg if hit_avg and miss_avg else 0
        diff_str = f"{diff:+.1f}" if diff else "—"
        lines.append(f"| {dim_label} | {total} | {hit_avg} | {miss_avg} | {diff_str} |")
    
    lines.append("")
    
    # 置信度分布
    lines.append("## 🎯 置信度分布")
    lines.append("")
    lines.append("| 等级 | 阈值 | 数量 |")
    lines.append("|------|------|------|")
    lines.append(f"| 高置信度 | ≥70% | {conf_dist.get('high', 0)} |")
    lines.append(f"| 中置信度 | 50%~70% | {conf_dist.get('medium', 0)} |")
    lines.append(f"| 低置信度 | <50% | {conf_dist.get('low', 0)} |")
    lines.append("")
    
    # 总结
    lines.append("## 📝 总结")
    lines.append("")
    if rate >= 20:
        lines.append(f"今日命中率 **{rate:.1f}%**，表现优秀。命中 {hit} 只涨停股，推荐池覆盖度良好。")
    elif rate >= 10:
        lines.append(f"今日命中率 **{rate:.1f}%**，表现尚可。命中 {hit} 只涨停股，仍有提升空间。")
    elif rate > 0:
        lines.append(f"今日命中率 **{rate:.1f}%**，表现一般。仅命中 {hit} 只涨停股，建议关注各维度评分阈值。")
    else:
        lines.append(f"今日命中率 **0%**，未命中任何涨停股。推荐池 {predicted} 只，实际涨停 {actual} 只。")
        if actual == 0:
            lines.append("注：当日实际涨停数为0，可能为市场整体低迷或数据获取异常。")
    lines.append("")
    
    lines.append("---")
    lines.append(f"*报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
    
    return "\n".join(lines)


# ===== 主流程 =====
def main():
    today = datetime.now().strftime("%Y%m%d")
    print(f"=== 涨停预测日报复盘 {today} ===")
    
    # Step 1: 检查交易日
    if not is_trade_day(today):
        print("今天不是交易日，跳过复盘")
        return
    
    # Step 2: 汇总信号
    signals = load_today_signals(today)
    print(f"今日预测信号: {len(signals)}只")
    
    # Step 3: 汇总分析结果
    analysis = load_today_analysis(today)
    print(f"今日分析结果: {len(analysis)}条")
    
    # Step 4: 获取涨停列表
    limit_ups = get_today_limit_up(today)
    print(f"今日实际涨停: {len(limit_ups)}只")
    
    # Step 5: 计算命中（以推送池为预测池，而非全部信号）
    # 推送池 = 综合分>=50的候选股票
    pushed_codes = set()
    for item in analysis:
        code = item.get("code", "")
        if code:
            pushed_codes.add(code)
    
    # 如果没有分析结果（无推送池），fallback到信号文件
    if not pushed_codes:
        for p in signals:
            code = p.get("ts_code") or p.get("code") or p.get("代码", "")
            if "." not in str(code):
                if str(code).startswith("6"):
                    code = f"{code}.SH"
                else:
                    code = f"{code}.SZ"
            pushed_codes.add(code)
    
    actual_codes = set(limit_ups)
    hits_set = pushed_codes & actual_codes
    
    hits = {
        "predicted_count": len(pushed_codes),
        "actual_limit_count": len(actual_codes),
        "hit_count": len(hits_set),
        "hit_rate": len(hits_set) / len(pushed_codes) * 100 if pushed_codes else 0,
        "hit_codes": list(hits_set),
        "miss_codes": list(pushed_codes - actual_codes)
    }
    print(f"命中情况: {hits['hit_count']}/{hits['predicted_count']} ({hits['hit_rate']:.1f}%)")
    
    # 标记分析结果中的命中（仅推送池内标记）
    hit_codes = set(hits["hit_codes"])
    for r in analysis:
        code = r.get("code", "") or r.get("ts_code", "")
        r["hit"] = code in hit_codes
    
    # Step 6: 各维度表现（仅基于推送池）
    dim_perf = analyze_dimension_performance(analysis)
    
    # Step 7: 置信度分布（仅基于推送池）
    conf_dist = confidence_distribution(analysis)
    
    # Step 8: 生成报告
    report = {
        "date": today,
        "predicted_count": hits["predicted_count"],
        "actual_limit_count": hits["actual_limit_count"],
        "hit_count": hits["hit_count"],
        "hit_rate": hits["hit_rate"],
        "hit_codes": hits["hit_codes"],
        "miss_codes": hits.get("miss_codes", []),
        "dim_performance": dim_perf,
        "confidence_dist": conf_dist
    }
    
    # 保存JSON报告（保留用于程序读取）
    report_file_json = PROJECT_DIR / "data" / "reports" / f"{today}.json"
    report_file_json.parent.mkdir(parents=True, exist_ok=True)
    with open(report_file_json, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"JSON报告已保存: {report_file_json}")
    
    # 保存Markdown报告（人类可读）
    md_content = generate_markdown_report(report)
    report_file_md = PROJECT_DIR / "data" / "reports" / f"{today}.md"
    with open(report_file_md, "w") as f:
        f.write(md_content)
    print(f"Markdown报告已保存: {report_file_md}")
    
    # Step 9: 飞书推送
    if FEISHU_APP_ID and FEISHU_APP_SECRET and FEISHU_CHAT_ID_REPORT:
        send_feishu_report(report)
    else:
        print("飞书配置缺失，跳过推送")

if __name__ == "__main__":
    main()
