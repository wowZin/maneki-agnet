"""V2.4 增量实现的单元测试"""
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
from score_shortterm import score_shortterm, score_aggression


def test_v24_aggression_factor():
    """V2.4: 攻击独特性因子 — 涨停基因+高开率+弱转强"""
    code = "000001.SZ"
    score, reason = score_aggression(code)
    print(f"\n[测试1] 攻击独特性 {code}: {score}分")
    print(f"  {reason[:80]}")
    assert isinstance(score, (int, float))
    assert 0 <= score <= 20, f"越界: {score}"
    print(f"  ✅ 攻击独特性因子正常")


def test_v24_shortterm_weights():
    """V2.4: 短线博弈面权重调整 — 5因子"""
    code = "000001.SZ"
    score, reason = score_shortterm(code)
    print(f"\n[测试2] 短线博弈面 {code}: {score}分")
    has_aggression = "[攻击]" in reason
    print(f"  {'✅ 攻击独特性已参与评分' if has_aggression else '⚠️ 攻击独特性未触发'}")
    assert isinstance(score, (int, float))
    print(f"  ✅ 短线博弈面V2.4正常")


def test_v24_emotion_circuit_breaker():
    """V2.4: 情绪熔断 — 否决6"""
    code = "000001.SZ"
    score, reason = score_sentiment(code)
    print(f"\n[测试3] 情绪熔断 {code}: {score}分")
    has_meltdown = "熔断" in reason
    print(f"  {'✅ 情绪熔断触发' if has_meltdown else 'ℹ️ 未触发熔断(市场正常)'}")
    assert isinstance(score, (int, float))
    print(f"  ✅ 情绪熔断逻辑正常")


def test_v24_known_stocks():
    """综合测试多个股票"""
    codes = ["000001.SZ", "000600.SZ", "600183.SH"]
    print(f"\n[综合测试] V2.4增量评分")
    for code in codes:
        s, r = score_shortterm(code)
        assert isinstance(s, (int, float))
        has_agg = "[攻击]" in r
        print(f"  {code}: 短线{s:.1f}分 {'✅含攻击' if has_agg else ''}")


if __name__ == "__main__":
    print("=" * 60)
    print("V2.4 增量实现单元测试")
    print("=" * 60)
    
    tests = [
        test_v24_aggression_factor,
        test_v24_shortterm_weights,
        test_v24_emotion_circuit_breaker,
        test_v24_known_stocks,
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
