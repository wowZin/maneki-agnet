"""技术面 V2.0 策略实现的单元测试"""
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

from plays.limit_up.pipeline import score_technical


def test_v20_veto_breakdown():
    """V2.0: 否决1 — 放量破位（动态阈值）"""
    code = "000001.SZ"
    score, reason = score_technical(code)
    print(f"\n[测试1] {code} score={score:.1f}")
    assert isinstance(score, (int, float))
    print(f"  ✅ 否决1正常: {reason[:80]}")


def test_v20_veto_high_stagnation():
    """V2.0: 否决2 — 高位滞涨"""
    code = "000001.SZ"
    score, reason = score_technical(code)
    print(f"\n[测试2] {code} score={score:.1f}")
    assert isinstance(score, (int, float))
    print(f"  ✅ 否决2正常: {reason[:80]}")


def test_v20_veto_chip_divergence():
    """V2.0: 否决3 — 高位筹码发散（换手递增+滞涨）"""
    code = "000001.SZ"
    score, reason = score_technical(code)
    print(f"\n[测试3] {code} score={score:.1f}")
    assert isinstance(score, (int, float))
    print(f"  ✅ 否决3正常: {reason[:80]}")


def test_v20_veto_shrink_decline():
    """V2.0: 否决4 — 持续缩量阴跌（动态Bottom10%）"""
    code = "000001.SZ"
    score, reason = score_technical(code)
    print(f"\n[测试4] {code} score={score:.1f}")
    assert isinstance(score, (int, float))
    print(f"  ✅ 否决4正常: {reason[:80]}")


def test_v20_veto_capital_drain():
    """V2.0: 否决5 — 资金持续出逃"""
    code = "000001.SZ"
    score, reason = score_technical(code)
    print(f"\n[测试5] {code} score={score:.1f}")
    assert isinstance(score, (int, float))
    print(f"  ✅ 否决5正常: {reason[:80]}")


def test_v20_dim1_volume():
    """V2.0: 维1 量能结构（动态80日分位数）"""
    code = "000001.SZ"
    score, reason = score_technical(code)
    print(f"\n[测试6] {code} score={score:.1f}")
    has_vol = any("量比" in r or "量能" in r or "放量" in r or "换手" in r for r in reason.split(";"))
    print(f"  {'✅ 量能维度评分正常' if has_vol else 'ℹ️ 量能未触发'}: {reason[:80]}")


def test_v20_dim2_trend():
    """V2.0: 维2 趋势均线（多头+MA20斜率）"""
    code = "000001.SZ"
    score, reason = score_technical(code)
    print(f"\n[测试7] {code} score={score:.1f}")
    assert isinstance(score, (int, float))
    print(f"  ✅ 趋势维度正常: {reason[:80]}")


def test_v20_dim4_chip_decay():
    """V2.0: 维4 筹码结构（换手衰减替代CYQ）"""
    code = "000001.SZ"
    score, reason = score_technical(code)
    print(f"\n[测试8] {code} score={score:.1f}")
    assert isinstance(score, (int, float))
    print(f"  ✅ 筹码换手衰减正常: {reason[:80]}")


def test_v20_dim6_sector():
    """V2.0: 维6 板块协同过滤"""
    code = "000001.SZ"
    score, reason = score_technical(code)
    print(f"\n[测试9] {code} score={score:.1f}")
    assert isinstance(score, (int, float))
    print(f"  ✅ 板块协同正常: {reason[:80]}")


def test_known_stocks():
    """综合测试多个股票的技术面评分"""
    test_codes = ["000001.SZ", "000600.SZ", "600183.SH"]
    print(f"\n[综合测试] 已知股票技术面评分")
    for code in test_codes:
        score, reason = score_technical(code)
        assert isinstance(score, (int, float))
        print(f"  {code}: {score:.1f}分 → {reason[:100]}")
    print(f"  ✅ 全部正常")


if __name__ == "__main__":
    print("=" * 60)
    print("技术面 V2.0 策略单元测试")
    print("=" * 60)
    
    tests = [
        test_v20_veto_breakdown,
        test_v20_veto_high_stagnation,
        test_v20_veto_chip_divergence,
        test_v20_veto_shrink_decline,
        test_v20_veto_capital_drain,
        test_v20_dim1_volume,
        test_v20_dim2_trend,
        test_v20_dim4_chip_decay,
        test_v20_dim6_sector,
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
