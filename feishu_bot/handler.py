"""消息处理器 — 解析飞书消息 → 调用评分 → 返回结果卡片

功能:
- 股票分析：@机器人 平安银行 或 @机器人 000001.SZ
- 追问指标：@机器人 基本面为什么这么低？(基于上次分析)
- 非股票问题：友好拒绝并说明能力范围
"""

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

# ── 确保能导入 scripts/ 下的模块 ────────────────────────
PROJECT_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from feishu_bot.feishu_client import FEISHU_CLIENT, BOT_CHAT_ID

# ── 股票代码/名称解析 ─────────────────────────────────────

STOCK_CODE_PATTERN = re.compile(r"\b(\d{6})(?:\.(SH|SZ))?\b")
SKIP_WORDS = {"机器人", "扫描", "大盘", "股票", "分析", "查看", "查询", "今天", "明天"}

# 维度关键词（用于追问检测）
DIM_KEYWORDS = {
    "fundamental": {"基本面", "基本", "业绩", "利润", "营收", "ROE", "财务"},
    "technical": {"技术面", "技术", "K线", "均线", "MACD", "KDJ", "形态", "走势"},
    "fundflow": {"资金面", "资金", "主力", "流入", "流出", "龙虎榜", "盘口"},
    "sentiment": {"情绪面", "情绪", "热度", "连板", "竞价", "封板", "炸板"},
    "shortterm": {"短线博弈", "短线", "博弈", "封单", "攻击"},
}
ALL_DIM_KEYWORDS = set().union(*DIM_KEYWORDS.values())

# 闲聊/非股票关键词
NON_STOCK_PATTERNS = [
    re.compile(r"你好|您好|嗨|hi|hello|在吗", re.I),
    re.compile(r"天气|温度|下雨|台风"),
    re.compile(r"你是谁|你叫什么|你是什么|介绍.*自己"),
    re.compile(r"能做什么|你会什么|有什么功能"),
    re.compile(r"谢谢|感谢|再见|拜拜|晚安"),
]

# ── 会话记忆（最近一次分析的股票，按 chat_id 存储）──
_last_analysis: dict[str, dict] = {}


def _save_last_analysis(chat_id: str, data: dict):
    _last_analysis[chat_id] = {"data": data, "time": datetime.now()}


def _get_last_analysis(chat_id: str) -> dict | None:
    entry = _last_analysis.get(chat_id)
    if entry:
        # 30分钟内有效
        if (datetime.now() - entry["time"]).total_seconds() < 1800:
            return entry["data"]
    return None


# ── 股票名称→代码映射 ─────────────────────────────────────


def _build_name_to_code() -> dict[str, str]:
    try:
        import tushare as ts
        import os
        from dotenv import load_dotenv

        load_dotenv(PROJECT_DIR / ".env")
        ts.set_token(os.getenv("TUSHARE_TOKEN", ""))
        pro = ts.pro_api()
        df = pro.stock_basic(fields="ts_code,name")
        mapping = {}
        for _, row in df.iterrows():
            name = row.get("name", "").strip()
            code = row.get("ts_code", "")
            if name and code:
                mapping[name] = code
        return mapping
    except Exception as e:
        print(f"  [名称映射] 构建失败: {e}")
        return {}


_NAME_TO_CODE: dict[str, str] | None = None


def get_name_to_code() -> dict[str, str]:
    global _NAME_TO_CODE
    if _NAME_TO_CODE is None:
        _NAME_TO_CODE = _build_name_to_code()
    return _NAME_TO_CODE


def parse_stock_codes(text: str) -> list[str]:
    codes = []
    # 1. 6位数字代码
    for match in STOCK_CODE_PATTERN.finditer(text):
        raw_code, market = match.groups()
        if market:
            codes.append(f"{raw_code}.{market}")
        elif raw_code.startswith("6"):
            codes.append(f"{raw_code}.SH")
        elif raw_code.startswith(("0", "3")):
            codes.append(f"{raw_code}.SZ")

    # 2. 中文名称
    mapping = get_name_to_code()
    sorted_names = sorted(mapping.keys(), key=len, reverse=True)
    for name in sorted_names:
        if name in SKIP_WORDS:
            continue
        code = mapping[name]
        if code in codes:
            continue
        if name in text:
            codes.append(code)

    return codes


def clean_mention(text: str) -> str:
    return re.sub(r"<at[^>]*>.*?</at>", "", text).strip()


# ── 非股票问题检测 ─────────────────────────────────────────


def is_non_stock_message(text: str) -> bool:
    """检测是否为明显的非股票问题"""
    for pattern in NON_STOCK_PATTERNS:
        if pattern.search(text):
            return True
    return False


# ── 追问检测 ──────────────────────────────────────────────


def detect_follow_up(text: str, last_data: dict | None) -> tuple[str | None, str | None]:
    """检测是否为追问某个指标详情
    返回: (维度名/rating, 提示文本) 或 (None, None)
    """
    if not last_data:
        return None, None

    # 评级追问：评分/星级/评级
    rating_keywords = ["评分", "星级", "评级", "星"]
    for kw in rating_keywords:
        if kw in text:
            return "rating", None

    # 检查文本中是否包含维度关键词
    matched_dims = []
    for dim, keywords in DIM_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                matched_dims.append(dim)
                break

    if matched_dims:
        return matched_dims[0], None

    # 通用追问
    detail_patterns = ["为什么", "解释", "详细", "说说", "怎么回事", "具体"]
    for p in detail_patterns:
        if p in text:
            return "all", None

    return None, None


def get_dim_explanation(dim: str, score: float, reason: str) -> str:
    """生成维度指标的详细解读"""
    explanations = {
        "fundamental": {
            "name": "基本面",
            "high": "基本面优秀，公司盈利能力和成长性良好",
            "mid": "基本面中等，建议进一步查看具体财务指标",
            "low": "基本面偏弱，盈利能力或成长性存在压力",
        },
        "technical": {
            "name": "技术面",
            "high": "技术形态良好，均线多头排列，走势健康",
            "mid": "技术面中性，存在一定支撑但尚未形成明确趋势",
            "low": "技术面偏弱，短期均线承压或形态不佳",
        },
        "fundflow": {
            "name": "资金面",
            "high": "主力资金积极关注，大单净流入明显",
            "mid": "资金面中性偏多，存在一定资金关注",
            "low": "资金面偏弱，主力参与度不高或存在流出压力",
        },
        "sentiment": {
            "name": "情绪面",
            "high": "市场情绪活跃，连板基因和封板质量良好",
            "mid": "情绪面中性，市场关注度一般",
            "low": "情绪面偏弱，缺乏短线资金合力",
        },
        "shortterm": {
            "name": "短线博弈",
            "high": "短线攻击性强，封板质量和竞价表现突出",
            "mid": "短线博弈特征中等，存在一定攻击性",
            "low": "短线博弈信号不明显，封板力度偏弱",
        },
    }

    info = explanations.get(dim, {"name": dim, "high": "表现良好", "mid": "表现一般", "low": "表现偏弱"})
    if score >= 60:
        level_desc = info["high"]
    elif score >= 40:
        level_desc = info["mid"]
    else:
        level_desc = info["low"]

    return f"**{info['name']} ({score:.0f}分) — {level_desc}**\n评分依据: {reason or '暂无详细数据'}"


def get_rating_explanation(result: dict) -> str:
    """解释综合评级的含义和构成"""
    total = result["total"]
    scores = result["scores"]
    reasons = result["reasons"]

    # 星级
    stars = _stars(total)
    if total >= 55: level = "优秀 ⭐⭐⭐⭐⭐"
    elif total >= 45: level = "良好 ⭐⭐⭐⭐"
    elif total >= 35: level = "中等 ⭐⭐⭐"
    else: level = "偏弱"

    # 找出得分最高的维度和最低的维度
    weighted = [(dim, scores.get(dim, 0), reasons.get(dim, "")) for dim in ["fundamental", "technical", "fundflow", "sentiment", "shortterm"]]
    weighted.sort(key=lambda x: x[1], reverse=True)
    best = weighted[0]
    worst = weighted[-1]
    dim_cn = {"fundamental":"基本面","technical":"技术面","fundflow":"资金面","sentiment":"情绪面","shortterm":"短线博弈"}

    # 计算各维度的贡献方向
    highs = [f"{dim_cn[d]}={s:.0f}分" for d, s, _ in weighted if s >= 40]
    lows = [f"{dim_cn[d]}={s:.0f}分" for d, s, _ in weighted if s < 20]

    lines = [
        f"**{stars} 综合评级 {total:.1f}分 — {level}**\n",
        f"**评分构成分析：**"
    ]

    if highs:
        lines.append(f"✅ 加分项（≥40分）：{'、'.join(highs)}")
    if lows:
        lines.append(f"⚠️ 减分项（<20分）：{'、'.join(lows)}")

    lines.append(f"\n**最强维度：{dim_cn[best[0]]}** ({best[1]:.0f}分)")
    lines.append(f"依据：{best[2].split(';')[0] if best[2] else '无数据'}")

    if worst[1] < 20:
        lines.append(f"\n**最弱维度：{dim_cn[worst[0]]}** ({worst[1]:.0f}分)")
        lines.append(f"依据：{worst[2].split(';')[0] if worst[2] else '无数据'}")

    # 建议
    if total >= 55:
        lines.append("\n💡 各维度信号积极，综合评级优秀，可重点关注。")
    elif total >= 45:
        lines.append("\n💡 整体偏积极，可结合自身风险偏好进一步判断。")
    elif total >= 35:
        lines.append(f"\n💡 评级中等，主要受{dim_cn[worst[0]]}拖累，建议关注该维度改善情况。")
    else:
        lines.append(f"\n💡 评级偏弱，多个维度信号不强，建议保持观望。")

    return "\n".join(lines)


# ── 评分逻辑 ──────────────────────────────────────────────


def _score_one_stock(code: str) -> dict:
    from plays.limit_up.pipeline import (
        score_fundamental,
        score_technical,
        score_fundflow,
        score_sentiment,
        AGENT_WEIGHTS,
    )
    from plays.limit_up.agents.shortterm_agent import score_shortterm

    scores: dict[str, float] = {}
    reasons: dict[str, str] = {}
    funcs = {
        "fundamental": score_fundamental,
        "technical": score_technical,
        "fundflow": score_fundflow,
        "sentiment": score_sentiment,
        "shortterm": score_shortterm,
    }
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fn, code): dim for dim, fn in funcs.items()}
        for future in as_completed(futures):
            dim = futures[future]
            try:
                s, r = future.result(timeout=30)
                scores[dim] = s
                reasons[dim] = r
            except Exception as e:
                scores[dim] = 0.0
                reasons[dim] = f"评分异常: {e}"

    # V2.6: 加权Top3择优
    dim_names = ["fundamental", "technical", "fundflow", "sentiment", "shortterm"]
    weights = AGENT_WEIGHTS
    contribs = [(scores.get(d, 0) or 0, weights.get(d, 1.0)) for d in dim_names]
    contribs.sort(key=lambda x: x[0] * x[1], reverse=True)
    top3 = contribs[:3]
    total_s = sum(s * w for s, w in top3)
    total_w = sum(w for _, w in top3)
    total = total_s / total_w if total_w > 0 else 0

    return {"code": code, "scores": scores, "reasons": reasons, "total": round(total, 1)}


# ── 市场状态判定 ──────────────────────────────────────────


def _market_state() -> str:
    """返回当前市场状态: 'trading' / 'closed' / 'weekend'"""
    now = datetime.now()
    if now.weekday() >= 5:
        return "weekend"
    h, m = now.hour, now.minute
    if (h == 9 and m >= 30) or (10 <= h < 11) or (h == 11 and m < 30) or (13 <= h < 15):
        return "trading"
    return "closed"


# ── 实时行情获取 ──────────────────────────────────────────


def _fetch_eastmoney(code: str) -> dict:
    """从东方财富获取实时行情，返回 {price, change_pct} 或空dict"""
    raw = code.split(".")[0]
    try:
        import requests as _req
        import sys as _sys
        _sys.path.insert(0, str(SCRIPTS_DIR))
        from proxy_utils import get_proxies_dict
        from dotenv import load_dotenv
        import os

        load_dotenv(PROJECT_DIR / ".env")
        proxies = get_proxies_dict() if os.getenv("PROXY_ENABLED", "").lower() == "true" else None

        market = "0" if raw.startswith(("00", "30", "8", "4")) else "1"
        url = (f"https://push2.eastmoney.com/api/qt/stock/get?"
               f"secid={market}.{raw}&fields=f43,f44,f45,f46,f47,f48,f49,"
               f"f50,f51,f52,f53,f54,f55,f57,f58,f168,f170,f171,f292")
        resp = _req.get(url, proxies=proxies, timeout=5)
        d = resp.json().get("data", {})
        price = d.get("f43", 0) or 0
        pct = d.get("f170", 0) or 0
        if price:
            return {"price": float(price), "change_pct": float(pct)}
    except Exception as e:
        print(f"  [Eastmoney] {code} 失败: {e}")
    return {}


def _fetch_tushare_daily(code: str) -> dict:
    """从Tushare获取最近可用日线，自动回退到上一个有数据的交易日，返回 {price, change_pct} 或空dict"""
    try:
        import os as _os
        import tushare as _ts
        from datetime import timedelta
        from dotenv import load_dotenv
        load_dotenv(PROJECT_DIR / ".env")
        _ts.set_token(_os.getenv("TUSHARE_TOKEN", ""))
        pro = _ts.pro_api()

        # 找到最近有全天数据的交易日（Tushare daily T+1更新，今天数据可能还没出）
        for i in range(10):
            check = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
            df = pro.daily(ts_code=code, start_date=check, end_date=check,
                          fields="trade_date,close,pct_chg")
            if df is not None and len(df) > 0:
                row = df.iloc[0]
                return {"price": float(row["close"]), "change_pct": float(row["pct_chg"])}
    except Exception as e:
        print(f"  [Tushare daily] {code} 失败: {e}")
    return {}


def _get_realtime_quote(code: str) -> dict:
    """获取行情：盘中走东财实时，盘后走Tushare日线（自动回退最近交易日）"""
    state = _market_state()
    if state == "trading":
        result = _fetch_eastmoney(code)
        if result:
            return result
        # 东财失败时降级到Tushare（盘中Tushare只有T-1数据）
        result = _fetch_tushare_daily(code)
        if result:
            return result
        return {"price": 0, "change_pct": 0}

    # 盘后/周末：Tushare日线（自动回退到最近有数据的交易日）
    result = _fetch_tushare_daily(code)
    if result:
        return result
    return {"price": 0, "change_pct": 0}

# ── 积极信号总结 ──────────────────────────────────────────


def _positive_summary(result: dict, change_pct: float) -> str:
    scores = result["scores"]
    total = result["total"]
    points = []

    f = scores.get("fundamental", 0)
    t = scores.get("technical", 0)
    m = scores.get("fundflow", 0)
    s = scores.get("sentiment", 0)

    if f >= 75:
        points.append(f"基本面强劲({f:.0f}分)")
    elif f >= 55:
        points.append(f"基本面偏积极({f:.0f}分)")

    if t >= 60:
        points.append(f"技术形态向好({t:.0f}分)")
    elif t >= 40:
        points.append(f"技术面有支撑({t:.0f}分)")

    if m >= 60:
        points.append(f"主力资金关注({m:.0f}分)")
    elif m >= 40:
        points.append(f"资金面中性偏多({m:.0f}分)")

    if s >= 60:
        points.append(f"情绪面活跃({s:.0f}分)")
    elif s >= 40:
        points.append(f"情绪面存共识({s:.0f}分)")

    if change_pct > 5:
        points.append(f"盘中涨幅{change_pct:.1f}%表现强势")
    elif change_pct > 2:
        points.append(f"盘中涨{change_pct:.1f}%走势稳健")
    elif change_pct < -3:
        points.append(f"⚠️ 盘中跌{change_pct:.1f}%需注意风险")

    if not points:
        if total >= 40:
            return "各维度无明显突出信号，综合评级中等偏上"
        return "各维度信号偏弱，建议观望"

    return "；".join(points)


# ── AI 总结 ──────────────────────────────────────────────


def _generate_ai_summary(result: dict, quote: dict | None = None) -> str:
    scores = result["scores"]
    reasons = result["reasons"]
    total = result["total"]
    change_pct = (quote or {}).get("change_pct", 0)
    price = (quote or {}).get("price", 0)

    prompt = f"""你是一个A股股票分析师。请根据以下评分数据，用一段简洁的话总结这只股票的多空信号（不超过100字）。

股票评分数据：
- 综合评级: {_stars(total)}
- 实时涨幅: {change_pct:+.2f}%
- 最新价: {price:.2f}

各维度评分与理由：
- 基本面 {scores.get('fundamental',0)}分: {reasons.get('fundamental','无')}
- 技术面 {scores.get('technical',0)}分: {reasons.get('technical','无')}
- 资金面 {scores.get('fundflow',0)}分: {reasons.get('fundflow','无')}
- 情绪面 {scores.get('sentiment',0)}分: {reasons.get('sentiment','无')}
- 短线博弈 {scores.get('shortterm',0)}分: {reasons.get('shortterm','无')}

要求：
1. 指出最突出的积极或消极信号
2. 给出简短的操作参考建议
3. 语气客观，不超过100字"""

    try:
        import requests as _requests
        import yaml as _yaml

        with open("/root/.hermes/config.yaml") as _f:
            _cfg = _yaml.safe_load(_f)
        _mc = _cfg.get("model", {})
        _api_key = _mc.get("api_key", "")

        resp = _requests.post(
            f"{_mc.get('base_url', 'https://api.deepseek.com')}/chat/completions",
            headers={"Authorization": f"Bearer {_api_key}", "Content-Type": "application/json"},
            json={
                "model": _mc.get("default", "deepseek-v4-flash"),
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 200,
                "temperature": 0.7,
            },
            timeout=15,
        )
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"  [AI总结] 生成失败: {e}")
        return ""


# ── 结果卡片构建 ──────────────────────────────────────────


def _dim_label(dim: str) -> str:
    labels = {"fundamental": "基本面", "technical": "技术面", "fundflow": "资金面", "sentiment": "情绪面", "shortterm": "短线博弈"}
    return labels.get(dim, dim)


def _stars(total: float) -> str:
    """星级: >=55:5星 >=45:4星 >=35:3星"""
    if total >= 55: return "⭐ ⭐ ⭐ ⭐ ⭐"
    if total >= 45: return "⭐ ⭐ ⭐ ⭐"
    if total >= 35: return "⭐ ⭐ ⭐"
    return "- 不评级"


def _score_color(score: float) -> str:
    if score >= 50: return "green"
    elif score >= 40: return "blue"
    elif score >= 35: return "orange"
    return "red"


def _change_color(pct: float) -> str:
    if pct > 0: return "green"
    elif pct < 0: return "red"
    return "grey"


def _build_result_card(stock_name: str, result: dict, quote: dict | None = None) -> dict:
    code = result["code"]
    total = result["total"]
    scores = result["scores"]
    reasons = result["reasons"]

    change_pct = (quote or {}).get("change_pct", 0)
    price = (quote or {}).get("price", 0)

    stars_str = _stars(total)
    header_lines = [f"**综合评级 {stars_str}**"]
    if change_pct is not None and change_pct != "":
        header_lines.append(f"**涨跌幅: {change_pct:+.2f}%**")
    if price is not None and price != "":
        header_lines.append(f"**现价: {price:.2f}**")
    header_content = "\n".join(header_lines)

    score_lines = []
    for dim in ["fundamental", "technical", "fundflow", "sentiment", "shortterm"]:
        s = scores.get(dim, 0)
        r = reasons.get(dim, "")
        short_reason = r.split(";")[0] if r else "无数据"
        score_lines.append(f"**{_dim_label(dim)} {s:.0f}分**　{short_reason}")

    tip_line = "\n💡 可追问：\"为什么是4星？\"、\"基本面为什么这么低？\"、\"资金面详细说说\""

    elements = [
        {"tag": "div", "text": {"tag": "lark_md", "content": header_content}},
        {"tag": "hr"},
        {"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(score_lines)}},
        {"tag": "hr"},
        {"tag": "div", "text": {"tag": "lark_md", "content": tip_line}},
    ]

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"📊 {stock_name} ({code})"},
            "template": _score_color(total),
        },
        "elements": elements,
    }


def _build_error_card(stock_name: str, error: str) -> dict:
    friendly_msg = f"抱歉，分析 {stock_name} 时出了点问题。\n可能原因：\n1️⃣ 股票代码或名称不正确\n2️⃣ 数据源暂时不可用\n3️⃣ 该股票可能已退市或停牌\n\n请检查后重试。"
    return {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": f"⚠️ {stock_name} 分析失败"}, "template": "red"},
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": friendly_msg}},
            {"tag": "note", "element": {"tag": "plain_text", "content": f"错误详情: {error}"}},
        ],
    }


def _get_stock_name(code: str) -> str:
    try:
        import tushare as ts
        import os
        from dotenv import load_dotenv

        load_dotenv(PROJECT_DIR / ".env")
        ts.set_token(os.getenv("TUSHARE_TOKEN", ""))
        pro = ts.pro_api()
        df = pro.stock_basic(ts_code=code, fields="name")
        if not df.empty:
            return df.iloc[0]["name"]
    except Exception:
        pass
    return code.split(".")[0]


# ── 知识库查询 ─────────────────────────────────────────────

WIKI_PATH = Path(__file__).resolve().parent.parent / "wiki"

def _query_wiki(text: str) -> str | None:
    """从 wiki 知识库查找匹配内容，AI 合成回答"""
    try:
        import subprocess
        import re as _re

        # 提取搜索词：英文按单词、中文按停用词切分
        stop_words = {"的", "了", "是", "在", "有", "和", "就", "不", "也", "都", "要",
                      "吗", "啊", "呢", "吧", "哦", "嗯", "哈", "呀", "我", "你", "他",
                      "这", "那", "哪", "什么", "怎么", "如何", "哪些", "多少"}
        words = set()
        # 英文/数字词
        for w in _re.findall(r"[A-Za-z0-9_]{2,}", text):
            words.add(w.lower())
        # 中文词：按停用词切分后取2字以上片段
        cn_text = _re.sub(r"[A-Za-z0-9_\s]", "", text)
        for s in _re.split(r"[" + "".join(stop_words) + r"]", cn_text):
            s = s.strip()
            if len(s) >= 2:
                # 再切成2-3字片段
                for i in range(len(s) - 1):
                    words.add(s[i:i+2])
                if len(s) >= 4:
                    words.add(s)

        if not words:
            return None

        # 搜索 concepts/ + plays/ 下的所有玩法数据
        grep_dirs = [
            str(WIKI_PATH / "concepts"),
            str(WIKI_PATH / "queries"),
            str(WIKI_PATH / "plays"),
        ]
        matched_files = set()
        for w in words:
            for d in grep_dirs:
                result = subprocess.run(
                    ["grep", "-rli", w, d],
                    capture_output=True, text=True, timeout=5
                )
                if result.stdout.strip():
                    for p in result.stdout.strip().split("\n"):
                        p = p.strip()
                        if p:
                            matched_files.add(p)

        if not matched_files:
            return None

        # 按匹配文件数排序（匹配词最多的文件排前面）
        file_scores = {}
        for fp in matched_files:
            score = 0
            content = Path(fp).read_text(encoding="utf-8")
            for w in words:
                if w in content:
                    score += 1
            file_scores[fp] = score

        top_files = sorted(
            file_scores.keys(),
            key=lambda x: (file_scores[x], 1 if "/entities/" in x else 0, x),
            reverse=True
        )[:1]

        # 读取最佳匹配文件的完整内容
        contexts = []
        for fp in top_files:
            fpath = Path(fp)
            if fpath.exists():
                content = fpath.read_text(encoding="utf-8")
                parts = content.split("---", 2)
                body = parts[2].strip() if len(parts) >= 3 else content
                contexts.append(body)

        wiki_context = "\n\n".join(contexts)

        # 用 DeepSeek 合成回答
        import requests as _requests
        import yaml as _yaml

        with open("/root/.hermes/config.yaml") as _f:
            _cfg = _yaml.safe_load(_f)
        _mc = _cfg.get("model", {})
        _api_key = _mc.get("api_key", "")

        prompt = f"""你是一个A股分析助手，以下是用户的问题和知识库中的相关内容。

用户问题: {text}

知识库内容:
{wiki_context}

请严格按照知识库内容回答。要求：
1. [重要] 如果 entities/ 中有具体的日期数据、推送记录、命中明细，**必须优先引用**
2. 如果知识库中有具体数字（如推送X只、命中Y只、覆盖率Z%），直接给出
3. 用简洁易懂的语言，控制在 150 字以内
4. 如果没有相关信息，说"知识库中没有相关数据"""

        resp = _requests.post(
            f"{_mc.get('base_url', 'https://api.deepseek.com')}/chat/completions",
            headers={"Authorization": f"Bearer {_api_key}", "Content-Type": "application/json"},
            json={
                "model": _mc.get("default", "deepseek-v4-flash"),
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 300,
                "temperature": 0.5,
            },
            timeout=15,
        )
        data = resp.json()
        answer = data["choices"][0]["message"]["content"].strip()
        return answer

    except Exception as e:
        print(f"  [wiki] 查询失败: {e}")
        return None


# ── 主入口 ────────────────────────────────────────────────


async def handle_message_event(event: dict):
    message = event.get("message", {})
    chat_id = message.get("chat_id", BOT_CHAT_ID)
    message_id = message.get("message_id", "")
    content_raw = message.get("content", "{}")

    try:
        content = json.loads(content_raw)
    except json.JSONDecodeError:
        content = {}

    text = content.get("text", "") if isinstance(content, dict) else str(content)
    text = clean_mention(text)

    if not text.strip():
        return

    # ── 1. 检测是否为非股票问题 ──
    if is_non_stock_message(text):
        await FEISHU_CLIENT.reply_markdown(
            message_id,
            "🤖 你好！我是 **Maneki 股票分析助手**，专注于A股个股分析。\n\n"
            "**我可以帮你：**\n"
            "✅ 分析某只股票，给出基本面/技术面/资金面/情绪面/短线博弈评分\n"
            "✅ 追问指标详情，解读每个维度的具体依据\n"
            "✅ 回答股票分析知识问题（什么是AUC？怎么算的？）\n"
            "✅ 同时分析最多5只股票\n\n"
            "**使用方法：**\n"
            "@我 + 股票名称或代码，例如：\n"
            "  @机器人 平安银行\n"
            "  @机器人 000001.SZ\n"
            "  @机器人 贵州茅台 和 宁德时代\n\n"
            "分析完成后可追问：\"为什么是4星？\"、\"基本面为什么这么低？\"、\"资金面详细说说\"\n"
            "也可直接问知识：\"什么是AUC？\"、\"涨停均排是什么意思？\"\n\n"
            "**盯盘助手：**\n"
            "  @机器人 盯 000001.SZ\n"
            "  @机器人 停 000001.SZ\n"
            "  @机器人 盯盘列表"
        )
        return

    # ── 1.5 盯盘指令路由 ──
    watchdog_keywords = {
        "盯盘列表": "list",
        "清盯盘": "clear",
    }
    wd_action = None
    for kw, action in watchdog_keywords.items():
        if kw in text:
            wd_action = action
            break

    if text.startswith("盯 ") or text.startswith("watch "):
        wd_action = "add"
    elif text.startswith("停 ") or text.startswith("stop "):
        wd_action = "remove"

    if wd_action:
        try:
            from plays.watchdog.watchdog import get_engine
            engine = get_engine()
            # 确保l2api已启动
            from plays.limit_up.l2api_client import has_client, get_client as get_l2
            engine.start()

            if wd_action == "list":
                result = engine.list_all()
                await FEISHU_CLIENT.reply_text(message_id, result)
            elif wd_action == "clear":
                result = engine.clear_all()
                await FEISHU_CLIENT.reply_text(message_id, f"✅ {result}")
            elif wd_action == "add":
                codes = parse_stock_codes(text)
                if codes:
                    result = engine.add(codes)
                    await FEISHU_CLIENT.reply_text(message_id, f"✅ {result}")
                else:
                    await FEISHU_CLIENT.reply_text(message_id, "请指定股票代码，如: 盯 000001.SZ")
            elif wd_action == "remove":
                codes = parse_stock_codes(text)
                if codes:
                    result = engine.remove(codes)
                    await FEISHU_CLIENT.reply_text(message_id, f"✅ {result}")
                else:
                    await FEISHU_CLIENT.reply_text(message_id, "请指定股票代码，如: 停 000001.SZ")
        except Exception as e:
            await FEISHU_CLIENT.reply_text(message_id, f"盯盘助手启动失败: {e}")
        return

    codes = parse_stock_codes(text)
    if not codes:
        last = _get_last_analysis(chat_id)
        dim, _ = detect_follow_up(text, last)
        if dim and last:
            if dim == "rating":
                explanation = get_rating_explanation(last["result"])
                await FEISHU_CLIENT.reply_markdown(message_id, explanation)
            elif dim == "all":
                lines = []
                for d in ["fundamental", "technical", "fundflow", "sentiment", "shortterm"]:
                    score = last["result"]["scores"].get(d, 0)
                    reason = last["result"]["reasons"].get(d, "")
                    lines.append(get_dim_explanation(d, score, reason))
                await FEISHU_CLIENT.reply_markdown(message_id, "\n\n".join(lines))
            else:
                score = last["result"]["scores"].get(dim, 0)
                reason = last["result"]["reasons"].get(dim, "")
                explanation = get_dim_explanation(dim, score, reason)
                await FEISHU_CLIENT.reply_markdown(message_id, explanation)
            return

        # ── 兜底：尝试 wiki 知识库查询 ──
        wiki_answer = _query_wiki(text)
        if wiki_answer:
            await FEISHU_CLIENT.reply_markdown(message_id, wiki_answer)
            return

        # 既不是股票也不是追问也不是知识 → 友好提示
        await FEISHU_CLIENT.reply_markdown(
            message_id,
            "📌 我没有识别到股票代码或名称。\n\n"
            "请这样使用：\n"
            "  @机器人 平安银行\n"
            "  @机器人 000001.SZ\n\n"
            "或者对刚才的分析结果追问：\n"
            "  \"为什么是4星？\"\n"
            "  \"基本面为什么这么低？\"\n"
            "  \"资金面详细说说\""
        )
        return

    # ── 3. 执行分析 ──
    codes = codes[:5]
    code_list = ", ".join(codes)
    await FEISHU_CLIENT.reply_text(message_id, f"🔍 正在分析 {code_list}，请稍候...")

    with ThreadPoolExecutor(max_workers=min(len(codes), 4)) as pool:
        futures = {pool.submit(_score_one_stock, code): code for code in codes}
        for future in as_completed(futures):
            code = futures[future]
            try:
                result = future.result(timeout=60)
                stock_name = _get_stock_name(code)
                quote = _get_realtime_quote(code)
                card = _build_result_card(stock_name, result, quote)

                # 保存到会话记忆（用于后续追问）
                _save_last_analysis(chat_id, {"result": result, "stock_name": stock_name, "code": code})

                await FEISHU_CLIENT.send_card(chat_id, card)

                # AI 总结
                summary = _generate_ai_summary(result, quote)
                if summary:
                    await FEISHU_CLIENT.send_text(
                        chat_id,
                        f"💡 {stock_name}({code}) 总结: {summary}"
                    )
            except Exception as e:
                card = _build_error_card(code, str(e))
                await FEISHU_CLIENT.send_card(chat_id, card)
