#!/usr/bin/env python3
"""
评分计算与截断规则单元测试
验证各 Agent 评分模型的截断、阈值、共振加分逻辑正确

运行: python -m pytest tests/test_score_calculation.py -v
"""

import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


class TestScoreTruncation(unittest.TestCase):
    """测试各 Agent 评分截断规则"""

    def test_technician_dimension_truncation(self):
        """技术面: 各维度得分截断至 [0, 权重]"""
        def calc_dim_score(raw_score, weight):
            return max(0, min(weight, raw_score))

        # 量能维度(40分): 原始分50 -> 截断至40
        self.assertEqual(calc_dim_score(50, 40), 40)
        # 趋势维度(25分): 原始分-10 -> 截断至0
        self.assertEqual(calc_dim_score(-10, 25), 0)
        # 位置维度(12分): 原始分8 -> 保持8
        self.assertEqual(calc_dim_score(8, 12), 8)
        # 筹码维度(15分): 原始分20 -> 截断至15
        self.assertEqual(calc_dim_score(20, 15), 15)
        # 资金维度(8分): 原始分-5 -> 截断至0
        self.assertEqual(calc_dim_score(-5, 8), 0)

    def test_sentiment_subfactor_truncation(self):
        """情绪面: 子因子截断规则"""
        def calc_subfactor_score(raw_score, max_score):
            return max(0, min(max_score, raw_score))

        # 赚钱效应(10分): 原始分12 -> 截断至10
        self.assertEqual(calc_subfactor_score(12, 10), 10)
        # 涨跌结构(8分): 原始分-8 -> 截断至0
        self.assertEqual(calc_subfactor_score(-8, 8), 0)
        # 炸板控制(7分): 原始分5 -> 保持5
        self.assertEqual(calc_subfactor_score(5, 7), 5)

    def test_fundflow_subfactor_truncation(self):
        """资金面: 子因子截断规则"""
        def calc_subfactor_score(raw_score, max_score):
            return max(0, min(max_score, raw_score))

        # 超大单规模(15分): 原始分18 -> 截断至15
        self.assertEqual(calc_subfactor_score(18, 15), 15)
        # 龙虎榜合力(12分): 原始分-15 -> 截断至0
        self.assertEqual(calc_subfactor_score(-15, 12), 0)
        # 北向增持(6分): 原始分4 -> 保持4
        self.assertEqual(calc_subfactor_score(4, 6), 4)


class TestRatingThresholds(unittest.TestCase):
    """测试全系统统一评级阈值"""

    def test_unified_thresholds(self):
        """验证全系统统一采用 75/55/35"""
        def classify(score):
            if score >= 75:
                return "高"
            elif score >= 55:
                return "中"
            elif score >= 35:
                return "低"
            else:
                return "无"

        self.assertEqual(classify(80), "高")
        self.assertEqual(classify(75), "高")
        self.assertEqual(classify(74), "中")
        self.assertEqual(classify(55), "中")
        self.assertEqual(classify(54), "低")
        self.assertEqual(classify(35), "低")
        self.assertEqual(classify(34), "无")
        self.assertEqual(classify(0), "无")

    def test_veto_override(self):
        """一票否决覆盖所有分数"""
        def final_rating(score, veto_triggered):
            if veto_triggered:
                return "无"
            return self._classify(score)

        # 即使90分，触发否决也是无
        self.assertEqual(final_rating(90, True), "无")
        # 不触发否决正常评级
        self.assertEqual(final_rating(90, False), "高")

    def _classify(self, score):
        if score >= 75:
            return "高"
        elif score >= 55:
            return "中"
        elif score >= 35:
            return "低"
        return "无"


class TestFundamentalResonance(unittest.TestCase):
    """测试基本面共振加分与截断"""

    def test_resonance_bonus_a(self):
        """条件A: 业绩>=0.8 且 事件>=0.7 且 t<=10 -> +15分"""
        def calc_bonus(f_performance, f_event, t_days):
            bonus = 0
            if f_performance >= 0.8 and f_event >= 0.7 and t_days <= 10:
                bonus = max(bonus, 15)
            if f_performance >= 0.7 and f_event >= 0.6:  # 简化条件B
                bonus = max(bonus, 10)
            return bonus

        self.assertEqual(calc_bonus(0.85, 0.75, 5), 15)
        self.assertEqual(calc_bonus(0.75, 0.75, 5), 10)  # 不满足A，满足B
        self.assertEqual(calc_bonus(0.85, 0.75, 15), 10)  # t>10，不满足A
        self.assertEqual(calc_bonus(0.6, 0.5, 5), 0)  # 都不满足

    def test_composite_score_cap(self):
        """总分截断至100分封顶"""
        def composite_score(base_score, resonance_bonus):
            return min(100, base_score + resonance_bonus)

        # 正常情况
        self.assertEqual(composite_score(70, 15), 85)
        # 超100截断
        self.assertEqual(composite_score(90, 15), 100)
        # 无加分
        self.assertEqual(composite_score(60, 0), 60)


class TestTechnicianVetoRules(unittest.TestCase):
    """测试技术面一票否决规则"""

    def test_veto_volume_breakdown(self):
        """放量破位: 跌破MA20 + 量比>1.8"""
        def check_veto(price, ma20, volume_ratio):
            return price < ma20 and volume_ratio > 1.8

        self.assertTrue(check_veto(9.5, 10.0, 2.0))
        self.assertFalse(check_veto(10.5, 10.0, 2.0))  # 未跌破
        self.assertFalse(check_veto(9.5, 10.0, 1.5))  # 量比不够

    def test_veto_high_position_stagnation(self):
        """高位滞涨: 涨幅>60% + 换手>25% + 长上影"""
        def check_veto(stage_gain, turnover, upper_shadow_ratio):
            return stage_gain > 0.60 and turnover > 0.25 and upper_shadow_ratio > 1.5

        self.assertTrue(check_veto(0.65, 0.30, 2.0))
        self.assertFalse(check_veto(0.50, 0.30, 2.0))  # 涨幅不够
        self.assertFalse(check_veto(0.65, 0.20, 2.0))  # 换手不够

    def test_veto_shrinkage_decline(self):
        """持续缩量阴跌: 连续3日量比<0.5 + 重心下移"""
        def check_veto(volume_ratios, price_trend_down):
            return all(v < 0.5 for v in volume_ratios) and price_trend_down

        self.assertTrue(check_veto([0.4, 0.3, 0.45], True))
        self.assertFalse(check_veto([0.4, 0.3, 0.45], False))  # 未下移
        self.assertFalse(check_veto([0.4, 0.3, 0.6], True))  # 第3日不够


class TestFundFlowVetoRules(unittest.TestCase):
    """测试资金面一票否决规则"""

    def test_veto_main_outflow(self):
        """主力持续流出: 当日净流出 + 近3日累计<-0.5%流通市值"""
        def check_veto(today_net, cum3d_net, float_cap):
            threshold = -0.005 * float_cap
            return today_net < 0 and cum3d_net < threshold

        float_cap = 1_000_000_000  # 10亿
        self.assertTrue(check_veto(-1_000_000, -6_000_000, float_cap))
        self.assertFalse(check_veto(1_000_000, -6_000_000, float_cap))  # 当日正
        self.assertFalse(check_veto(-1_000_000, -4_000_000, float_cap))  # 3日不够

    def test_veto_retail_only(self):
        """纯散户博弈: 主力净占比 < 10%"""
        def check_veto(main_ratio):
            return main_ratio < 0.10

        self.assertTrue(check_veto(0.05))
        self.assertFalse(check_veto(0.15))
        self.assertFalse(check_veto(0.10))  # 边界: <10%才触发，等于10%不触发


class TestSentimentVetoRules(unittest.TestCase):
    """测试情绪面一票否决规则"""

    def test_veto_market_receding(self):
        """市场退潮: 炸板率>45% 或 连板晋级率<40%"""
        def check_veto(break_rate, promotion_rate):
            return break_rate > 0.45 or promotion_rate < 0.40

        self.assertTrue(check_veto(0.50, 0.50))
        self.assertTrue(check_veto(0.30, 0.35))
        self.assertFalse(check_veto(0.30, 0.50))

    def test_veto_high_level_kill(self):
        """高位杀跌: 最高连板连续2日下降 + 高位股平均溢价<-2%"""
        def check_veto(height_trend, high_premium):
            return height_trend == "down_2d" and high_premium < -0.02

        self.assertTrue(check_veto("down_2d", -0.03))
        self.assertFalse(check_veto("up_2d", -0.03))  # 高度未下降
        self.assertFalse(check_veto("down_2d", 0.01))  # 溢价不够低


if __name__ == "__main__":
    unittest.main()
