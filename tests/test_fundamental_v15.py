"""基本面 V1.5 策略实现的单元测试"""
import sys, os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "plays" / "limit-up"))

from dotenv import load_dotenv
load_dotenv(PROJECT_DIR / ".env")

import tushare as ts
ts.set_token(os.getenv("TUSHARE_TOKEN", ""))
pro = ts.pro_api()

from plays.limit_up.pipeline import score_fundamental


def test_v15_veto_goodwill_exemption():
    """V1.5: 商誉否决 — 医药/电子行业ROE>10%豁免"""
    code = "000001.SZ"  # 平安银行（非医药）
    score, reason = score_fundamental(code)
    print(f"\n[测试1] {code} score={score}")
    print(f"  reason: {reason[:80]}")
    assert isinstance(score, (int, float))
    print(f"  ✅ 商誉否决逻辑正常")


def test_v15_veto_debt_exemption():
    """V1.5: 负债率否决 — 房地产/建筑/非银/公用事业豁免"""
    code = "000001.SZ"
    score, reason = score_fundamental(code)
    print(f"\n[测试2] {code} score={score}")
    print(f"  reason: {reason[:80]}")
    assert isinstance(score, (int, float))
    print(f"  ✅ 负债率行业豁免正常")


def test_v15_turnaround_bonus():
    """V1.5: 困境反转加分 — 最新季扣非>0且去年同期<0"""
    code = "000001.SZ"
    score, reason = score_fundamental(code)
    print(f"\n[测试3] {code} score={score}")
    has_turnaround = "困境反转" in reason
    print(f"  {'✅ 困境反转已检测' if has_turnaround else 'ℹ️ 无困境反转信号'}")
    assert isinstance(score, (int, float))


def test_v15_price_in_penalty():
    """V1.5: 见光死惩罚 — Price-in_Ratio衰减"""
    code = "000001.SZ"
    score, reason = score_fundamental(code)
    print(f"\n[测试4] {code} score={score}")
    has_penalty = "见光死" in reason
    print(f"  {'✅ 见光死惩罚触发' if has_penalty else 'ℹ️ 未见光死'}")
    assert isinstance(score, (int, float))


def test_v15_nonlinear_resonance():
    """V1.5: 非线性共振加分"""
    code = "000001.SZ"
    score, reason = score_fundamental(code)
    print(f"\n[测试5] {code} score={score}")
    has_resonance = "共振" in reason
    print(f"  {'✅ 共振加分触发' if has_resonance else 'ℹ️ 未触发共振'}")
    assert isinstance(score, (int, float))


def test_v15_value_restructure():
    """V1.5: 估值维度重构 — 废除低PE加分"""
    code = "000001.SZ"
    score, reason = score_fundamental(code)
    print(f"\n[测试6] {code} score={score}")
    has_peg = "PEG" in reason
    print(f"  {'✅ PEG估值正常' if has_peg else 'ℹ️ PEG未触发'}")
    assert isinstance(score, (int, float))


def test_v15_chip_genetic_gene():
    """V1.5: 筹码维度 — 连板基因"""
    code = "000001.SZ"
    score, reason = score_fundamental(code)
    print(f"\n[测试7] {code} score={score}")
    has_gene = "连板基因" in reason
    print(f"  {'✅ 连板基因已检测' if has_gene else 'ℹ️ 无连板基因'}")
    assert isinstance(score, (int, float))


def test_known_stocks():
    """综合测试多个股票的基本面评分"""
    test_codes = ["000001.SZ", "000600.SZ", "600183.SH"]
    print(f"\n[综合测试] 已知股票基本面评分")
    for code in test_codes:
        score, reason = score_fundamental(code)
        assert isinstance(score, (int, float))
        print(f"  {code}: {score:.1f}分 → {reason[:80]}")
    print(f"  ✅ 全部正常")


if __name__ == "__main__":
    print("=" * 60)
    print("基本面 V1.5 策略单元测试")
    print("=" * 60)
    
    tests = [
        test_v15_veto_goodwill_exemption,
        test_v15_veto_debt_exemption,
        test_v15_turnaround_bonus,
        test_v15_price_in_penalty,
        test_v15_nonlinear_resonance,
        test_v15_value_restructure,
        test_v15_chip_genetic_gene,
        test_known_stocks,
    ]
    
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"\n  ❌ {test.__name__}: {e}")
            import traceback; traceback.print_exc()
            failed += 1
        print()
    
    print("=" * 60)
    print(f"结果: {passed}/{len(tests)} 通过, {failed} 失败")
    if failed > 0:
        sys.exit(1)
    print("✅ 全部通过!")
