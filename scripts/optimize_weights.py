#!/usr/bin/env python3
"""权重优化器 — 暴力搜索最优权重组合

流程:
  1. 读取 data/analysis/ 里已有的评分数据
  2. 从 tushare 拉取对应日期实际涨停数据
  3. 枚举 1000+ 种权重组合 → 找命中率最高的

用法:
  python scripts/optimize_weights.py [--days 30]

输出:
  data/weights_optimized.json
"""

import json
import random
import sys
from collections import defaultdict
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

DATA_DIR = PROJECT_DIR / "data"
ANALYSIS_DIR = DATA_DIR / "analysis"


# ── 1. 读取历史评分数据 ─────────────────────────────────

def load_all_analysis() -> list[dict]:
    """读取所有分析文件，每条记录附带 trade_date"""
    records = []
    for f in sorted(ANALYSIS_DIR.glob("*.json")):
        # 从文件名解析日期：20260519_1017.json → 20260519
        trade_date = f.stem.split("_")[0]
        with open(f) as fh:
            stocks = json.load(fh)
        for s in stocks:
            records.append({
                "trade_date": trade_date,
                "code": s["code"],
                "name": s["name"],
                "scores": s["scores"],
                "total": s["total"],
            })
    return records


# ── 2. 标记实际是否涨停 ──────────────────────────────────

def fetch_limit_ups(dates: list[str]) -> set[tuple[str, str]]:
    """从 tushare 拉取涨停数据，返回 {(date, code)} 集合"""
    limit_ups = set()

    for date in dates:
        try:
            # tushare limit_list_d: 每日涨停板股票
            df = pro.limit_list_d(trade_date=date, limit_type="U")
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    code = row.get("ts_code", "")
                    limit_ups.add((date, code))
            print(f"  {date}: {len(limit_ups) - sum(1 for d,c in limit_ups if d != date)} 只涨停")
        except Exception as e:
            print(f"  {date}: 拉取失败 {e}")

    return limit_ups


def mark_hit_rates(
    records: list[dict], limit_ups: set[tuple[str, str]]
) -> list[dict]:
    """标记每只股票是否实际涨停"""
    for r in records:
        r["is_limit_up"] = (r["trade_date"], r["code"]) in limit_ups
    return records


# ── 3. 权重搜索 ──────────────────────────────────────────

DIMS = ["fundamental", "technical", "fundflow", "sentiment", "shortterm"]


def score_with_weights(record: dict, weights: dict[str, float]) -> float:
    """用指定权重计算综合分"""
    scores = record["scores"]
    total_w = sum(weights.get(d, 1) for d in DIMS)
    total_s = sum(scores.get(d, 0) * weights.get(d, 1) for d in DIMS)
    return total_s / total_w if total_w > 0 else 0


def evaluate_weights(
    records: list[dict],
    weights: dict[str, float],
    threshold: float = 50,
) -> dict:
    """评估一组权重的表现"""
    pushed = 0
    hit = 0

    for r in records:
        s = score_with_weights(r, weights)
        if s >= threshold:
            pushed += 1
            if r["is_limit_up"]:
                hit += 1

    return {
        "weights": weights.copy(),
        "pushed": pushed,
        "hit": hit,
        "hit_rate": round(hit / pushed * 100, 1) if pushed > 0 else 0,
        "total_stocks": len(records),
    }


def generate_weight_combos(n: int = 3000) -> list[dict[str, float]]:
    """生成随机权重组合（基本面降权，资金/情绪倾向）"""
    combos = []
    for _ in range(n):
        # 各维度权重在 0.2~2.0 之间随机
        w = {
            "fundamental": round(random.uniform(0.2, 1.2), 2),
            "technical": round(random.uniform(0.5, 1.8), 2),
            "fundflow": round(random.uniform(0.8, 2.0), 2),
            "sentiment": round(random.uniform(0.8, 2.0), 2),
        }
        combos.append(w)
    return combos


def search_best_weights(
    records: list[dict],
    n_combos: int = 3000,
    threshold: float = 50,
) -> list[dict]:
    """暴力搜索最优权重组合"""
    print(f"\n搜索 {n_combos} 种权重组合...")

    combos = generate_weight_combos(n_combos)

    # 添加几个基准组合
    baselines = [
        {"fundamental": 1.0, "technical": 1.0, "fundflow": 1.0, "sentiment": 1.0},
        {"fundamental": 0.6, "technical": 1.0, "fundflow": 1.4, "sentiment": 1.2},
        {"fundamental": 0.4, "technical": 1.0, "fundflow": 1.6, "sentiment": 1.4},
        {"fundamental": 0.2, "technical": 0.8, "fundflow": 1.8, "sentiment": 1.6},
    ]
    combos = baselines + combos

    results = []
    for w in combos:
        result = evaluate_weights(records, w, threshold)
        results.append(result)

    # 按命中率排序
    results.sort(key=lambda x: (-x["hit_rate"], -x["hit"], -x["pushed"]))

    return results


# ── 4. 输出 ──────────────────────────────────────────────

def print_report(results: list[dict], records: list[dict]):
    """打印优化报告"""
    print("\n" + "=" * 60)
    print("权重优化报告")
    print("=" * 60)

    # 基准（原始权重）
    baseline = results[-1]  # 最后一个基准 = 原始四维均衡
    for r in results:
        if all(v == 1.0 for v in r["weights"].values()):
            baseline = r
            break

    print(f"\n基准 (四维均衡 1:1:1:1):")
    print(f"  推送 {baseline['pushed']} 只 → 涨停 {baseline['hit']} 只 → 命中率 {baseline['hit_rate']}%")

    print(f"\n🏆 最优权重:")
    for i, r in enumerate(results[:5]):
        if r["pushed"] == 0:
            continue
        w = r["weights"]
        print(f"\n  第{i+1}名:")
        print(f"    基本面 {w['fundamental']:.1f}  技术面 {w['technical']:.1f}  资金面 {w['fundflow']:.1f}  情绪面 {w['sentiment']:.1f}")
        print(f"    推送 {r['pushed']} 只 → 涨停 {r['hit']} 只 → 命中率 {r['hit_rate']}%")
        if baseline["pushed"] > 0:
            delta = r["hit_rate"] - baseline["hit_rate"]
            sign = "+" if delta >= 0 else ""
            print(f"    相较基准: {sign}{delta:.1f}%")

    print("\n" + "=" * 60)

    # 假阴性分析：涨停但没被推送的股票，看各维度的平均分
    limit_stocks = [r for r in records if r["is_limit_up"]]
    unpushed_limit = [r for r in limit_stocks if r["total"] < 50]
    if unpushed_limit:
        print(f"\n📋 假阴性分析（涨停却没被推送的 {len(unpushed_limit)} 只）:")
        avg = defaultdict(list)
        for r in unpushed_limit:
            for d in DIMS:
                avg[d].append(r["scores"].get(d, 0))
        for d in DIMS:
            vals = avg[d]
            if vals:
                print(f"  {d}: 平均 {sum(vals)/len(vals):.1f} 分")

    pushed_stocks = [r for r in records if r["total"] >= 50]
    limit_pushed = [r for r in pushed_stocks if r["is_limit_up"]]
    if limit_pushed and pushed_stocks:
        print(f"\n📋 鉴别力分析:")
        for d in DIMS:
            hit_avg = sum(r["scores"].get(d, 0) for r in limit_pushed) / len(limit_pushed) if limit_pushed else 0
            miss_avg = sum(r["scores"].get(d, 0) for r in pushed_stocks if not r["is_limit_up"]) / max(len([r for r in pushed_stocks if not r["is_limit_up"]]), 1)
            miss_count = len([r for r in pushed_stocks if not r["is_limit_up"]])
            print(f"  {d}: 命中均分 {hit_avg:.1f} vs 未命中均分 {miss_avg:.1f} (鉴别力 {hit_avg - miss_avg:+.1f}) [{len(limit_pushed)}命中/{miss_count}未命中]")


def save_results(results: list[dict], records: list[dict]):
    """保存优化结果"""
    output_dir = DATA_DIR / "weights"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 最优权重推荐
    best = results[0]
    output = {
        "optimized_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_range": f"{records[0]['trade_date']} ~ {records[-1]['trade_date']}",
        "total_stocks": len(records),
        "total_limit_ups": sum(1 for r in records if r["is_limit_up"]),
        "baseline": {
            "weights": {"fundamental": 1.0, "technical": 1.0, "fundflow": 1.0, "sentiment": 1.0},
            "pushed": next((r["pushed"] for r in results if all(v == 1.0 for v in r["weights"].values())), 0),
            "hit_rate": next((r["hit_rate"] for r in results if all(v == 1.0 for v in r["weights"].values())), 0),
        },
        "recommended": {
            "weights": best["weights"],
            "pushed": best["pushed"],
            "hit": best["hit"],
            "hit_rate": best["hit_rate"],
            "improvement": f"+{best['hit_rate'] - next((r['hit_rate'] for r in results if all(v == 1.0 for v in r['weights'].values())), 0):.1f}%",
        },
        "top_10": [
            {
                "rank": i + 1,
                "weights": r["weights"],
                "pushed": r["pushed"],
                "hit": r["hit"],
                "hit_rate": r["hit_rate"],
            }
            for i, r in enumerate(results[:10])
        ],
    }

    out_file = output_dir / "weights_optimized.json"
    with open(out_file, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {out_file}")


# ── Main ──────────────────────────────────────────────────

def main(days: int = 30):
    print("=" * 60)
    print(f"权重优化器启动 — {datetime.now()}")
    print("=" * 60)

    # 1. 加载历史评分
    print("\n[1/4] 读取历史评分数据...")
    records = load_all_analysis()
    print(f"  共 {len(records)} 条记录")

    if not records:
        print("  ❌ 没有历史评分数据，退出")
        return

    # 2. 获取实际涨停数据
    print("\n[2/4] 拉取历史涨停数据...")
    dates = sorted(set(r["trade_date"] for r in records))
    print(f"  涉及 {len(dates)} 个交易日: {dates}")

    limit_ups = fetch_limit_ups(dates)
    print(f"  共 {len(limit_ups)} 条涨停记录")

    # 3. 标记命中
    print("\n[3/4] 标记命中...")
    records = mark_hit_rates(records, limit_ups)
    hit_count = sum(1 for r in records if r["is_limit_up"])
    print(f"  数据中实际涨停 {hit_count} 只")

    # 4. 权重搜索
    print("\n[4/4] 搜索最优权重...")
    results = search_best_weights(records, n_combos=3000)

    # 5. 输出
    print_report(results, records)
    save_results(results, records)

    print("\n✅ 优化完成!")


if __name__ == "__main__":
    days = 30
    if len(sys.argv) > 1 and sys.argv[1].startswith("--days="):
        days = int(sys.argv[1].split("=")[1])
    main(days)
