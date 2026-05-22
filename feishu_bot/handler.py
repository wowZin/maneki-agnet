"""消息处理器 — 解析飞书消息 → 调用评分 → 返回结果卡片"""

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


def _build_name_to_code() -> dict[str, str]:
    """从 tushare 获取全量股票列表，建立 名称→代码 映射"""
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
    """从消息文本中提取股票代码（支持代码和名称）

    先匹配 6 位代码，再匹配中文名称（按名称长度降序匹配）。
    """
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

    # 2. 中文名称（按长度降序匹配）
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
    """去掉 @机器人 标签"""
    return re.sub(r"<at[^>]*>.*?</at>", "", text).strip()


# ── 评分逻辑 ──────────────────────────────────────────────


def _score_one_stock(code: str) -> dict:
    """对单只股票运行五维度评分"""
    from zt_pipeline import (
        score_fundamental,
        score_technical,
        score_fundflow,
        score_sentiment,
        AGENT_WEIGHTS,
    )
    from score_shortterm import score_shortterm

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

    weights = AGENT_WEIGHTS
    total = sum(scores[d] * weights[d] for d in weights) / sum(weights.values())
    return {"code": code, "scores": scores, "reasons": reasons, "total": round(total, 1)}


# ── 实时行情获取 ──────────────────────────────────────────


def _get_realtime_quote(code: str) -> dict:
    """获取个股实时行情（涨幅%、最新价）

    通过 Eastmoney clist 分页搜索 + zdtps 代理。
    """
    try:
        import requests as _req
        import sys as _sys
        _sys.path.insert(0, str(SCRIPTS_DIR))
        from proxy_utils import get_requests_session_with_proxy

        raw = code.split(".")[0]
        raw_num = int(raw)

        # 确定市场和fs参数
        if raw.startswith("6"):
            markets = [("m:1+t:2", "SH主板"), ("m:1+t:23", "SH科创板")]
            base = 600000
        elif raw.startswith("3"):
            markets = [("m:0+t:80", "SZ创业板")]
            base = 300000
        else:
            markets = [("m:0+t:6", "SZ主板"), ("m:0+t:80", "SZ创业板")]
            base = 0

        # 获取代理session
        sess = get_requests_session_with_proxy()
        if sess is None:
            sess = _req.Session()
            sess.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                                 "Referer": "https://quote.eastmoney.com/"})
        # 确保 session 有代理配置
        if not sess.proxies:
            from proxy_utils import get_proxies_dict
            proxies = get_proxies_dict()
            if proxies:
                sess.proxies = proxies

        for fs, label in markets:
            # 先拿总页数
            try:
                resp = sess.get(
                    f"https://push2.eastmoney.com/api/qt/clist/get?"
                    f"np=1&fltt=2&invt=2&fs={fs}&fields=f12&pn=1&pz=1&po=0",
                    timeout=5
                )
                total_count = resp.json().get("data", {}).get("total", 0)
                total_pages = (total_count // 100) + 1
            except Exception:
                total_pages = 20  # fallback

            for pn in range(1, total_pages + 1):
                url = (
                    f"https://push2.eastmoney.com/api/qt/clist/get?"
                    f"np=1&fltt=2&invt=2&fs={fs}&fields=f2,f3,f12,f14&pn={pn}&pz=100&po=0"
                )
                for retry in range(2):
                    try:
                        resp = sess.get(url, timeout=8)
                        items = resp.json().get("data", {}).get("diff", [])
                        for item in items:
                            if item.get("f12") == raw:
                                return {"price": item.get("f2", 0) or 0, "change_pct": item.get("f3", 0) or 0}
                        break
                    except Exception:
                        if retry == 0:
                            from proxy_utils import get_proxy_ip
                            new_addr = get_proxy_ip(force_refresh=True)
                            if new_addr:
                                sess.proxies = {"http": f"http://{new_addr}", "https": f"http://{new_addr}"}
                            continue
                        break
        return {"price": 0, "change_pct": 0}
    except Exception as e:
        print(f"  [实时行情] {code} 获取失败: {e}")
        return {"price": 0, "change_pct": 0}


# ── 积极信号总结 ──────────────────────────────────────────


def _positive_summary(result: dict, change_pct: float) -> str:
    """根据评分和实时行情生成综合积极信号总结"""
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
    """调用 DeepSeek 模型生成综合信号总结"""
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
    """星级: >=50:5星 >=40:4星 >=35:3星"""
    if total >= 50: return "⭐ ⭐ ⭐ ⭐ ⭐"
    if total >= 40: return "⭐ ⭐ ⭐ ⭐"
    if total >= 35: return "⭐ ⭐ ⭐"
    return "不评级"


def _score_color(score: float) -> str:
    if score >= 50:
        return "green"
    elif score >= 40:
        return "blue"
    elif score >= 35:
        return "orange"
    return "red"


def _change_color(pct: float) -> str:
    if pct > 0:
        return "green"
    elif pct < 0:
        return "red"
    return "grey"


def _build_result_card(stock_name: str, result: dict, quote: dict | None = None) -> dict:
    code = result["code"]
    total = result["total"]
    scores = result["scores"]
    reasons = result["reasons"]

    change_pct = (quote or {}).get("change_pct", 0)
    price = (quote or {}).get("price", 0)

    # 标题行：综合评级 + 实时涨跌幅
    stars_str = _stars(total)
    header_lines = [f"**综合评级 {stars_str}**"]
    if change_pct is not None and change_pct != "":
        header_lines.append(f"**涨跌幅: {change_pct:+.2f}%**")
    if price is not None and price != "":
        header_lines.append(f"**现价: {price:.2f}**")
    header_content = "\n".join(header_lines)

    # 各维度详情（五维度+短线博弈）
    score_lines = []
    for dim in ["fundamental", "technical", "fundflow", "sentiment", "shortterm"]:
        s = scores.get(dim, 0)
        r = reasons.get(dim, "")
        short_reason = r.split(";")[0] if r else "无数据"
        score_lines.append(f"**{_dim_label(dim)} {s:.0f}分**　{short_reason}")

    elements = [
        {"tag": "div", "text": {"tag": "lark_md", "content": header_content}},
        {"tag": "hr"},
        {"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(score_lines)}},
    ]

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"📊 {stock_name} ({code})"},
            "template": _score_color(total),
        },
        "elements": elements,
    }


def _build_error_card(code: str, error: str) -> dict:
    return {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": f"⚠️ {code} 分析失败"}, "template": "red"},
        "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": f"错误: {error}"}}],
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
    return code


# ── 主入口 ────────────────────────────────────────────────


async def handle_message_event(event: dict):
    """处理飞书 im.message.receive_v1 事件"""
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

    codes = parse_stock_codes(text)
    if not codes:
        await FEISHU_CLIENT.reply_text(
            message_id,
            "📌 请带上股票代码或名称，例如：\n@机器人 000001.SZ\n@机器人 平安银行\n@机器人 贵州茅台 和 宁德时代"
        )
        return

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
                await FEISHU_CLIENT.send_card(chat_id, card)

                # 发送 AI 总结（纯文本）
                summary = _generate_ai_summary(result, quote)
                if summary:
                    await FEISHU_CLIENT.send_text(
                        chat_id,
                        f"💡 {stock_name}({code}) 总结: {summary}"
                    )
            except Exception as e:
                card = _build_error_card(code, str(e))
                await FEISHU_CLIENT.send_card(chat_id, card)
