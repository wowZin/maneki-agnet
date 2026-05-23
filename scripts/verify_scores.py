#!/usr/bin/env python3
"""评分验证脚本 — 拆纬度前后对比用

用法:
  # 1. 保存 baseline（改代码前跑）
  python3 scripts/verify_scores.py --save baseline.json

  # 2. 改完代码后跑对比
  python3 scripts/verify_scores.py --check baseline.json

  # 3. 只看当前结果（不保存不对比）
  python3 scripts/verify_scores.py
"""

import json
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

# ── 测试股票：覆盖各种场景 ──
TEST_STOCKS = [
    ("000518.SZ", "四环生物", "涨停股"),
    ("603893.SH", "瑞芯微", "科技股"),
    ("000001.SZ", "平安银行", "银行股"),
]

DIMS = ["fundamental", "technical", "fundflow", "sentiment", "shortterm"]


def run_all_scores():
    """跑所有股票的5维度评分"""
    # 动态导入（确保用的是当前代码）
    sys.path.insert(0, str(PROJECT_DIR / "scripts"))
    from zt_pipeline import score_fundamental, score_technical, score_fundflow, score_sentiment
    from score_shortterm import score_shortterm

    funcs = {
        "fundamental": score_fundamental,
        "technical": score_technical,
        "fundflow": score_fundflow,
        "sentiment": score_sentiment,
        "shortterm": score_shortterm,
    }

    results = {}
    for code, name, tag in TEST_STOCKS:
        stock_result = {"name": name, "tag": tag, "scores": {}, "reasons": {}, "time": ""}
        for dim in DIMS:
            fn = funcs[dim]
            try:
                t0 = time.time()
                s, r = fn(code)
                elapsed = round(time.time() - t0, 2)
                stock_result["scores"][dim] = s
                stock_result["reasons"][dim] = r
                stock_result["time"] = elapsed
            except Exception as e:
                stock_result["scores"][dim] = -1
                stock_result["reasons"][dim] = f"ERROR: {e}"
        results[code] = stock_result
    return results


def print_results(results: dict):
    """打印结果"""
    print(f"\n{'='*90}")
    print(f"评分验证 — {len(results)} 只股票 × {len(DIMS)} 维度")
    print(f"{'='*90}")

    for code, data in results.items():
        print(f"\n📊 {code} {data['name']} ({data['tag']})")
        for dim in DIMS:
            s = data["scores"].get(dim, "?")
            r = (data["reasons"].get(dim, "") or "")[:60]
            print(f"  {dim:<12} {s:>5}  {r}")
        if data.get("time"):
            print(f"  {'耗时':<12} {data['time']}s")


def compare(baseline: dict, current: dict) -> bool:
    """对比 baseline 和当前结果"""
    all_match = True
    diffs = []

    for code in baseline:
        if code not in current:
            diffs.append(f"{code}: 缺失")
            all_match = False
            continue

        b = baseline[code]
        c = current[code]

        for dim in DIMS:
            bs = b["scores"].get(dim)
            cs = c["scores"].get(dim)
            br = (b["reasons"].get(dim) or "")[:30]
            cr = (c["reasons"].get(dim) or "")[:30]

            if bs != cs:
                diffs.append(f"{code} {dim}: score {bs} → {cs}  |  {br} → {cr}")
                all_match = False
            elif br != cr:
                # reason 轻微差异可能正常（如时间戳），只记录不报错
                pass

    if all_match:
        print(f"\n✅ 完全一致！{len(baseline)} 只股票 × {len(DIMS)} 维度全部吻合")
    else:
        print(f"\n❌ 发现 {len(diffs)} 处差异:")
        for d in diffs:
            print(f"  {d}")

    return all_match


def main():
    mode = "run"
    baseline_path = None
    for arg in sys.argv[1:]:
        if arg == "--save":
            mode = "save"
        elif arg == "--check":
            mode = "check"
        elif not arg.startswith("--"):
            baseline_path = arg

    if mode == "save":
        print("📝 保存 baseline...")
        results = run_all_scores()
        path = baseline_path or "baseline.json"
        with open(path, "w") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print_results(results)
        print(f"\n✅ baseline 已保存: {path}")
        print(f"   MD5: {hash(json.dumps(results, sort_keys=True))}")

    elif mode == "check":
        path = baseline_path or "baseline.json"
        if not Path(path).exists():
            print(f"❌ baseline 文件不存在: {path}")
            return

        with open(path) as f:
            baseline = json.load(f)
        print(f"📖 读取 baseline: {path} ({len(baseline)} 只股票)")

        print("\n🔄 运行当前代码...")
        current = run_all_scores()

        print("\n📊 当前结果:")
        print_results(current)

        print("\n🔍 对比中...")
        match = compare(baseline, current)
        if not match:
            sys.exit(1)

    else:
        results = run_all_scores()
        print_results(results)


if __name__ == "__main__":
    main()
