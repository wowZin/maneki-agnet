#!/usr/bin/env python3
"""短线博弈面评分 — 打板专用

因子:
  1. 封板质量 25% — 封板时间、封单强度
  2. 连板动量 25% — 连板数、涨停基因
  3. 开盘博弈 15% — 竞价表现、开盘形态
  4. 板块助攻 15% — 板块热度、身位地位
  5. 攻击独特性 20% — 涨停基因、高开率、弱转强（V2.4新增）

用法:
  from score_shortterm import score_shortterm
  score, reason = score_shortterm("603319.SH")
"""

import sys
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_DIR))

import tushare as ts
import requests
from dotenv import load_dotenv
import os

load_dotenv(PROJECT_DIR / ".env")
ts.set_token(os.getenv("TUSHARE_TOKEN", ""))
pro = ts.pro_api()

# ── 全市场涨停列表缓存 ──
_LIMIT_UP_CACHE = None
_LIMIT_UP_CACHE_DATE = None

def _get_today_limit_ups():
    """全市场涨停列表(缓存，每轮只调一次，防10000次/天限流)"""
    global _LIMIT_UP_CACHE, _LIMIT_UP_CACHE_DATE
    today = datetime.now().strftime("%Y%m%d")
    if _LIMIT_UP_CACHE is not None and _LIMIT_UP_CACHE_DATE == today:
        return _LIMIT_UP_CACHE
    try:
        _LIMIT_UP_CACHE = pro.limit_list_d(trade_date=today, limit_type="U")
        _LIMIT_UP_CACHE_DATE = today
    except Exception:
        _LIMIT_UP_CACHE = None
    return _LIMIT_UP_CACHE


# ── 工具函数 ──────────────────────────────────────────────

def _today_str() -> str:
    return datetime.now().strftime("%Y%m%d")


def _is_today(date_str: str) -> bool:
    return date_str == _today_str()


def _safe_float(val, default=0.0):
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


# ── 1. 封板质量 (35%) ────────────────────────────────────

def score_seal_quality(code: str) -> tuple[float, str]:
    """封板质量评分

    数据来源: tushare limit_list_d
    """
    reasons = []
    score = 0

    try:
        df = pro.limit_list_d(ts_code=code, trade_date=_today_str())
        if df is not None and not df.empty:
            row = df.iloc[0]

            # 封板时间
            open_time = str(row.get("open_time", "")).strip()
            if open_time:
                try:
                    hour = int(open_time[:2])
                    minute = int(open_time[2:4])
                    hm = hour * 100 + minute
                    if hm <= 930:
                        score += 35
                        reasons.append("开盘秒板+35")
                    elif hm <= 1000:
                        score += 30
                        reasons.append("30分内封板+30")
                    elif hm <= 1030:
                        score += 20
                        reasons.append("早盘封板+20")
                    elif hm <= 1130:
                        score += 15
                        reasons.append("午前封板+15")
                    else:
                        score += 5
                        reasons.append("午后封板+5")
                except:
                    pass

            # 封单金额（首次封单额）
            first_amount = _safe_float(row.get("first_limit_amount", 0))
            if first_amount > 5e8:  # 5亿+
                score += 30
                reasons.append(f"封单强劲({first_amount/1e8:.1f}亿)+30")
            elif first_amount > 1e8:
                score += 20
                reasons.append(f"封单充足({first_amount/1e8:.1f}亿)+20")
            elif first_amount > 3e7:
                score += 10
                reasons.append(f"封单一般({first_amount/1e7:.0f}千万)+10")

            # 是否炸板（终封单额 < 首封单额 * 0.3）
            last_amount = _safe_float(row.get("last_limit_amount", 0))
            if first_amount > 0 and last_amount > 0:
                seal_ratio = last_amount / first_amount
                if seal_ratio < 0.3:
                    score -= 15
                    reasons.append("大幅撤单-15")
                elif seal_ratio < 0.6:
                    score -= 5
                    reasons.append("部分撤单-5")

        else:
            # 今天没涨停，用最近一次涨停数据
            df2 = pro.limit_list_d(ts_code=code, limit_type="U")
            if df2 is not None and not df2.empty:
                recent = df2.iloc[0]
                days_ago = (_safe_float(recent.get("trade_date", 0)))
                reasons.append("今日未涨停(参考历史)")
                score += 10  # 给个基础分
            else:
                reasons.append("无涨停记录")
                score += 0

    except Exception as e:
        reasons.append(f"封板数据异常:{str(e)[:20]}")

    total = min(score, 100)
    reason_str = "; ".join(reasons) if reasons else "无数据"
    return max(total, 0), f"[封板] {reason_str}"


# ── 2. 连板动量 (25%) ────────────────────────────────────

def score_momentum(code: str) -> tuple[float, str]:
    """连板动量评分"""
    reasons = []
    score = 0

    try:
        # 获取历史涨停记录（最近30天）
        thirty_days_ago = datetime.now() - __import__("datetime").timedelta(days=30)
        start = thirty_days_ago.strftime("%Y%m%d")

        df = pro.limit_list_d(ts_code=code, start_date=start, end_date=_today_str(), limit_type="U")
        if df is not None and not df.empty:
            # 连板数
            limit_times = _safe_float(df.iloc[0].get("limit_times", 0))
            if limit_times >= 4:
                score += 50
                reasons.append(f"{int(limit_times)}连板+50")
            elif limit_times == 3:
                score += 40
                reasons.append("3连板+40")
            elif limit_times == 2:
                score += 30
                reasons.append("2连板+30")
            elif limit_times >= 1:
                score += 15
                reasons.append("首板+15")

            # 涨停基因：近30天涨停次数
            recent_count = len(df)
            if recent_count >= 5:
                score += 20
                reasons.append(f"近月{recent_count}次涨停+20")
            elif recent_count >= 3:
                score += 10
                reasons.append(f"近月{recent_count}次涨停+10")

            # 断板反包（上次涨停后断板，今天又涨停）
            if len(df) >= 2:
                dates = df["trade_date"].tolist()
                # 检查是否有间隔
                gaps = []
                for i in range(1, len(dates)):
                    from datetime import datetime as _dt
                    d1 = _dt.strptime(str(dates[i-1]), "%Y%m%d")
                    d2 = _dt.strptime(str(dates[i]), "%Y%m%d")
                    gap = (d1 - d2).days
                    if gap > 1 and gap < 10:
                        gaps.append(gap)
                if gaps:
                    score += 15
                    reasons.append("断板反包+15")
        else:
            reasons.append("近期无涨停")

        # 涨幅活跃度（近5日日均涨幅）
        df_daily = pro.daily(ts_code=code, start_date=start, end_date=_today_str())
        if df_daily is not None and not df_daily.empty:
            recent_days = df_daily.head(min(5, len(df_daily)))
            avg_pct = recent_days["pct_chg"].mean()
            if avg_pct > 3:
                score += 15
                reasons.append(f"近5日活跃(均涨{avg_pct:.1f}%)+15")
            elif avg_pct > 1:
                score += 5
                reasons.append(f"近5日温和(均涨{avg_pct:.1f}%)+5")

    except Exception as e:
        reasons.append(f"连板数据异常:{str(e)[:20]}")

    total = min(score, 100)
    reason_str = "; ".join(reasons) if reasons else "无数据"
    return max(total, 0), f"[连板] {reason_str}"


# ── 3. 开盘博弈 (20%) ────────────────────────────────────

def score_open_battle(code: str) -> tuple[float, str]:
    """开盘博弈评分

    使用 tushare 日线数据 + 实时竞价估算
    """
    reasons = []
    score = 0

    try:
        # 获取今日日线（含开盘数据）
        df = pro.daily(ts_code=code, start_date=_today_str(), end_date=_today_str())
        if df is not None and not df.empty:
            row = df.iloc[0]
            open_p = _safe_float(row.get("open", 0))
            pre_close = _safe_float(row.get("pre_close", 0))
            high = _safe_float(row.get("high", 0))

            if pre_close > 0:
                # 开盘涨幅
                open_pct = (open_p - pre_close) / pre_close * 100

                if open_pct >= 9.5:
                    score += 40
                    reasons.append(f"一字/秒板开盘+40")
                elif open_pct >= 5:
                    score += 30
                    reasons.append(f"高开{open_pct:.1f}%+30")
                elif open_pct >= 3:
                    score += 20
                    reasons.append(f"小幅高开{open_pct:.1f}%+20")
                elif open_pct >= 0:
                    score += 5
                    reasons.append(f"平开{open_pct:.1f}%+5")
                else:
                    score -= 10
                    reasons.append(f"低开{open_pct:.1f}%-10")

                # 分歧转一致（开盘跌但最终涨停）
                if open_pct < 3 and high >= pre_close * 1.098:
                    score += 20
                    reasons.append("分歧转一致+20")

            # 换手率
            vol = _safe_float(row.get("vol", 0))
            amount = _safe_float(row.get("amount", 0))
            if amount > 0:
                # 用成交额估算活跃度
                if amount > 1e9:  # 10亿+
                    score += 20
                    reasons.append("放量活跃+20")
                elif amount > 3e8:
                    score += 10
                    reasons.append("成交活跃+10")
        else:
            # 无今日数据（盘前或休市）
            reasons.append("暂无今日数据")

    except Exception as e:
        reasons.append(f"开盘数据异常:{str(e)[:20]}")

    total = min(score, 100)
    reason_str = "; ".join(reasons) if reasons else "无数据"
    return max(total, 0), f"[开盘] {reason_str}"


# ── 4. 板块助攻 (20%) ────────────────────────────────────

def score_sector(code: str) -> tuple[float, str]:
    """板块助攻评分
    
    数据源：concept_detail（概念映射）+ limit_cpt_list（概念涨停统计）
    """
    reasons = []
    score = 0
    today = _today_str()

    try:
        # 获取个股所属概念
        concept_names = []
        try:
            import requests
            payload = {
                "api_name": "concept_detail",
                "token": os.getenv("TUSHARE_TOKEN", ""),
                "params": {"ts_code": code},
                "fields": "id,concept_name"
            }
            resp = requests.post("https://api.tushare.pro", json=payload, timeout=10)
            items = resp.json().get("data", {}).get("items", [])
            concept_names = [c[1] for c in items if len(c) > 1] if items else []
        except:
            pass

        if not concept_names:
            reasons.append("无概念数据")
            score += 10
            return max(min(score, 100), 0), f"[板块] {'; '.join(reasons)}"

        # 获取今日概念涨停统计
        cpt_fields = ["ts_code", "name", "trade_date", "up_nums"]
        cpt_data = []
        try:
            import requests
            payload2 = {
                "api_name": "limit_cpt_list",
                "token": os.getenv("TUSHARE_TOKEN", ""),
                "params": {"trade_date": today},
                "fields": ",".join(cpt_fields)
            }
            resp2 = requests.post("https://api.tushare.pro", json=payload2, timeout=10)
            items2 = resp2.json().get("data", {}).get("items", [])
            fields2 = resp2.json().get("data", {}).get("fields", [])
            if items2 and fields2:
                for item in items2:
                    d = dict(zip(fields2, item))
                    d["up_nums"] = int(d.get("up_nums", 0)) if d.get("up_nums") else 0
                    cpt_data.append(d)
        except:
            pass

        if not cpt_data:
            reasons.append("无概念涨停统计")
            score += 10
            return max(min(score, 100), 0), f"[板块] {'; '.join(reasons)}"

        # 构建概念→涨停家数映射（含模糊匹配）
        concept_ul_cnt = {c["name"]: c["up_nums"] for c in cpt_data if c.get("name") and c.get("up_nums", 0) > 0}

        def _match_ul_cnt(cname):
            if cname in concept_ul_cnt:
                return concept_ul_cnt[cname]
            for k, v in concept_ul_cnt.items():
                if cname in k or k in cname:
                    return v
            return 0

        # 找出所属概念中最大涨停数
        max_ul = max([_match_ul_cnt(n) for n in concept_names], default=0)

        if max_ul >= 10:
            score += 40
            reasons.append(f"板块爆发(概念涨停{max_ul}只)+40")
        elif max_ul >= 5:
            score += 30
            reasons.append(f"板块强联动({max_ul}只涨停)+30")
        elif max_ul >= 3:
            score += 20
            reasons.append(f"板块有热点({max_ul}只涨停)+20")
        elif max_ul >= 1:
            score += 10
            reasons.append(f"板块跟风({max_ul}只涨停)+10")
        else:
            reasons.append(f"所属概念无涨停+0")

        # 龙头地位：该股票是否在概念涨停股中
        is_leader = False
        try:
            payload3 = {
                "api_name": "limit_list_d",
                "token": os.getenv("TUSHARE_TOKEN", ""),
                "params": {"trade_date": today},
                "fields": "ts_code,name"
            }
            resp3 = requests.post("https://api.tushare.pro", json=payload3, timeout=10)
            limit_items = resp3.json().get("data", {}).get("items", [])
            limit_codes = {x[0] for x in limit_items if x} if limit_items else set()
            if code in limit_codes:
                # 试试看是否属于同一概念的其他涨停股
                is_leader = True  # 自己就是涨停股，加分
        except:
            pass

        if is_leader and max_ul > 0:
            score += 15
            reasons.append("自身涨停+15")

    except Exception as e:
        reasons.append(f"板块数据异常:{str(e)[:30]}")

    total = min(score, 100)
    reason_str = "; ".join(reasons) if reasons else "无数据"
    return max(total, 0), f"[板块] {reason_str}"


# ── 5. 攻击独特性 (20%, V2.4新增) ──────────────────────────

def score_aggression(code: str) -> tuple[float, str]:
    """攻击独特性评分

    因子：
    1. 近20日有过涨停 且 次日高开率>50% → +8分
    2. 近10日最大单日涨幅>7%             → +7分
    3. 昨日是涨停股+今日弱转强            → +5分
    """
    reasons = []
    score = 0
    today = _today_str()

    try:
        from datetime import timedelta
        # 获取近20个交易日数据
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=30)
        start = start_dt.strftime("%Y%m%d")

        df_daily = pro.daily(ts_code=code, start_date=start, end_date=today)
        if df_daily is not None and not df_daily.empty:
            recent = df_daily.head(20)

            # ① 近20日有过涨停 + 次日高开率>50%
            limit_up_dates = recent[recent["pct_chg"] >= 9.5]["trade_date"].tolist()
            if limit_up_dates:
                high_open_count = 0
                for i, lu_date in enumerate(limit_up_dates):
                    # 找该涨停日的下一个交易日
                    lu_idx = recent[recent["trade_date"] == lu_date].index
                    if not lu_idx.empty:
                        pos = recent.index.get_loc(lu_idx[0])
                        if isinstance(pos, slice):
                            pos = pos.start
                        if pos + 1 < len(recent):
                            next_day = recent.iloc[pos + 1]
                            next_open = _safe_float(next_day.get("open", 0))
                            next_pre = _safe_float(next_day.get("pre_close", 0))
                            if next_pre > 0 and (next_open / next_pre - 1) * 100 > 0:
                                high_open_count += 1
                if limit_up_dates and high_open_count / len(limit_up_dates) > 0.5:
                    score += 8
                    reasons.append(f"涨停高开率{high_open_count}/{len(limit_up_dates)}+8")

            # ② 近10日最大单日涨幅>7%
            max_pct = recent.head(10)["pct_chg"].max()
            if max_pct > 7:
                score += 7
                reasons.append(f"近10日最大涨幅{max_pct:.1f}%+7")

            # ③ 昨日涨停+今日弱转强
            if len(df_daily) >= 2:
                yesterday_row = df_daily.iloc[1] if len(df_daily) >= 2 else None
                today_row = df_daily.iloc[0] if len(df_daily) >= 1 else None
                if yesterday_row is not None and today_row is not None:
                    y_pct = _safe_float(yesterday_row.get("pct_chg", 0))
                    t_open = _safe_float(today_row.get("open", 0))
                    t_pre = _safe_float(today_row.get("pre_close", 0))
                    t_pct = _safe_float(today_row.get("pct_chg", 0))
                    if y_pct >= 9.5 and t_pre > 0:
                        open_pct = (t_open / t_pre - 1) * 100
                        if -2 <= open_pct <= 2 and t_pct > 4:
                            score += 5
                            reasons.append(f"弱转强(昨涨停今开{open_pct:.1f}%当前{t_pct:.1f}%)+5")

        else:
            reasons.append("无近20日数据")

    except Exception as e:
        reasons.append(f"攻击因子异常:{str(e)[:20]}")

    total = min(score, 20)
    reason_str = "; ".join(reasons) if reasons else "无数据"
    return max(total, 0), f"[攻击] {reason_str}"


# ── 综合评分 ──────────────────────────────────────────────

def score_shortterm(code: str) -> tuple[float, str]:
    """短线博弈面综合评分（0-100）V2.4：新增攻击独特性因子"""

    weights = {
        "seal": 0.25,
        "momentum": 0.25,
        "open": 0.15,
        "sector": 0.15,
        "aggression": 0.20,
    }

    seal_s, seal_r = score_seal_quality(code)
    momentum_s, momentum_r = score_momentum(code)
    open_s, open_r = score_open_battle(code)
    sector_s, sector_r = score_sector(code)
    agg_s, agg_r = score_aggression(code)

    total = (
        seal_s * weights["seal"]
        + momentum_s * weights["momentum"]
        + open_s * weights["open"]
        + sector_s * weights["sector"]
        + agg_s * weights["aggression"]
    )

    reason = f"{seal_r} | {momentum_r} | {open_r} | {sector_r} | {agg_r}"
    return round(total, 1), reason


# ── 自测 ──────────────────────────────────────────────────

if __name__ == "__main__":
    codes = sys.argv[1:] if len(sys.argv) > 1 else ["603319.SH"]
    for code in codes:
        s, r = score_shortterm(code)
        print(f"\n{code}: {s}分")
        for part in r.split(" | "):
            print(f"  {part}")
