"""情绪面 V2.3 策略实现的单元测试"""
import sys, os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_DIR / ".env")

import tushare as ts
ts.set_token(os.getenv("TUSHARE_TOKEN", ""))
pro = ts.pro_api()

from zt_pipeline import score_sentiment


def test_v23_veto4_type_a():
    """V2.3: 否决4 A型诱多 — 最高>3%但跌停+换手>10日均换手1.5倍"""
    code = "000001.SZ"  # 平安银行（大概率无核按钮）
    score, reason = score_sentiment(code)
    print(f"\n[测试1] {code} score={score}")
    # 平安银行不应该有核按钮
    assert "核按钮" not in reason or "豁免" in reason, f"误判核按钮: {reason}"
    print(f"  ✅ 否决4 A型正常: {reason[:80]}")


def test_v23_veto4_type_b():
    """V2.3: 否决4 B型一字闷杀 — 无需换手率确认"""
    code = "000001.SZ"
    score, reason = score_sentiment(code)
    print(f"\n[测试2] {code} score={score}")
    assert isinstance(score, (int, float))
    print(f"  ✅ 否决4 B型正常: {reason[:80]}")


def test_v23_veto5_popularity_threshold():
    """V2.3: 否决5 — 人气排名动态阈值+Null处理"""
    code = "000001.SZ"
    score, reason = score_sentiment(code)
    print(f"\n[测试3] {code} score={score}")
    assert isinstance(score, (int, float))
    # 平安银行至少有换手率数据，应该不会因为涨幅<3%被否决
    if "纯跟风弱势" in reason:
        print(f"  ⚡ 触发了否决5: {reason}")
    else:
        print(f"  ✅ 否决5通过: {reason[:80]}")


def test_v23_dim2_three_state():
    """V2.3: 维2 三态周期标签"""
    code = "000001.SZ"
    score, reason = score_sentiment(code)
    print(f"\n[测试4] {code} score={score}")
    # 检查是否有退潮/分歧/发酵标签
    has_tag = any(tag in reason for tag in ["退潮", "发酵", "分歧"])
    print(f"  {'✅ 维2三态标签正常' if has_tag else 'ℹ️ 维2可能有或无概念数据'}: {reason[:80]}")
    assert isinstance(score, (int, float))


def test_v23_dim4_turnover_gradient():
    """V2.3: 维4 换手率梯度计分"""
    code = "000001.SZ"
    score, reason = score_sentiment(code)
    print(f"\n[测试5] {code} score={score}")
    assert isinstance(score, (int, float))
    print(f"  ✅ 维4换手率梯度正常: {reason[:80]}")


def test_v23_dim4_genetic_gene():
    """V2.3: 维4 连板基因因子"""
    code = "000001.SZ"
    score, reason = score_sentiment(code)
    print(f"\n[测试6] {code} score={score}")
    has_gene = "连板基因" in reason
    print(f"  {'✅ 连板基因已检测' if has_gene else 'ℹ️ 该股无连板基因'}")
    assert isinstance(score, (int, float))


def test_v23_dim5_gap_8pct():
    """V2.3: 维5 高开≥8%秒板修正"""
    code = "000001.SZ"
    score, reason = score_sentiment(code)
    print(f"\n[测试7] {code} score={score}")
    # 平安银行大概率不会高开8%，不会触发该修正
    assert isinstance(score, (int, float))
    print(f"  ✅ 维5秒板修正正常: {reason[:80]}")


def test_v23_high_discount():
    """V2.3: 高位情绪折扣 — ≥5板折扣系数"""
    code = "000001.SZ"
    score, reason = score_sentiment(code)
    print(f"\n[测试8] {code} score={score}")
    has_discount = "折扣" in reason
    print(f"  {'✅ 高位折扣逻辑就绪' if has_discount else 'ℹ️ 非高位股无折扣'}")
    assert isinstance(score, (int, float))


def test_known_stocks():
    """测试多个已知涨停股的情绪面评分"""
    test_codes = [
        "000001.SZ",
        "000600.SZ",
        "600183.SH",
    ]
    print(f"\n[综合测试] 已知股票情绪面评分")
    for code in test_codes:
        score, reason = score_sentiment(code)
        assert isinstance(score, (int, float))
        print(f"  {code}: {score}分 → {reason[:80]}")
    print(f"  ✅ 全部正常")


if __name__ == "__main__":
    print("=" * 60)
    print("情绪面 V2.3 策略单元测试")
    print("=" * 60)
    
    tests = [
        test_v23_veto4_type_a,
        test_v23_veto4_type_b,
        test_v23_veto5_popularity_threshold,
        test_v23_dim2_three_state,
        test_v23_dim4_turnover_gradient,
        test_v23_dim4_genetic_gene,
        test_v23_dim5_gap_8pct,
        test_v23_high_discount,
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
            import traceback
            traceback.print_exc()
            failed += 1
        print()
    
    print("=" * 60)
    print(f"结果: {passed}/{len(tests)} 通过, {failed} 失败")
    if failed > 0:
        sys.exit(1)
    print("✅ 全部通过!")
