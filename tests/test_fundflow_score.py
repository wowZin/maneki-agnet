"""
资金面评分 V1.0 单元测试
测试 score_fundflow() 五维度量化评分逻辑
"""
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 模拟配置环境
os.environ.setdefault('TUSHARE_TOKEN', 'test_token_for_unit_test')


def _build_tushare_response(items, fields=None):
    """通用Tushare API响应构建器 - 返回list格式（Tushare真实格式）"""
    return {
        "data": {
            "fields": fields or [],
            "items": items
        }
    }


class TestFundflowScoreV1(unittest.TestCase):
    """资金面五维度评分测试"""

    def _mock_requests_post(self, responses_map):
        """
        创建mock，根据api_name返回不同响应
        responses_map: {api_name: response_dict}
        注意：requests.post(url, json=...) 中 json 是关键字参数
        """
        def _post(url, **kwargs):
            json_data = kwargs.get("json", {})
            api_name = json_data.get("api_name", "")
            response_data = responses_map.get(api_name, _build_tushare_response([]))
            mock_resp = MagicMock()
            mock_resp.json.return_value = response_data
            return mock_resp
        return _post

    # === 数据构建器 ===

    def _build_moneyflow_items(self, buy_elg, sell_elg, buy_lg, sell_lg, net_mf, days=3):
        """构建个股资金流向数据（近N天，按日期降序）
        moneyflow fields: trade_date,buy_elg_vol,buy_elg_amount,sell_elg_vol,sell_elg_amount,
                          buy_lg_vol,buy_lg_amount,sell_lg_vol,sell_lg_amount,net_mf_vol,net_mf_amount
        """
        items = []
        for i in range(days):
            # 简单递减模拟历史数据
            factor = 1.0 - i * 0.1
            items.append([
                f"2026051{6-i}", 1000, buy_elg * factor, 800, sell_elg * factor,
                2000, buy_lg * factor, 1500, sell_lg * factor,
                3000, net_mf * factor
            ])
        return items

    def _build_top_list_items(self, net_rate):
        """构建龙虎榜数据
        top_list fields: trade_date,ts_code,name,close,pct_change,turnover_rate,amount,l_sell,l_buy,l_amount,net_amount,net_rate
        """
        return [["20260516", "600000.SH", "测试股", 10.0, 10.0, 8.5, 50000, 2000, 3000, 5000, 1000, net_rate]]

    def _build_top_inst_items(self, inst_buy, hot_money_buy):
        """构建龙虎榜机构交易数据
        top_inst fields: trade_date,ts_code,exalter,side,buy,buy_rate,sell,sell_rate,net_buy,reason
        """
        items = []
        if inst_buy > 0:
            items.append(["20260516", "600000.SH", "机构专用", "B", inst_buy, 5.0, 0, 0, inst_buy, "涨停"])
        if hot_money_buy > 0:
            items.append(["20260516", "600000.SH", "知名游资营业部", "B", hot_money_buy, 3.0, 0, 0, hot_money_buy, "涨停"])
        return items

    def _build_hk_hold_items(self, vol_today, vol_5d_ago, ratio_today, ratio_prev):
        """构建北向持股数据
        hk_hold fields: trade_date,ts_code,name,vol,ratio,exchange
        注意：Tushare返回数据按日期降序（最新日期在前）
        """
        items = []
        # 生成5天数据（日期降序：最新日期在前）
        for i in range(5):
            # i=0是最新日期，i=4是5天前
            vol = vol_5d_ago + (vol_today - vol_5d_ago) * (5 - i) / 5
            ratio = ratio_prev + (ratio_today - ratio_prev) * (5 - i) / 5
            items.append([f"2026051{6-i}", "600000.SH", "测试股", vol, ratio, "SH"])
        return items

    def _build_daily_basic_items(self, circ_mv, turnover_rate):
        """构建每日基本面数据
        daily_basic fields: trade_date,ts_code,close,turnover_rate,turnover_rate_f,volume_ratio,total_mv,circ_mv
        """
        return [["20260516", "600000.SH", 10.0, turnover_rate, 7.5, 1.2, 100000, circ_mv]]


class TestFundflowVeto(TestFundflowScoreV1):
    """一票否决规则测试"""

    @patch('scripts.zt_pipeline.requests.post')
    def test_veto_main_capital_continuous_outflow(self, mock_post):
        """否决规则1: 主力3日累计净流出 > 0.5%流通市值"""
        # 3日净流出 = -3000万，流通市值=10万(万)=100000万，0.5%=500万 → 触发
        moneyflow_items = self._build_moneyflow_items(500, 1000, 800, 1200, -1000, days=3)
        daily_items = self._build_daily_basic_items(circ_mv=10, turnover_rate=8)  # circ_mv=10万

        responses = {
            "moneyflow": _build_tushare_response(moneyflow_items,
                ["trade_date","buy_elg_vol","buy_elg_amount","sell_elg_vol","sell_elg_amount",
                 "buy_lg_vol","buy_lg_amount","sell_lg_vol","sell_lg_amount","net_mf_vol","net_mf_amount"]),
            "daily_basic": _build_tushare_response(daily_items,
                ["trade_date","ts_code","close","turnover_rate","turnover_rate_f","volume_ratio","total_mv","circ_mv"]),
        }
        mock_post.side_effect = self._mock_requests_post(responses)

        from scripts.zt_pipeline import score_fundflow
        score, reason = score_fundflow("600000.SH")
        self.assertEqual(score, 0)
        self.assertIn("否决", reason)

    @patch('scripts.zt_pipeline.requests.post')
    def test_veto_pure_retail(self, mock_post):
        """否决规则2: 主力净占比 < 10%"""
        # 买超大单=100, 卖超大单=99, 买大单=200, 卖大单=199 → 主力净额=2, 总量=598 → 占比=0.33%
        # 超大单总量=100+99=199, 总量=598 → 超大单占比=33.3% > 5%, 不触发否决
        # 修改为超大单占比<5%: 买超大单=10, 卖超大单=9, 买大单=200, 卖大单=199
        moneyflow_items = [
            ["20260516", 100, 10, 100, 9, 200, 200, 100, 199, 300, 2]
        ]
        daily_items = self._build_daily_basic_items(circ_mv=1000, turnover_rate=5)

        responses = {
            "moneyflow": _build_tushare_response(moneyflow_items,
                ["trade_date","buy_elg_vol","buy_elg_amount","sell_elg_vol","sell_elg_amount",
                 "buy_lg_vol","buy_lg_amount","sell_lg_vol","sell_lg_amount","net_mf_vol","net_mf_amount"]),
            "daily_basic": _build_tushare_response(daily_items,
                ["trade_date","ts_code","close","turnover_rate","turnover_rate_f","volume_ratio","total_mv","circ_mv"]),
        }
        mock_post.side_effect = self._mock_requests_post(responses)

        from scripts.zt_pipeline import score_fundflow
        score, reason = score_fundflow("600000.SH")
        self.assertEqual(score, 0)
        self.assertIn("否决", reason)

    @patch('scripts.zt_pipeline.requests.post')
    def test_veto_dragon_tiger_massive_sell(self, mock_post):
        """否决规则3: 龙虎榜机构/游资净卖出 > 净买入2倍"""
        moneyflow_items = self._build_moneyflow_items(2000, 1000, 3000, 2000, 2000, days=1)
        # 机构买入=1000万，游资卖出=-5000万 → 净卖=5000 > 净买=1000*2=2000
        top_inst_items = [
            ["20260516", "600000.SH", "机构专用", "B", 1000, 5.0, 0, 0, 1000, "涨停"],
            ["20260516", "600000.SH", "知名游资", "S", 0, 0, 5000, 10.0, -5000, "涨停"],
        ]
        daily_items = self._build_daily_basic_items(circ_mv=1000, turnover_rate=5)

        responses = {
            "moneyflow": _build_tushare_response(moneyflow_items,
                ["trade_date","buy_elg_vol","buy_elg_amount","sell_elg_vol","sell_elg_amount",
                 "buy_lg_vol","buy_lg_amount","sell_lg_vol","sell_lg_amount","net_mf_vol","net_mf_amount"]),
            "top_inst": _build_tushare_response(top_inst_items,
                ["trade_date","ts_code","exalter","side","buy","buy_rate","sell","sell_rate","net_buy","reason"]),
            "daily_basic": _build_tushare_response(daily_items,
                ["trade_date","ts_code","close","turnover_rate","turnover_rate_f","volume_ratio","total_mv","circ_mv"]),
        }
        mock_post.side_effect = self._mock_requests_post(responses)

        from scripts.zt_pipeline import score_fundflow
        score, reason = score_fundflow("600000.SH")
        self.assertEqual(score, 0)
        self.assertIn("否决", reason)


class TestFundflowDimensions(TestFundflowScoreV1):
    """五维度评分逻辑测试"""

    @patch('scripts.zt_pipeline.requests.post')
    def test_strong_main_inflow(self, mock_post):
        """测试维度1: 强主力流入 → 高分"""
        # 超大单买入=5000, 卖出=1000, 大单买入=3000, 卖出=500 → 主力净=6500
        # 流通市值=100000万, 6500/100000=6.5% → +15分
        # 主力占比 = 6500/9500 = 68.4% → +10分
        # 连续3日净流入 → +10分
        moneyflow_items = self._build_moneyflow_items(5000, 1000, 3000, 500, 6500, days=3)
        daily_items = self._build_daily_basic_items(circ_mv=100000, turnover_rate=8)

        responses = {
            "moneyflow": _build_tushare_response(moneyflow_items,
                ["trade_date","buy_elg_vol","buy_elg_amount","sell_elg_vol","sell_elg_amount",
                 "buy_lg_vol","buy_lg_amount","sell_lg_vol","sell_lg_amount","net_mf_vol","net_mf_amount"]),
            "daily_basic": _build_tushare_response(daily_items,
                ["trade_date","ts_code","close","turnover_rate","turnover_rate_f","volume_ratio","total_mv","circ_mv"]),
        }
        mock_post.side_effect = self._mock_requests_post(responses)

        from scripts.zt_pipeline import score_fundflow
        score, reason = score_fundflow("600000.SH")
        # 维度1应得35分(15+10+10)，维度4有净流入+10和换手+6=16分，维度5有锁仓+5
        self.assertGreaterEqual(score, 35, f"强主力流入应得高分，实际{score}, 原因: {reason}")
        self.assertIn("[主力", reason)

    @patch('scripts.zt_pipeline.requests.post')
    def test_dragon_tiger_bullish(self, mock_post):
        """测试维度2: 龙虎榜机构游资看多"""
        moneyflow_items = self._build_moneyflow_items(2000, 1000, 3000, 2000, 2000, days=3)
        daily_items = self._build_daily_basic_items(circ_mv=100000, turnover_rate=8)
        top_inst_items = self._build_top_inst_items(inst_buy=5000, hot_money_buy=3000)
        top_list_items = self._build_top_list_items(net_rate=15.0)

        responses = {
            "moneyflow": _build_tushare_response(moneyflow_items,
                ["trade_date","buy_elg_vol","buy_elg_amount","sell_elg_vol","sell_elg_amount",
                 "buy_lg_vol","buy_lg_amount","sell_lg_vol","sell_lg_amount","net_mf_vol","net_mf_amount"]),
            "daily_basic": _build_tushare_response(daily_items,
                ["trade_date","ts_code","close","turnover_rate","turnover_rate_f","volume_ratio","total_mv","circ_mv"]),
            "top_inst": _build_tushare_response(top_inst_items,
                ["trade_date","ts_code","exalter","side","buy","buy_rate","sell","sell_rate","net_buy","reason"]),
            "top_list": _build_tushare_response(top_list_items,
                ["trade_date","ts_code","name","close","pct_change","turnover_rate","amount","l_sell","l_buy","l_amount","net_amount","net_rate"]),
        }
        mock_post.side_effect = self._mock_requests_post(responses)

        from scripts.zt_pipeline import score_fundflow
        score, reason = score_fundflow("600000.SH")
        # 维度2: 8000>3000 → +12, 席位主导 → +8, 龙虎榜净买率>0 → +5 = 25分
        self.assertIn("[龙虎", reason)
        self.assertGreaterEqual(score, 25)

    @patch('scripts.zt_pipeline.requests.post')
    def test_northbound_holding_increase(self, mock_post):
        """测试维度3: 北向增持"""
        moneyflow_items = self._build_moneyflow_items(2000, 1000, 3000, 2000, 2000, days=3)
        daily_items = self._build_daily_basic_items(circ_mv=100000, turnover_rate=8)
        # 5日前持股5000万，今日持股6000万 → 增持20%
        hk_hold_items = self._build_hk_hold_items(
            vol_today=6000, vol_5d_ago=5000, ratio_today=2.0, ratio_prev=1.5)

        responses = {
            "moneyflow": _build_tushare_response(moneyflow_items,
                ["trade_date","buy_elg_vol","buy_elg_amount","sell_elg_vol","sell_elg_amount",
                 "buy_lg_vol","buy_lg_amount","sell_lg_vol","sell_lg_amount","net_mf_vol","net_mf_amount"]),
            "daily_basic": _build_tushare_response(daily_items,
                ["trade_date","ts_code","close","turnover_rate","turnover_rate_f","volume_ratio","total_mv","circ_mv"]),
            "hk_hold": _build_tushare_response(hk_hold_items,
                ["trade_date","ts_code","name","vol","ratio","exchange"]),
        }
        mock_post.side_effect = self._mock_requests_post(responses)

        from scripts.zt_pipeline import score_fundflow
        score, reason = score_fundflow("600000.SH")
        self.assertIn("[北向", reason)
        self.assertGreaterEqual(score, 6)  # 至少6分（持续增持）

    @patch('scripts.zt_pipeline.requests.post')
    def test_intraday_net_inflow(self, mock_post):
        """测试维度4: 净流入+换手率健康"""
        moneyflow_items = self._build_moneyflow_items(2000, 1000, 3000, 2000, 2000, days=3)
        daily_items = self._build_daily_basic_items(circ_mv=100000, turnover_rate=6)

        responses = {
            "moneyflow": _build_tushare_response(moneyflow_items,
                ["trade_date","buy_elg_vol","buy_elg_amount","sell_elg_vol","sell_elg_amount",
                 "buy_lg_vol","buy_lg_amount","sell_lg_vol","sell_lg_amount","net_mf_vol","net_mf_amount"]),
            "daily_basic": _build_tushare_response(daily_items,
                ["trade_date","ts_code","close","turnover_rate","turnover_rate_f","volume_ratio","total_mv","circ_mv"]),
        }
        mock_post.side_effect = self._mock_requests_post(responses)

        from scripts.zt_pipeline import score_fundflow
        score, reason = score_fundflow("600000.SH")
        self.assertIn("[盘口", reason)
        # 净流入+10, 换手6%(3-10区间)+6 = 16分
        self.assertGreaterEqual(score, 16)

    @patch('scripts.zt_pipeline.requests.post')
    def test_lockup_high(self, mock_post):
        """测试维度5: 锁仓度高"""
        # 连续3日净流入递增 → 锁仓+5
        # 无大幅流出 → 抛压可控+3
        moneyflow_items = [
            ["20260516", 1000, 3000, 800, 1000, 2000, 2000, 1500, 1500, 3000, 3000],
            ["20260515", 1000, 2500, 800, 1200, 2000, 1800, 1500, 1600, 3000, 2000],
            ["20260514", 1000, 2000, 800, 1500, 2000, 1500, 1500, 1800, 3000, 1000],
        ]
        daily_items = self._build_daily_basic_items(circ_mv=100000, turnover_rate=8)

        responses = {
            "moneyflow": _build_tushare_response(moneyflow_items,
                ["trade_date","buy_elg_vol","buy_elg_amount","sell_elg_vol","sell_elg_amount",
                 "buy_lg_vol","buy_lg_amount","sell_lg_vol","sell_lg_amount","net_mf_vol","net_mf_amount"]),
            "daily_basic": _build_tushare_response(daily_items,
                ["trade_date","ts_code","close","turnover_rate","turnover_rate_f","volume_ratio","total_mv","circ_mv"]),
        }
        mock_post.side_effect = self._mock_requests_post(responses)

        from scripts.zt_pipeline import score_fundflow
        score, reason = score_fundflow("600000.SH")
        self.assertIn("[锁仓", reason)

    @patch('scripts.zt_pipeline.requests.post')
    def test_no_data_returns_zero(self, mock_post):
        """测试无数据场景: 所有API返回空"""
        responses = {
            "moneyflow": _build_tushare_response([]),
            "top_list": _build_tushare_response([]),
            "top_inst": _build_tushare_response([]),
            "hk_hold": _build_tushare_response([]),
            "daily_basic": _build_tushare_response([]),
        }
        mock_post.side_effect = self._mock_requests_post(responses)

        from scripts.zt_pipeline import score_fundflow
        score, reason = score_fundflow("600000.SH")
        # 无数据不触发否决，但各维度得0分
        self.assertEqual(score, 0)
        self.assertIn("无", reason)

    @patch('scripts.zt_pipeline.requests.post')
    def test_retail_trap_detected(self, mock_post):
        """测试散户接盘: 主力流出但总净流入为正"""
        # 超大单买=500,卖=1000(净-500) 大单买=800,卖=1000(净-200) → 主力净=-700
        # 但总净流入=500(中小单在流入) → 散户接盘
        # 主力净占比=-700/3300=-21.2%, 超大单占比=1500/3300=45.5% > 5%, 不触发否决
        # 修改为超大单占比<5%: 超大单买=50,卖=100,大单买=800,卖=1000
        # 主力净占比 = -700/2350 = -29.8% < 10%, 超大单占比=150/2350=6.4% > 5%, 仍不触发
        # 需同时满足超大单占比<5%: 超大单买=40,卖=50(总量90), 大单买=800,卖=1000
        moneyflow_items = [
            ["20260516", 100, 40, 100, 50, 200, 800, 100, 1000, 300, 500]
        ]
        daily_items = self._build_daily_basic_items(circ_mv=100000, turnover_rate=8)

        responses = {
            "moneyflow": _build_tushare_response(moneyflow_items,
                ["trade_date","buy_elg_vol","buy_elg_amount","sell_elg_vol","sell_elg_amount",
                 "buy_lg_vol","buy_lg_amount","sell_lg_vol","sell_lg_amount","net_mf_vol","net_mf_amount"]),
            "daily_basic": _build_tushare_response(daily_items,
                ["trade_date","ts_code","close","turnover_rate","turnover_rate_f","volume_ratio","total_mv","circ_mv"]),
        }
        mock_post.side_effect = self._mock_requests_post(responses)

        from scripts.zt_pipeline import score_fundflow
        score, reason = score_fundflow("600000.SH")
        # 主力净占比 = -700/3300 = -21.2% < 10% → 触发否决
        self.assertEqual(score, 0)


if __name__ == '__main__':
    unittest.main()
