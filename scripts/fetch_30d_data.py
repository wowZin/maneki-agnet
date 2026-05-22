#!/usr/bin/env python3
"""拉取近30天涨停数据，批量跑五维评分，缓存到 data/history/

用法:
  python scripts/fetch_30d_data.py --week 1   # 跑最近1周（最新5个交易日）
  python scripts/fetch_30d_data.py --week 2   # 跑第2周
  python scripts/fetch_30d_data.py --all      # 按周依次跑完（2C4G友好模式）
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

import tushare as ts
from dotenv import load_dotenv
import os

load_dotenv(PROJECT_DIR / ".env")
ts.set_token(os.getenv("TUSHARE_TOKEN", ""))
pro = ts.pro_api()

HISTORY_DIR = PROJECT_DIR / "data" / "history"
HISTORY_DIR.mkdir(parents=True, exist_ok=True)

DIMS = ["fundamental", "technical", "fundflow", "sentiment", "shortterm"]
CACHE_FILE = HISTORY_DIR / "full_30d_scores.json"


def parse_args():
    parser = argparse.ArgumentParser(description="30天回测数据采集（按周分批，2C4G友好）")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--week", type=int, choices=range(1, 7),
                       help="跑第几周的数据（1=最新一周，6=最旧一周）")
    group.add_argument("--all", action="store_true",
                       help="按周依次跑完全部数据（每跑完一周休息10秒）")
    return parser.parse_args()


def week_boundaries(trading_dates: list[str], week_no: int) -> tuple | None:
    """将交易日列表按5天一组分周，返回第 week_no 周的起止索引

    交易日从最近到最旧排列，week_no 1 = 最新一周
    """
    n = len(trading_dates)
    start = (week_no - 1) * 5
    if start >= n:
        return None
    end = min(start + 5, n)
    return (start, end)


# ── 1. 拉取涨停数据 ──────────────────────────────────────

def fetch_30d_limit_ups() -> list[dict]:
    """获取近30个交易日的涨停股票列表"""
    all_ups = []
    today = datetime.now()
    trading_days = 0

    for i in range(60):
        if trading_days >= 30:
            break
        d = today - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        ds = d.strftime("%Y%m%d")
        try:
            time.sleep(0.55)  # 控制频率
            df = pro.limit_list_d(trade_date=ds, limit_type="U")
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    all_ups.append({
                        "trade_date": ds,
                        "code": row.get("ts_code", ""),
                        "name": row.get("name", ""),
                    })
                trading_days += 1
                print(f"  {ds}: {len(df)} 只涨停 (累计{trading_days}/30)")
            else:
                # 库存交易日也可能没有涨停
                trading_days += 1
                print(f"  {ds}: 0 只")
        except Exception as e:
            if "频率超限" in str(e):
                print(f"  限流，等待5秒...")
                time.sleep(5)
                continue
            print(f"  {ds}: {e}")

    print(f"\n共 {len(all_ups)} 条涨停记录, {trading_days} 个交易日")
    return all_ups


# ── 2. 去重（同一天同一只股票只跑一次） ────────────────────


def dedup(records: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for r in records:
        key = (r["trade_date"], r["code"])
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


# ── 3. 批量跑五维评分（并行） ─────────────────────────────


def score_stock(code: str) -> dict:
    """跑五维评分，返回 {dim: score} 和 {dim: reason}（2C4G：串行跑各维度，避免嵌套线程）"""
    from zt_pipeline import score_fundamental, score_technical, score_fundflow, score_sentiment
    from score_shortterm import score_shortterm

    scores, reasons = {}, {}
    funcs = {
        "fundamental": score_fundamental,
        "technical": score_technical,
        "fundflow": score_fundflow,
        "sentiment": score_sentiment,
        "shortterm": score_shortterm,
    }
    for dim, fn in funcs.items():
        try:
            s, r = fn(code)
            scores[dim] = s
            reasons[dim] = r
        except Exception as e:
            scores[dim] = 0
            reasons[dim] = f"异常: {e}"
    return {"scores": scores, "reasons": reasons}


def batch_score(records: list[dict], week_label: str = "") -> list[dict]:
    """批量评分，每次并行跑多个（2C4G：串行，一次1只）"""
    # 检查缓存
    if CACHE_FILE.exists():
        with open(CACHE_FILE) as f:
            cached = json.load(f)
        cached_keys = {(r["trade_date"], r["code"]) for r in cached}
        todo = [r for r in records if (r["trade_date"], r["code"]) not in cached_keys]
        print(f"缓存命中 {len(cached)} 条，还需跑 {len(todo)} 条")
        records = todo
    else:
        cached = []
        print("无缓存，全部需跑")

    if not records:
        print("全部已缓存，跳过评分")
        return cached

    total = len(records)
    prefix = f"[{week_label}] " if week_label else ""
    for i, r in enumerate(records):
        date, code, name = r["trade_date"], r["code"], r.get("name", "")
        try:
            result = score_stock(code)
            cached.append({
                "trade_date": date,
                "code": code,
                "name": name,
                "scores": result["scores"],
                "reasons": result["reasons"],
            })
            progress = f"{prefix}进度: {i+1}/{total} ({code} {name})"
            print(progress)
        except Exception as e:
            print(f"    {code} 评分异常: {e}")

        # 每5只保存一次
        if (i + 1) % 5 == 0 or i == total - 1:
            with open(CACHE_FILE, "w") as f:
                json.dump(cached, f, ensure_ascii=False)
            time.sleep(0.5)

    print(f"{prefix}累计评分 {len(cached)} 条")
    return cached


# ── 4. 整理 + 保存 ───────────────────────────────────────


def save_final(records: list[dict]):
    """添加 is_limit_up 标记后保存"""
    limit_ups_set = {(r["trade_date"], r["code"]) for r in records}
    for r in records:
        r["is_limit_up"] = True

    # 还需要一些未涨停的对比数据
    print("\n从流水线分析数据补充未涨停样本...")
    analysis_dir = PROJECT_DIR / "data" / "analysis"
    existing_codes = {(r["trade_date"], r["code"]) for r in records}
    supplemented = 0

    for f in sorted(analysis_dir.glob("*.json")):
        trade_date = f.stem.split("_")[0]
        with open(f) as fh:
            stocks = json.load(fh)
        for s in stocks:
            code = s.get("code", "")
            key = (trade_date, code)
            if key not in existing_codes and key not in {(r["trade_date"], r["code"]) for r in records}:
                scores_from_analysis = s.get("scores", {})
                # 如果流水线数据没有 shortterm，需要补
                if "shortterm" not in scores_from_analysis:
                    continue  # 跳过未补跑 shortterm 的
                records.append({
                    "trade_date": trade_date,
                    "code": code,
                    "name": s.get("name", ""),
                    "scores": scores_from_analysis,
                    "reasons": s.get("reasons", {}),
                    "is_limit_up": False,
                })
                supplemented += 1

    print(f"补充 {supplemented} 条非涨停样本")

    # 保存最终结果
    out_file = HISTORY_DIR / "full_30d_scores.json"
    with open(out_file, "w") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"最终数据已保存: {out_file} ({len(records)} 条)")
    return records


# ── Main ──────────────────────────────────────────────────

def main():
    args = parse_args()
    print("=" * 60)
    print(f"30天回测数据采集 — {datetime.now()}")
    print("=" * 60)

    # 1. 拉取/加载涨停数据
    if CACHE_FILE.exists():
        print(f"\n发现已有缓存: {CACHE_FILE}")
        with open(CACHE_FILE) as f:
            cached_records = json.load(f)
        limit_ups = sum(1 for r in cached_records if r.get("is_limit_up"))
        print(f"  缓存中有 {len(cached_records)} 条 (涨停 {limit_ups})")
        # 从涨停记录中提取交易日列表
        trading_dates = sorted(set(r["trade_date"] for r in cached_records if r.get("is_limit_up")), reverse=True)
        all_limit_ups = [r for r in cached_records if r.get("is_limit_up")]
        print(f"  涉及 {len(trading_dates)} 个交易日")
    else:
        print("\n[1/3] 拉取近30天涨停数据...")
        all_limit_ups = fetch_30d_limit_ups()
        all_limit_ups = dedup(all_limit_ups)
        trading_dates = sorted(set(r["trade_date"] for r in all_limit_ups), reverse=True)

    if not trading_dates:
        print("无数据可处理")
        return

    print(f"\n共 {len(trading_dates)} 个交易日，{len(all_limit_ups)} 只涨停股")

    # 2. 确定要处理的交易周
    n_weeks = (len(trading_dates) + 4) // 5  # 向上取整

    if args.week:
        weeks_to_run = [args.week]
    elif args.all:
        weeks_to_run = list(range(1, n_weeks + 1))
    else:
        # 默认跑最近一周
        weeks_to_run = [1]
        print(f"提示: 默认只跑最近1周，可用 --week N 指定周数(1-{n_weeks}) 或 --all 跑全部")

    for wn in weeks_to_run:
        bounds = week_boundaries(trading_dates, wn)
        if bounds is None:
            print(f"周 {wn} 超出范围（共 {n_weeks} 周），跳过")
            continue
        start, end = bounds
        week_dates = trading_dates[start:end]

        week_label = f"周{wn}({'/'.join(week_dates[0::max(1,len(week_dates)-1)])})"
        print(f"\n{'=' * 50}")
        print(f"[{week_label}] 处理 {len(week_dates)} 个交易日")

        week_records = [r for r in all_limit_ups if r["trade_date"] in week_dates]
        print(f"  共 {len(week_records)} 只涨停股需评分")

        records = batch_score(week_records, week_label=week_label)

        # 每周之间休息
        if wn != weeks_to_run[-1]:
            print(f"\n  --- 休息 10 秒，准备下一周 ---")
            time.sleep(10)

    # 3. 整理最终数据
    print(f"\n{'=' * 50}")
    print("[最终整理] 补充非涨停样本...")

    # 加载最终缓存
    if CACHE_FILE.exists():
        with open(CACHE_FILE) as f:
            final_records = json.load(f)
    else:
        final_records = list(all_limit_ups)

    # 添加 is_limit_up 标记
    limit_up_set = {(r["trade_date"], r["code"]) for r in all_limit_ups}
    for r in final_records:
        r["is_limit_up"] = (r["trade_date"], r["code"]) in limit_up_set

    save_final(final_records)

    print(f"\n{'=' * 60}")
    print(f"✅ 完成! {len(final_records)} 条数据就绪")
    limit_count = sum(1 for r in final_records if r.get("is_limit_up"))
    print(f"   涨停 {limit_count} 只")
    print(f"   非涨停 {len(final_records) - limit_count} 只")
    print(f"\n下一步运行: python scripts/optimize_weights.py")


if __name__ == "__main__":
    main()
