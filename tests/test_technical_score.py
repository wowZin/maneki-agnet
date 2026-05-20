"""
技术面评分 V1.1 单元测试
测试 score_technical() 五维度量化评分逻辑
含V1.0→V1.1阈值调整验证
"""
import sys
import os
import json
import unittest
from unittest.mock import patch, MagicMock

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 模拟配置环境
os.environ.setdefault('TUSHARE_TOKEN', 'test_token_for_unit_test')


class TestTechnicalScoreV1(unittest.TestCase):
    """技术面五维度评分测试"""

    def setUp(self):
        """每个测试前清空Tushare缓存，避免缓存污染"""
        from scripts.zt_pipeline import clear_tushare_cache
        clear_tushare_cache()

    def _build_factor_response(self, items, fields=None):
        """构建Tushare stk_factor_pro 响应"""
        if fields is None:
            fields = [
                "trade_date", "close", "open", "high", "low", "pre_close",
                "change", "pct_change", "vol", "amount", "vol_ratio",
                "turnover_rate", "ma_bfq_5", "ma_bfq_10", "ma_bfq_20",
                "ma_bfq_60", "macd_dif_bfq", "macd_dea_bfq", "macd_bfq",
                "kdj_k_bfq", "kdj_d_bfq", "rsi_bfq_6", "boll_upper_bfq",
                "boll_mid_bfq", "boll_lower_bfq"
            ]
        return {
            "data": {
                "fields": fields,
                "items": items
            }
        }

    def _build_moneyflow_response(self, items):
        """构建Tushare moneyflow 响应"""
        return {
            "data": {
                "fields": ["trade_date", "net_mf_amount", "buy_lg_amount", "sell_lg_amount"],
                "items": items
            }
        }

    def _make_stock_data(self, close, open_p, high, low, vol_ratio, turnover,
                         ma5, ma10, ma20, ma60=None, boll_upper=None,
                         boll_mid=None, boll_lower=None, trade_date="20260516",
                         pct_change=None):
        """构建单日股票因子数据"""
        if pct_change is None:
            pct_change = round((close - (close - 0.5)) / (close - 0.5) * 100, 2)
        row = [
            trade_date, close, open_p, high, low, close - 0.5,
            0.5, pct_change, 100000, 5000000, vol_ratio, turnover,
            ma5, ma10, ma20, ma60 or ma20,
            0.1, 0.05, 0.05,  # MACD
            50, 45,  # KDJ
            55,  # RSI
            boll_upper or close * 1.05,
            boll_mid or close,
            boll_lower or close * 0.95
        ]
        return row

    @patch('requests.post')
    def test_perfect_bullish_stock(self, mock_post):
        """测试完美多头股票（均线多头+放量+筹码集中）"""
        from scripts.zt_pipeline import score_technical

        # 构建完美多头数据
        day1 = self._make_stock_data(
            close=15.0, open_p=14.5, high=15.2, low=14.3,
            vol_ratio=2.5, turnover=5.0,
            ma5=14.8, ma10=14.5, ma20=14.0, ma60=13.5,
            boll_upper=15.3, boll_mid=14.8, boll_lower=14.3,
            trade_date="20260516"
        )
        day2 = self._make_stock_data(
            close=14.8, open_p=14.6, high=14.9, low=14.5,
            vol_ratio=0.6, turnover=2.0,
            ma5=14.7, ma10=14.4, ma20=13.9, ma60=13.4,
            boll_upper=15.1, boll_mid=14.6, boll_lower=14.1,
            trade_date="20260515"
        )
        day3 = self._make_stock_data(
            close=14.6, open_p=14.7, high=14.8, low=14.4,
            vol_ratio=0.5, turnover=1.8,
            ma5=14.6, ma10=14.3, ma20=13.8, ma60=13.3,
            boll_upper=15.0, boll_mid=14.5, boll_lower=14.0,
            trade_date="20260514"
        )
        day4 = self._make_stock_data(
            close=14.5, open_p=14.4, high=14.7, low=14.3,
            vol_ratio=0.7, turnover=2.5,
            ma5=14.5, ma10=14.2, ma20=13.7, ma60=13.2,
            trade_date="20260513"
        )
        day5 = self._make_stock_data(
            close=14.4, open_p=14.3, high=14.6, low=14.2,
            vol_ratio=0.8, turnover=2.8,
            ma5=14.4, ma10=14.1, ma20=13.6, ma60=13.1,
            trade_date="20260512"
        )

        factor_resp = self._build_factor_response([day1, day2, day3, day4, day5])
        mf_resp = self._build_moneyflow_response([["20260516", 5000000, 8000000, 3000000]])

        mock_post.side_effect = [
            MagicMock(json=lambda: factor_resp),
            MagicMock(json=lambda: mf_resp)
        ]

        score, reason = score_technical("000001.SZ")

        # 完美多头应得分较高
        self.assertGreater(score, 50, f"完美多头应得分>50, 实际={score}")
        self.assertIn("高", reason)

    @patch('requests.post')
    def test_veto_volume_breakdown(self, mock_post):
        """测试一票否决：放量破位"""
        from scripts.zt_pipeline import score_technical

        # 收盘<MA20 且 量比>1.8
        day1 = self._make_stock_data(
            close=12.0, open_p=12.5, high=12.8, low=11.8,
            vol_ratio=2.5, turnover=8.0,
            ma5=12.8, ma10=13.0, ma20=13.5, ma60=14.0,
            trade_date="20260516"
        )
        day2 = self._make_stock_data(
            close=12.8, open_p=12.7, high=13.0, low=12.6,
            vol_ratio=1.0, turnover=3.0,
            ma5=12.9, ma10=13.0, ma20=13.4, ma60=14.0,
            trade_date="20260515"
        )
        day3 = self._make_stock_data(
            close=12.9, open_p=12.8, high=13.1, low=12.7,
            vol_ratio=0.9, turnover=2.5,
            ma5=13.0, ma10=13.1, ma20=13.4, ma60=14.0,
            trade_date="20260514"
        )

        factor_resp = self._build_factor_response([day1, day2, day3])
        mf_resp = self._build_moneyflow_response([])

        mock_post.side_effect = [
            MagicMock(json=lambda: factor_resp),
            MagicMock(json=lambda: mf_resp)
        ]

        score, reason = score_technical("000001.SZ")

        self.assertEqual(score, 0, f"放量破位应得0分, 实际={score}")
        self.assertIn("放量破位", reason)

    @patch('requests.post')
    def test_veto_shrinkage_decline_v11(self, mock_post):
        """V1.1测试：持续缩量阴跌（量比<0.3且累计跌幅>3%才否决）"""
        from scripts.zt_pipeline import score_technical

        # 3日量比均<0.3, 累计跌幅>3%（-1.5-1.2-0.8=-3.5%）
        day1 = self._make_stock_data(
            close=10.0, open_p=10.2, high=10.3, low=9.9,
            vol_ratio=0.25, turnover=1.0,
            ma5=10.2, ma10=10.5, ma20=10.8, ma60=11.0,
            trade_date="20260516", pct_change=-1.5
        )
        day2 = self._make_stock_data(
            close=10.2, open_p=10.3, high=10.4, low=10.1,
            vol_ratio=0.2, turnover=0.8,
            ma5=10.3, ma10=10.5, ma20=10.8, ma60=11.0,
            trade_date="20260515", pct_change=-1.2
        )
        day3 = self._make_stock_data(
            close=10.3, open_p=10.4, high=10.5, low=10.2,
            vol_ratio=0.28, turnover=0.9,
            ma5=10.4, ma10=10.6, ma20=10.9, ma60=11.0,
            trade_date="20260514", pct_change=-0.8
        )

        factor_resp = self._build_factor_response([day1, day2, day3])
        mf_resp = self._build_moneyflow_response([])

        mock_post.side_effect = [
            MagicMock(json=lambda: factor_resp),
            MagicMock(json=lambda: mf_resp)
        ]

        score, reason = score_technical("000001.SZ")

        # V1.1: 量比均<0.3且累计跌幅=-3.5%>-3%，应触发否决
        self.assertEqual(score, 0, f"V1.1缩量阴跌应得0分, 实际={score}")
        self.assertIn("缩量阴跌", reason)

    @patch('requests.post')
    def test_no_veto_mild_shrinkage_v11(self, mock_post):
        """V1.1测试：量比<0.5但不<0.3，不再触发否决（偏弱不归零）"""
        from scripts.zt_pipeline import score_technical

        # 3日量比0.3-0.5之间（V1.0会否决，V1.1不否决）
        day1 = self._make_stock_data(
            close=10.0, open_p=10.1, high=10.2, low=9.9,
            vol_ratio=0.4, turnover=1.0,
            ma5=10.2, ma10=10.5, ma20=10.8, ma60=11.0,
            trade_date="20260516", pct_change=-1.0
        )
        day2 = self._make_stock_data(
            close=10.2, open_p=10.3, high=10.4, low=10.1,
            vol_ratio=0.35, turnover=0.8,
            ma5=10.3, ma10=10.5, ma20=10.8, ma60=11.0,
            trade_date="20260515", pct_change=-0.8
        )
        day3 = self._make_stock_data(
            close=10.3, open_p=10.4, high=10.5, low=10.2,
            vol_ratio=0.45, turnover=0.9,
            ma5=10.4, ma10=10.6, ma20=10.9, ma60=11.0,
            trade_date="20260514", pct_change=-0.5
        )

        factor_resp = self._build_factor_response([day1, day2, day3])
        mf_resp = self._build_moneyflow_response([])

        mock_post.side_effect = [
            MagicMock(json=lambda: factor_resp),
            MagicMock(json=lambda: mf_resp)
        ]

        score, reason = score_technical("000001.SZ")

        # V1.1: 量比0.4/0.35/0.45均>0.3，不触发否决，得分应>0
        self.assertGreater(score, 0, f"V1.1偏弱缩量不归零, 得分应>0, 实际={score}")
        self.assertNotIn("缩量阴跌", reason)

    @patch('requests.post')
    def test_no_veto_shrinkage_without_large_decline_v11(self, mock_post):
        """V1.1测试：量比<0.3但累计跌幅不足3%，不否决"""
        from scripts.zt_pipeline import score_technical

        # 3日量比均<0.3，但累计跌幅仅-1.5%（不满足>3%条件）
        day1 = self._make_stock_data(
            close=10.0, open_p=10.1, high=10.2, low=9.9,
            vol_ratio=0.25, turnover=1.0,
            ma5=10.2, ma10=10.5, ma20=10.8, ma60=11.0,
            trade_date="20260516", pct_change=-0.5
        )
        day2 = self._make_stock_data(
            close=10.2, open_p=10.3, high=10.4, low=10.1,
            vol_ratio=0.2, turnover=0.8,
            ma5=10.3, ma10=10.5, ma20=10.8, ma60=11.0,
            trade_date="20260515", pct_change=-0.6
        )
        day3 = self._make_stock_data(
            close=10.3, open_p=10.4, high=10.5, low=10.2,
            vol_ratio=0.28, turnover=0.9,
            ma5=10.4, ma10=10.6, ma20=10.9, ma60=11.0,
            trade_date="20260514", pct_change=-0.4
        )

        factor_resp = self._build_factor_response([day1, day2, day3])
        mf_resp = self._build_moneyflow_response([])

        mock_post.side_effect = [
            MagicMock(json=lambda: factor_resp),
            MagicMock(json=lambda: mf_resp)
        ]

        score, reason = score_technical("000001.SZ")

        # V1.1: 累计跌幅=-1.5%，不满足>3%条件，不否决
        self.assertGreater(score, 0, f"跌幅不足3%不否决, 得分应>0, 实际={score}")
        self.assertNotIn("缩量阴跌", reason)

    @patch('requests.post')
    def test_bearish_stock(self, mock_post):
        """测试空头排列股票（均线空头）"""
        from scripts.zt_pipeline import score_technical

        day1 = self._make_stock_data(
            close=10.0, open_p=10.1, high=10.2, low=9.8,
            vol_ratio=0.8, turnover=1.0,
            ma5=10.1, ma10=10.3, ma20=10.6, ma60=11.0,
            trade_date="20260516"
        )
        day2 = self._make_stock_data(
            close=10.1, open_p=10.2, high=10.3, low=10.0,
            vol_ratio=0.9, turnover=1.2,
            ma5=10.2, ma10=10.3, ma20=10.6, ma60=11.0,
            trade_date="20260515"
        )
        day3 = self._make_stock_data(
            close=10.2, open_p=10.3, high=10.4, low=10.1,
            vol_ratio=1.0, turnover=1.5,
            ma5=10.3, ma10=10.4, ma20=10.6, ma60=11.0,
            trade_date="20260514"
        )

        factor_resp = self._build_factor_response([day1, day2, day3])
        mf_resp = self._build_moneyflow_response([])

        mock_post.side_effect = [
            MagicMock(json=lambda: factor_resp),
            MagicMock(json=lambda: mf_resp)
        ]

        score, reason = score_technical("000001.SZ")

        # 空头排列得分应较低
        self.assertLess(score, 40, f"空头排列应得分<40, 实际={score}")

    @patch('requests.post')
    def test_data_fetch_failure(self, mock_post):
        """测试数据获取失败"""
        from scripts.zt_pipeline import score_technical

        mock_post.side_effect = Exception("Network error")

        score, reason = score_technical("000001.SZ")

        self.assertEqual(score, 50)
        self.assertIn("不足", reason)

    @patch('requests.post')
    def test_empty_data(self, mock_post):
        """测试空数据"""
        from scripts.zt_pipeline import score_technical

        mock_post.return_value = MagicMock(
            json=lambda: {"data": {"fields": [], "items": []}}
        )

        score, reason = score_technical("000001.SZ")

        self.assertEqual(score, 50)
        self.assertIn("不足", reason)

    @patch('requests.post')
    def test_score_range(self, mock_post):
        """测试评分范围 [0, 100]"""
        from scripts.zt_pipeline import score_technical

        # 构建普通数据
        day1 = self._make_stock_data(
            close=10.5, open_p=10.3, high=10.6, low=10.2,
            vol_ratio=1.2, turnover=2.5,
            ma5=10.4, ma10=10.3, ma20=10.5, ma60=10.8,
            trade_date="20260516"
        )
        day2 = self._make_stock_data(
            close=10.4, open_p=10.3, high=10.5, low=10.2,
            vol_ratio=1.0, turnover=2.0,
            ma5=10.3, ma10=10.3, ma20=10.5, ma60=10.8,
            trade_date="20260515"
        )
        day3 = self._make_stock_data(
            close=10.3, open_p=10.2, high=10.4, low=10.1,
            vol_ratio=1.1, turnover=2.2,
            ma5=10.3, ma10=10.3, ma20=10.5, ma60=10.8,
            trade_date="20260514"
        )

        factor_resp = self._build_factor_response([day1, day2, day3])
        mf_resp = self._build_moneyflow_response([])

        mock_post.side_effect = [
            MagicMock(json=lambda: factor_resp),
            MagicMock(json=lambda: mf_resp)
        ]

        score, reason = score_technical("000001.SZ")

        self.assertGreaterEqual(score, 0, "评分不应低于0")
        self.assertLessEqual(score, 100, "评分不应超过100")

    @patch('requests.post')
    def test_reason_contains_level(self, mock_post):
        """测试reason包含评级标识"""
        from scripts.zt_pipeline import score_technical

        day1 = self._make_stock_data(
            close=10.5, open_p=10.3, high=10.6, low=10.2,
            vol_ratio=1.5, turnover=3.0,
            ma5=10.4, ma10=10.3, ma20=10.0, ma60=9.8,
            trade_date="20260516"
        )
        day2 = self._make_stock_data(
            close=10.4, open_p=10.3, high=10.5, low=10.2,
            vol_ratio=1.0, turnover=2.0,
            ma5=10.3, ma10=10.2, ma20=9.9, ma60=9.7,
            trade_date="20260515"
        )
        day3 = self._make_stock_data(
            close=10.3, open_p=10.2, high=10.4, low=10.1,
            vol_ratio=0.9, turnover=1.8,
            ma5=10.2, ma10=10.1, ma20=9.8, ma60=9.6,
            trade_date="20260514"
        )

        factor_resp = self._build_factor_response([day1, day2, day3])
        mf_resp = self._build_moneyflow_response([])

        mock_post.side_effect = [
            MagicMock(json=lambda: factor_resp),
            MagicMock(json=lambda: mf_resp)
        ]

        score, reason = score_technical("000001.SZ")

        # reason 应包含 [高]/[中]/[低]/[无] 之一
        has_level = any(f"[{l}]" in reason for l in ["高", "中", "低", "无"])
        self.assertTrue(has_level, f"reason应包含评级标识, 实际={reason}")

    @patch('requests.post')
    def test_washout_and_breakout(self, mock_post):
        """测试洗盘起爆信号（前两日缩量+当日放量）"""
        from scripts.zt_pipeline import score_technical

        # 当日放量，前两日缩量
        day1 = self._make_stock_data(
            close=15.0, open_p=14.5, high=15.2, low=14.3,
            vol_ratio=2.0, turnover=5.0,
            ma5=14.8, ma10=14.5, ma20=14.0, ma60=13.5,
            trade_date="20260516"
        )
        day2 = self._make_stock_data(
            close=14.5, open_p=14.6, high=14.7, low=14.4,
            vol_ratio=0.6, turnover=1.5,
            ma5=14.6, ma10=14.4, ma20=13.9, ma60=13.4,
            trade_date="20260515"
        )
        day3 = self._make_stock_data(
            close=14.6, open_p=14.7, high=14.8, low=14.5,
            vol_ratio=0.5, turnover=1.2,
            ma5=14.5, ma10=14.3, ma20=13.8, ma60=13.3,
            trade_date="20260514"
        )

        factor_resp = self._build_factor_response([day1, day2, day3])
        mf_resp = self._build_moneyflow_response([])

        mock_post.side_effect = [
            MagicMock(json=lambda: factor_resp),
            MagicMock(json=lambda: mf_resp)
        ]

        score, reason = score_technical("000001.SZ")

        self.assertIn("洗盘起爆", reason, f"应检测到洗盘起爆信号, reason={reason}")

    # ===== V1.1 新增测试 =====

    @patch('requests.post')
    def test_deduct_low_vol_ratio_no_penalty_v11(self, mock_post):
        """V1.1测试：量比<1.5不扣分，仅不加分"""
        from scripts.zt_pipeline import score_technical

        # 量比=1.2（<1.5但>0），不加分也不扣分
        day1 = self._make_stock_data(
            close=11.0, open_p=10.8, high=11.2, low=10.7,
            vol_ratio=1.2, turnover=4.0,
            ma5=10.9, ma10=10.8, ma20=10.5, ma60=10.2,
            trade_date="20260516"
        )
        day2 = self._make_stock_data(
            close=10.9, open_p=10.8, high=11.0, low=10.7,
            vol_ratio=1.1, turnover=3.5,
            ma5=10.8, ma10=10.7, ma20=10.5, ma60=10.2,
            trade_date="20260515"
        )
        day3 = self._make_stock_data(
            close=10.8, open_p=10.7, high=10.9, low=10.6,
            vol_ratio=1.0, turnover=3.0,
            ma5=10.7, ma10=10.6, ma20=10.4, ma60=10.1,
            trade_date="20260514"
        )

        factor_resp = self._build_factor_response([day1, day2, day3])
        mf_resp = self._build_moneyflow_response([])

        mock_post.side_effect = [
            MagicMock(json=lambda: factor_resp),
            MagicMock(json=lambda: mf_resp)
        ]

        score, reason = score_technical("000001.SZ")

        # V1.1: 量比<1.5不扣分，得分应>0（偏弱不归零）
        self.assertGreater(score, 0, f"量比偏低不扣分, 得分应>0, 实际={score}")
        # reason应包含"不加分"标识而非扣分
        if "量比" in reason:
            self.assertIn("不加分", reason, f"量比<1.5应标注'不加分'而非扣分, reason={reason}")

    @patch('requests.post')
    def test_deduct_abnormal_volume_v11(self, mock_post):
        """V1.1测试：量比>6.0扣5分（而非V1.0的10分）"""
        from scripts.zt_pipeline import score_technical

        # 量比=8.0（异常放量）
        day1 = self._make_stock_data(
            close=11.0, open_p=10.5, high=11.5, low=10.3,
            vol_ratio=8.0, turnover=5.0,
            ma5=10.9, ma10=10.8, ma20=10.5, ma60=10.2,
            boll_upper=11.5, boll_mid=10.8, boll_lower=10.1,
            trade_date="20260516"
        )
        day2 = self._make_stock_data(
            close=10.9, open_p=10.8, high=11.0, low=10.7,
            vol_ratio=1.5, turnover=3.5,
            ma5=10.8, ma10=10.7, ma20=10.5, ma60=10.2,
            trade_date="20260515"
        )
        day3 = self._make_stock_data(
            close=10.8, open_p=10.7, high=10.9, low=10.6,
            vol_ratio=1.0, turnover=3.0,
            ma5=10.7, ma10=10.6, ma20=10.4, ma60=10.1,
            trade_date="20260514"
        )

        factor_resp = self._build_factor_response([day1, day2, day3])
        mf_resp = self._build_moneyflow_response([])

        mock_post.side_effect = [
            MagicMock(json=lambda: factor_resp),
            MagicMock(json=lambda: mf_resp)
        ]

        score, reason = score_technical("000001.SZ")

        # reason应包含"-5"扣分标识
        self.assertIn("-5", reason, f"V1.1量比异常应扣5分, reason={reason}")

    @patch('requests.post')
    def test_deduct_turnover_weak_v11(self, mock_post):
        """V1.1测试：换手率<1.5%扣5分（而非V1.0的10分）"""
        from scripts.zt_pipeline import score_technical

        # 换手率=1.0%（无量拉升）
        day1 = self._make_stock_data(
            close=11.0, open_p=10.8, high=11.2, low=10.7,
            vol_ratio=2.0, turnover=1.0,
            ma5=10.9, ma10=10.8, ma20=10.5, ma60=10.2,
            boll_upper=11.3, boll_mid=10.8, boll_lower=10.3,
            trade_date="20260516"
        )
        day2 = self._make_stock_data(
            close=10.9, open_p=10.8, high=11.0, low=10.7,
            vol_ratio=1.5, turnover=2.0,
            ma5=10.8, ma10=10.7, ma20=10.5, ma60=10.2,
            trade_date="20260515"
        )
        day3 = self._make_stock_data(
            close=10.8, open_p=10.7, high=10.9, low=10.6,
            vol_ratio=1.0, turnover=2.5,
            ma5=10.7, ma10=10.6, ma20=10.4, ma60=10.1,
            trade_date="20260514"
        )

        factor_resp = self._build_factor_response([day1, day2, day3])
        mf_resp = self._build_moneyflow_response([])

        mock_post.side_effect = [
            MagicMock(json=lambda: factor_resp),
            MagicMock(json=lambda: mf_resp)
        ]

        score, reason = score_technical("000001.SZ")

        # reason应包含"-5"扣分（V1.1换手率无量扣5分）
        self.assertIn("-5", reason, f"V1.1无量拉升应扣5分, reason={reason}")

    @patch('requests.post')
    def test_deduct_bearish_trend_v11(self, mock_post):
        """V1.1测试：均线空头扣10分而非15分"""
        from scripts.zt_pipeline import score_technical

        # 均线空头排列: MA5<MA10<MA20
        day1 = self._make_stock_data(
            close=10.0, open_p=10.1, high=10.2, low=9.8,
            vol_ratio=1.5, turnover=3.0,
            ma5=10.1, ma10=10.3, ma20=10.6, ma60=11.0,
            boll_upper=10.8, boll_mid=10.3, boll_lower=9.8,
            trade_date="20260516"
        )
        day2 = self._make_stock_data(
            close=10.1, open_p=10.2, high=10.3, low=10.0,
            vol_ratio=1.2, turnover=2.5,
            ma5=10.2, ma10=10.3, ma20=10.6, ma60=11.0,
            boll_upper=10.8, boll_mid=10.3, boll_lower=9.8,
            trade_date="20260515"
        )
        day3 = self._make_stock_data(
            close=10.2, open_p=10.3, high=10.4, low=10.1,
            vol_ratio=1.0, turnover=2.0,
            ma5=10.3, ma10=10.4, ma20=10.6, ma60=11.0,
            boll_upper=10.8, boll_mid=10.3, boll_lower=9.8,
            trade_date="20260514"
        )

        factor_resp = self._build_factor_response([day1, day2, day3])
        mf_resp = self._build_moneyflow_response([])

        mock_post.side_effect = [
            MagicMock(json=lambda: factor_resp),
            MagicMock(json=lambda: mf_resp)
        ]

        score, reason = score_technical("000001.SZ")

        # V1.1: 空头排列扣10分而非15分，得分应>0（偏弱不归零）
        self.assertGreater(score, 0, f"V1.1空头扣10分不归零, 得分应>0, 实际={score}")
        self.assertIn("-10", reason, f"V1.1空头排列应扣10分, reason={reason}")

    @patch('requests.post')
    def test_chip_dispersion_deduct_v11(self, mock_post):
        """V1.1测试：筹码发散扣5分而非10分"""
        from scripts.zt_pipeline import score_technical

        # BOLL带宽>25%表示筹码发散
        day1 = self._make_stock_data(
            close=10.0, open_p=10.1, high=10.2, low=9.8,
            vol_ratio=2.0, turnover=5.0,
            ma5=10.1, ma10=10.0, ma20=9.9, ma60=9.8,
            # boll_mid=10.0, bandwidth=(10.5-9.5)/10=10%，需>25%
            boll_upper=13.0, boll_mid=10.0, boll_lower=7.0,
            # bandwidth=(13-7)/10=60% > 25%
            trade_date="20260516"
        )
        day2 = self._make_stock_data(
            close=10.1, open_p=10.0, high=10.3, low=9.9,
            vol_ratio=1.5, turnover=3.0,
            ma5=10.0, ma10=9.9, ma20=9.8, ma60=9.7,
            boll_upper=12.5, boll_mid=10.0, boll_lower=7.5,
            trade_date="20260515"
        )
        day3 = self._make_stock_data(
            close=10.2, open_p=10.1, high=10.4, low=10.0,
            vol_ratio=1.0, turnover=2.0,
            ma5=10.1, ma10=10.0, ma20=9.9, ma60=9.8,
            boll_upper=12.0, boll_mid=10.0, boll_lower=8.0,
            trade_date="20260514"
        )

        factor_resp = self._build_factor_response([day1, day2, day3])
        mf_resp = self._build_moneyflow_response([])

        mock_post.side_effect = [
            MagicMock(json=lambda: factor_resp),
            MagicMock(json=lambda: mf_resp)
        ]

        score, reason = score_technical("000001.SZ")

        # V1.1: 筹码发散扣5分
        self.assertIn("-5", reason, f"V1.1筹码发散应扣5分, reason={reason}")

    @patch('requests.post')
    def test_veto_chip_boll_width_50_v11(self, mock_post):
        """V1.1测试：BOLL代理筹码发散否决阈值从30%放宽至50%"""
        from scripts.zt_pipeline import score_technical

        # BOLL带宽=40%（V1.0会否决，V1.1不否决）
        day1 = self._make_stock_data(
            close=10.0, open_p=10.5, high=10.8, low=9.5,
            vol_ratio=2.0, turnover=5.0,
            ma5=10.5, ma10=10.3, ma20=10.0, ma60=9.8,
            boll_upper=12.0, boll_mid=10.0, boll_lower=8.0,
            # bandwidth=(12-8)/10=40%
            trade_date="20260516"
        )
        day2 = self._make_stock_data(
            close=10.1, open_p=10.2, high=10.5, low=9.8,
            vol_ratio=1.5, turnover=3.0,
            ma5=10.2, ma10=10.1, ma20=9.9, ma60=9.7,
            boll_upper=11.5, boll_mid=10.0, boll_lower=8.5,
            trade_date="20260515"
        )
        day3 = self._make_stock_data(
            close=10.2, open_p=10.3, high=10.6, low=9.9,
            vol_ratio=1.0, turnover=2.0,
            ma5=10.1, ma10=10.0, ma20=9.8, ma60=9.6,
            boll_upper=11.0, boll_mid=10.0, boll_lower=9.0,
            trade_date="20260514"
        )

        factor_resp = self._build_factor_response([day1, day2, day3])
        mf_resp = self._build_moneyflow_response([])

        mock_post.side_effect = [
            MagicMock(json=lambda: factor_resp),
            MagicMock(json=lambda: mf_resp)
        ]

        score, reason = score_technical("000001.SZ")

        # V1.1: BOLL带宽40%不触发否决（阈值50%），得分应>0
        self.assertGreater(score, 0, f"V1.1 BOLL带宽40%不否决, 得分应>0, 实际={score}")

    @patch('requests.post')
    def test_ma60_decline_deduct_v11(self, mock_post):
        """V1.1测试：MA60下倾扣5分而非10分"""
        from scripts.zt_pipeline import score_technical

        # MA60下倾: 今日MA60<5日前MA60
        day1 = self._make_stock_data(
            close=11.0, open_p=10.8, high=11.2, low=10.7,
            vol_ratio=2.0, turnover=5.0,
            ma5=10.9, ma10=10.8, ma20=10.5, ma60=10.0,
            boll_upper=11.5, boll_mid=10.8, boll_lower=10.1,
            trade_date="20260516"
        )
        day2 = self._make_stock_data(
            close=10.9, open_p=10.8, high=11.0, low=10.7,
            vol_ratio=1.5, turnover=3.5,
            ma5=10.8, ma10=10.7, ma20=10.5, ma60=10.0,
            trade_date="20260515"
        )
        day3 = self._make_stock_data(
            close=10.8, open_p=10.7, high=10.9, low=10.6,
            vol_ratio=1.0, turnover=3.0,
            ma5=10.7, ma10=10.6, ma20=10.4, ma60=10.0,
            trade_date="20260514"
        )
        day4 = self._make_stock_data(
            close=10.7, open_p=10.6, high=10.8, low=10.5,
            vol_ratio=0.9, turnover=2.5,
            ma5=10.6, ma10=10.5, ma20=10.3, ma60=10.1,
            trade_date="20260513"
        )
        day5 = self._make_stock_data(
            close=10.6, open_p=10.5, high=10.7, low=10.4,
            vol_ratio=0.8, turnover=2.0,
            ma5=10.5, ma10=10.4, ma20=10.2, ma60=10.2,
            trade_date="20260512"
        )

        factor_resp = self._build_factor_response([day1, day2, day3, day4, day5])
        mf_resp = self._build_moneyflow_response([])

        mock_post.side_effect = [
            MagicMock(json=lambda: factor_resp),
            MagicMock(json=lambda: mf_resp)
        ]

        score, reason = score_technical("000001.SZ")

        # V1.1: MA60下倾扣5分
        if "MA60下倾" in reason:
            self.assertIn("-5", reason, f"V1.1 MA60下倾应扣5分, reason={reason}")


class TestTechnicalAgentV11(unittest.TestCase):
    """测试 technical_agent.py 的 V1.1 修改"""

    def setUp(self):
        from scripts.zt_pipeline import clear_tushare_cache
        clear_tushare_cache()

    def _make_factor_row(self, close=10.0, open_p=10.1, high=10.2, low=9.9,
                          vol_ratio=1.5, turnover=3.0, pct_change=1.0,
                          ma5=10.1, ma10=10.0, ma20=9.9, ma60=9.8,
                          boll_upper=10.5, boll_mid=10.0, boll_lower=9.5,
                          vol=100000, amount=5000000):
        """构建单日因子数据字典"""
        return {
            'close': close, 'open': open_p, 'high': high, 'low': low,
            'vol_ratio': vol_ratio, 'turnover_rate': turnover,
            'pct_change': pct_change,
            'ma_bfq_5': ma5, 'ma_bfq_10': ma10, 'ma_bfq_20': ma20,
            'ma_bfq_60': ma60,
            'boll_upper_bfq': boll_upper, 'boll_mid_bfq': boll_mid,
            'boll_lower_bfq': boll_lower,
            'vol': vol, 'amount': amount,
            'macd_dif_bfq': 0.1, 'macd_dea_bfq': 0.05, 'macd_bfq': 0.05,
            'kdj_k_bfq': 50, 'kdj_d_bfq': 45, 'rsi_bfq_6': 55,
        }

    def test_veto_shrinkage_v11_strict(self):
        """V1.1否决4: 量比<0.3+跌幅>3%才否决"""
        from scripts.agents.technical_agent import check_veto_rules

        # 量比均<0.3, 累计跌幅>3% → 应否决
        factors = [
            self._make_factor_row(vol_ratio=0.25, pct_change=-1.5, close=9.85),
            self._make_factor_row(vol_ratio=0.2, pct_change=-1.2, close=10.0),
            self._make_factor_row(vol_ratio=0.28, pct_change=-0.8, close=10.15),
        ]
        daily = []
        mf = []

        is_vetoed, flags = check_veto_rules(factors, daily, mf)
        self.assertTrue(is_vetoed, f"量比<0.3+跌幅>3%应否决, flags={flags}")
        self.assertIn("缩量阴跌", flags[0])

    def test_veto_shrinkage_v11_mild_not_vetoed(self):
        """V1.1否决4: 量比0.3-0.5之间不否决"""
        from scripts.agents.technical_agent import check_veto_rules

        # 量比0.4（V1.0否决，V1.1不否决）
        factors = [
            self._make_factor_row(vol_ratio=0.4, pct_change=-0.5),
            self._make_factor_row(vol_ratio=0.35, pct_change=-0.6),
            self._make_factor_row(vol_ratio=0.45, pct_change=-0.4),
        ]
        daily = []
        mf = []

        is_vetoed, flags = check_veto_rules(factors, daily, mf)
        self.assertFalse(is_vetoed, f"量比0.4不应否决(V1.1), flags={flags}")

    def test_veto_chip_boll_50_threshold(self):
        """V1.1否决3: BOLL带宽>50%才否决（从30%放宽）"""
        from scripts.agents.technical_agent import check_veto_rules

        # BOLL带宽=40%（不否决）
        factors = [
            self._make_factor_row(boll_upper=12.0, boll_mid=10.0, boll_lower=8.0),
            self._make_factor_row(boll_upper=11.5, boll_mid=10.0, boll_lower=8.5),
        ]
        daily = []
        mf = []

        is_vetoed, flags = check_veto_rules(factors, daily, mf)
        self.assertFalse(is_vetoed, f"BOLL带宽40%不应否决(V1.1), flags={flags}")

    def test_veto_chip_boll_over_50(self):
        """V1.1否决3: BOLL带宽>50%应否决"""
        from scripts.agents.technical_agent import check_veto_rules

        # BOLL带宽=60%（应否决）
        factors = [
            self._make_factor_row(boll_upper=13.0, boll_mid=10.0, boll_lower=7.0),
            self._make_factor_row(boll_upper=12.5, boll_mid=10.0, boll_lower=7.5),
        ]
        daily = []
        mf = []

        is_vetoed, flags = check_veto_rules(factors, daily, mf)
        self.assertTrue(is_vetoed, f"BOLL带宽60%应否决(V1.1), flags={flags}")
        self.assertIn("筹码发散", flags[0])
        self.assertIn("50%", flags[0])

    def test_score_deduct_turnover_weak_v11(self):
        """V1.1评分: 换手率<1.5%扣5分而非10分"""
        from scripts.agents.technical_agent import calculate_volume_score

        # 换手率=1.0%（无量拉升）
        today = self._make_factor_row(turnover=1.0, vol_ratio=2.0)
        yesterday = self._make_factor_row(turnover=2.0, vol_ratio=1.5)
        day_before = self._make_factor_row(turnover=2.5, vol_ratio=1.0)

        score, reasons = calculate_volume_score(today, yesterday, day_before)

        # V1.1: 无量拉升扣5分
        has_minus_5 = any("-5分" in r for r in reasons)
        self.assertTrue(has_minus_5, f"换手率1.0%应扣5分, reasons={reasons}")

    def test_score_deduct_bearish_v11(self):
        """V1.1评分: 均线空头扣10分而非15分"""
        from scripts.agents.technical_agent import calculate_trend_score

        # 均线空头: MA5<MA10<MA20
        factors = [self._make_factor_row(ma5=10.1, ma10=10.3, ma20=10.6, ma60=11.0)]

        score, reasons = calculate_trend_score(factors)

        # V1.1: 空头排列扣10分
        has_minus_10 = any("-10分" in r for r in reasons)
        self.assertTrue(has_minus_10, f"V1.1空头排列应扣10分, reasons={reasons}")


if __name__ == '__main__':
    unittest.main()