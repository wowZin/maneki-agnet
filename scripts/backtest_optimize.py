#!/usr/bin/env python3
"""回测优化 — 给历史评分数据补上短线博弈维度，跑权重优化

流程:
  1. 读取 data/analysis/ 里已有的评分数据
  2. 批量补跑 score_shortterm（并行加速）
  3. 从 tushare 拉实际涨停数据
  4. 暴力搜索最优权重
  5. 输出对比报告

用法:
  python scripts/backtest_optimize.py
"""

import json
import sys
import random
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
HISTORY_DIR = DATA_DIR / "history"
HISTORY_DIR.mkdir(parents=True, exist_ok=True)

DIMS = ["fundamental", "technical", "fundflow", "sentiment", "shortterm"]


# ── 1. 加载历史评分 + 补跑短线博弈 ──────────────────────

def load_and_augment() -> list[dict]:
    """加载已有评分 + 补跑 shortterm"""
    cache_file = HISTORY_DIR / "augmented_scores.json"
    if cache_file.exists():
        with open(cache_file) as f:
            return json.load(f)

    records = []
    for f in sorted(ANALYSIS_DIR.glob("*.json")):
        trade_date = f.stem.split("_")[0]
        with open(f) as fh:
            stocks = json.load(fh)
        for s in stocks:
            records.append({
                "trade_date": trade_date,
                "code": s["code"],
                "name": s["name"],
                "scores": s.get("scores", {}),
                "reasons": s.get("reasons", {}),
                "total": s.get("total", 0),
            })

    # 去重（同一只股票在一天内可能出现多次）
    seen = set()
    unique = []
    for r in records:
        key = (r["trade_date"], r["code"])
        if key not in seen:
            seen.add(key)
            unique.append(r)
    records = unique
    print(f"  去重后 {len(records)} 条")

    # 补跑 shortterm（并行加速）
    need_shortterm = [r for r in records if "shortterm" not in r.get("scores", {})]
    print(f"  需补跑 shortterm: {len(need_shortterm)} 条")

    if need_shortterm:
        from score_shortterm import score_shortterm

        def run_shortterm(r):
            try:
                s, reason = score_shortterm(r["code"])
                r["scores"]["shortterm"] = s
                r["reasons"]["shortterm"] = reason
            except Exception as e:
                r["scores"]["shortterm"] = 0
                r["reasons"]["shortterm"] = f"异常: {e}"
            return r

        batch_size = 20
        for i in range(0, len(need_shortterm), batch_size):
            batch = need_shortterm[i:i+batch_size]
            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = {pool.submit(run_shortterm, r): r for r in batch}
                for future in as_completed(futures):
                    future.result()
            print(f"    进度: {min(i+batch_size, len(need_shortterm))}/{len(need_shortterm)}")

        # 保存缓存
        with open(cache_file, "w") as f:
            json.dump(records, f, ensure_ascii=False)
        print(f"  缓存已保存: {cache_file}")

    return records


# ── 2. 拉取实际涨停数据 ──────────────────────────────────


def fetch_limit_ups(dates: list[str]) -> set[tuple[str, str]]:
    limit_ups = set()
    for date in dates:
        try:
            df = pro.limit_list_d(trade_date=date, limit_type="U")
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    limit_ups.add((date, row.get("ts_code", "")))
            print(f"  {date}: {sum(1 for d,c in limit_ups if d==date)} 只涨停")
        except Exception as e:
            print(f"  {date}: 失败 {e}")
    return limit_ups


# ── 3. 权重搜索 ──────────────────────────────────────────


def score_with_weights(record: dict, weights: dict[str, float]) -> float:
    scores = record.get("scores", {})
    total_w = sum(weights.get(d, 1) for d in DIMS)
    total_s = sum(scores.get(d, 0) * weights.get(d, 1) for d in DIMS)
    return total_s / total_w if total_w > 0 else 0


def evaluate(records: list[dict], weights: dict[str, float], threshold=50) -> dict:
    pushed = 0
    hit = 0
    for r in records:
        s = score_with_weights(r, weights)
        if s >= threshold:
            pushed += 1
            if r.get("is_limit_up"):
                hit += 1
    return {
        "weights": weights.copy(),
        "pushed": pushed,
        "hit": hit,
        "hit_rate": round(hit / pushed * 100, 1) if pushed > 0 else 0,
    }


def search(records: list[dict], n=5000, threshold=50) -> list[dict]:
    print(f"\n搜索 {n} 种权重组合...")

    # 基准组合
    baselines = [
        {d: 1.0 for d in DIMS},
        {"fundamental": 1.0, "technical": 1.0, "fundflow": 1.0, "sentiment": 1.0, "shortterm": 1.6},
        {"fundamental": 0.6, "technical": 1.0, "fundflow": 1.4, "sentiment": 1.2, "shortterm": 1.8},
        {"fundamental": 0.4, "technical": 1.0, "fundflow": 1.6, "sentiment": 1.4, "shortterm": 2.0},
        {"fundamental": 0.2, "technical": 0.8, "fundflow": 1.8, "sentiment": 1.6, "shortterm": 2.0},
    ]

    # 随机组合（shortterm 倾向较高权重）
    rand_combos = []
    for _ in range(n):
        w = {d: round(random.uniform(0.2, 2.0), 2) for d in DIMS}
        w["shortterm"] = round(random.uniform(0.8, 2.5), 2)
        rand_combos.append(w)

    all_combos = baselines + rand_combos

    results = []
    for w in all_combos:
        r = evaluate(records, w, threshold)
        results.append(r)

    results.sort(key=lambda x: (-x["hit_rate"], -x["hit"], -x["pushed"]))
    return results


# ── 4. 报告 ──────────────────────────────────────────────


def print_report(results: list[dict], records: list[dict]):
    print("\n" + "=" * 65)
    print("权重优化报告（含短线博弈维度）")
    print("=" * 65)

    # 基准
    baseline = None
    for r in results:
        if all(v == 1.0 for v in r["weights"].values()):
            baseline = r
            break
    if not baseline:
        baseline = results[-1]

    total_limit = sum(1 for r in records if r.get("is_limit_up"))
    print(f"\n数据: {len(records)} 条, 实际涨停 {total_limit} 只")

    print(f"\n基准 (五维均衡 1:1:1:1:1):")
    print(f"  推送 {baseline['pushed']} 只 → 涨停 {baseline['hit']} 只 → 命中率 {baseline['hit_rate']}%")

    print(f"\n🏆 Top 5 最优权重:")
    shown = 0
    for i, r in enumerate(results):
        if r["pushed"] == 0:
            continue
        w = r["weights"]
        print(f"\n  第{i+1}名 (命中率 {r['hit_rate']}% 推{r['pushed']}只 涨停{r['hit']}只):")
        print(f"    基本面 {w.get('fundamental',1):.1f}  技术面 {w.get('technical',1):.1f}  资金面 {w.get('fundflow',1):.1f}  情绪面 {w.get('sentiment',1):.1f}  短线 {w.get('shortterm',1):.1f}")
        if baseline["pushed"] > 0:
            delta = r["hit_rate"] - baseline["hit_rate"]
            print(f"    相较基准: {'+' if delta >= 0 else ''}{delta:.1f}%")
        shown += 1
        if shown >= 5:
            break

    print("\n" + "=" * 65)

    # 鉴别力分析
    pushed_stocks = [r for r in records if r.get("total", 0) >= 50]
    limit_pushed = [r for r in pushed_stocks if r.get("is_limit_up")]
    miss_pushed = [r for r in pushed_stocks if not r.get("is_limit_up")]

    if limit_pushed:
        print(f"\n📋 五维度鉴别力分析:")
        for d in DIMS:
            hit_avg = sum(r.get("scores", {}).get(d, 0) for r in limit_pushed) / len(limit_pushed)
            miss_avg = sum(r.get("scores", {}).get(d, 0) for r in miss_pushed) / max(len(miss_pushed), 1)
            print(f"  {d}: 涨停均分 {hit_avg:.1f} vs 未涨停均分 {miss_avg:.1f} (鉴别力 {hit_avg - miss_avg:+.1f})")

    # 假阴性
    limit_unpushed = [r for r in records if r.get("is_limit_up") and r.get("total", 0) < 50]
    if limit_unpushed:
        print(f"\n📋 假阴性（涨停但被漏掉 {len(limit_unpushed)} 只）各维度平均分:")
        avg = defaultdict(list)
        for r in limit_unpushed:
            for d in DIMS:
                avg[d].append(r.get("scores", {}).get(d, 0))
        for d in DIMS:
            vals = avg[d]
            if vals:
                print(f"  {d}: {sum(vals)/len(vals):.1f}")


def save_results(results: list[dict], records: list[dict]):
    out_dir = DATA_DIR / "weights"
    out_dir.mkdir(parents=True, exist_ok=True)

    baseline = next((r for r in results if all(v == 1.0 for v in r["weights"].values())), results[-1])
    top = [r for r in results if r["pushed"] > 0][:10]

    output = {
        "optimized_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_range": f"{records[0]['trade_date']} ~ {records[-1]['trade_date']}",
        "total_records": len(records),
        "total_limit_ups": sum(1 for r in records if r.get("is_limit_up")),
        "baseline": {
            "weights": {d: 1.0 for d in DIMS},
            "pushed": baseline["pushed"],
            "hit_rate": baseline["hit_rate"],
        },
        "recommended": top[0] if top else {},
        "top_10": [{
            "rank": i+1,
            "weights": r["weights"],
            "pushed": r["pushed"],
            "hit": r["hit"],
            "hit_rate": r["hit_rate"],
        } for i, r in enumerate(top)],
    }

    out_file = out_dir / "backtest_result.json"
    with open(out_file, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {out_file}")


# ── Main ──────────────────────────────────────────────────

def main():
    print("=" * 65)
    print(f"回测优化启动 — {datetime.now()}")
    print("=" * 65)

    # 1. 加载 + 补跑
    print("\n[1/4] 加载历史评分 + 补跑短线博弈...")
    records = load_and_augment()
    print(f"  共 {len(records)} 条")

    # 2. 拉涨停
    print("\n[2/4] 拉取实际涨停数据...")
    dates = sorted(set(r["trade_date"] for r in records))
    print(f"  涉及 {len(dates)} 个交易日: {dates}")
    limit_ups = fetch_limit_ups(dates)
    print(f"  共 {len(limit_ups)} 条涨停记录")

    # 3. 标记
    print("\n[3/4] 标记命中...")
    for r in records:
        r["is_limit_up"] = (r["trade_date"], r["code"]) in limit_ups
    print(f"  数据中实际涨停 {sum(1 for r in records if r['is_limit_up'])} 只")

    # 4. 搜索
    print("\n[4/4] 搜索最优权重...")
    results = search(records, n=5000)

    # 5. 输出
    print_report(results, records)
    save_results(results, records)

    print("\n✅ 完成!")


if __name__ == "__main__":
    main()
