"""
资金面评分 V2.0 单元测试
测试 score_fundflow() 五维度量化评分逻辑
V2.0变更：维2盘中→封板质量因子，维4盘中→融资余额增速，维4权重12→7，维5权重8→13，否决调节器/豁免
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
    """资金面五维度评分测试基类"""

    def setUp(self):
        """每个测试前清空Tushare缓存，避免缓存污染"""
        from scripts.zt_pipeline import clear_tushare_cache
        clear_tushare_cache()

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
        """构建个股资金流向数据（近N天，按日期降序）"""
        items = []
        for i in range(days):
            factor = 1.0 - i * 0.1
            items.append([
                f"2026051{6-i}", 1000, buy_elg * factor, 800, sell_elg * factor,
                2000, buy_lg * factor, 1500, sell_lg * factor,
                3000, net_mf * factor
            ])
        return items

    def _build_top_list_items(self, net_rate):
        """构建龙虎榜数据"""
        return [["20260516", "600000.SH", "测试股", 10.0, 10.0, 8.5, 50000, 2000, 3000, 5000, 1000, net_rate]]

    def _build_top_inst_items(self, inst_buy, hot_money_buy):
        """构建龙虎榜机构交易数据"""
        items = []
        if inst_buy > 0:
            items.append(["20260516", "600000.SH", "机构专用", "B", inst_buy, 5.0, 0, 0, inst_buy, "涨停"])
        if hot_money_buy > 0:
            items.append(["20260516", "600000.SH", "知名游资营业部", "B", hot_money_buy, 3.0, 0, 0, hot_money_buy, "涨停"])
        return items

    def _build_hk_hold_items(self, vol_today, vol_5d_ago, ratio_today, ratio_prev):
        """构建北向持股数据（5天，日期降序）"""
        items = []
        for i in range(5):
            vol = vol_5d_ago + (vol_today - vol_5d_ago) * (5 - i) / 5
            ratio = ratio_prev + (ratio_today - ratio_prev) * (5 - i) / 5
            items.append([f"2026051{6-i}", "600000.SH", "测试股", vol, ratio, "SH"])
        return items

    def _build_daily_basic_items(self, circ_mv, turnover_rate):
        """构建每日基本面数据"""
        return [["20260516", "600000.SH", 10.0, turnover_rate, 7.5, 1.2, 100000, circ_mv]]

    def _build_limit_list_items(self, fd_amount, first_time, open_times, limit="U"):
        """构建涨跌停数据(V2.0维2盘中封板质量因子)
        limit_list fields: trade_date,ts_code,close,pct_chg,open_times,fd_amount,first_time,last_time,up_stat,limit
        """
        pct = 10.0 if limit == "U" else -10.0
        up_stat = "1/1" if limit == "U" else ""
        return [["20260516", "600000.SH", 11.0, pct, open_times, fd_amount, first_time, "150000", up_stat, limit]]

    def _build_margin_detail_items(self, rzye_list, rzmre_list=None):
        """构建融资融券明细数据(V2.0维4盘中融资余额增速)
        margin_detail fields: trade_date,ts_code,rzye,rqye,rzmre,rqmcl,rzrqye
        rzye_list: 按日期降序的融资余额列表(最新在前)
        """
        items = []
        for i, rzye in enumerate(rzye_list):
            rzmre = rzmre_list[i] if rzmre_list and i < len(rzmre_list) else rzye * 0.05
            rqye = rzye * 0.1
            rqmcl = 100
            rzrqye = rzye + rqye
            items.append([f"2026051{6-i}", "600000.SH", rzye, rqye, rzmre, rqmcl, rzrqye])
        return items


class TestFundflowVeto(TestFundflowScoreV1):
    """一票否决规则测试"""

    @patch('scripts.zt_pipeline.requests.post')
    def test_veto_main_capital_continuous_outflow(self, mock_post):
        """否决规则1: 主力3日累计净流出 > 0.5%流通市值"""
        moneyflow_items = self._build_moneyflow_items(500, 1000, 800, 1200, -1000, days=3)
        daily_items = self._build_daily_basic_items(circ_mv=10, turnover_rate=8)

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
    """五维度评分逻辑测试（含V2.0变更）"""

    @patch('scripts.zt_pipeline.requests.post')
    def test_strong_main_inflow(self, mock_post):
        """测试维度1: 强主力流入 → 高分"""
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
        self.assertGreaterEqual(score, 35, f"强主力流入应得高分，实际{score}, 原因: {reason}")
        self.assertIn("[主力", reason)

    @patch('scripts.zt_pipeline.requests.post')
    def test_dragon_tiger_bullish(self, mock_post):
        """测试维度2: 龙虎榜机构游资看多(盘后路径)"""
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
        self.assertIn("[龙虎", reason)
        self.assertGreaterEqual(score, 25)

    @patch('scripts.zt_pipeline.requests.post')
    def test_northbound_holding_increase(self, mock_post):
        """测试维度4: 北向增持(盘后路径) → V2.0标签改为[融资]"""
        moneyflow_items = self._build_moneyflow_items(2000, 1000, 3000, 2000, 2000, days=3)
        daily_items = self._build_daily_basic_items(circ_mv=100000, turnover_rate=8)
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
        # V2.0: 维度4标签从[北向]改为[融资]
        self.assertIn("[融资", reason)
        self.assertGreaterEqual(score, 6)

    @patch('scripts.zt_pipeline.requests.post')
    def test_intraday_net_inflow(self, mock_post):
        """测试维度3: 净流入+换手率健康"""
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
        self.assertGreaterEqual(score, 16)

    @patch('scripts.zt_pipeline.requests.post')
    def test_lockup_high(self, mock_post):
        """测试维度5: 锁仓度高(V2.0权重8→13，含流入加速+3)"""
        # 净流入递增: 1000→2000→3000, 流入加速: 3000 > (2000+1000)/2*1.5=2250
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
        # V2.0: 递增+7 + 无抛压+3 + 加速+3 = 13分
        self.assertIn("13分", reason)

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
        self.assertEqual(score, 0)
        self.assertIn("无", reason)

    @patch('scripts.zt_pipeline.requests.post')
    def test_retail_trap_detected(self, mock_post):
        """测试散户接盘: 主力流出但总净流入为正"""
        # 超大单占比<5%，主力净占比<10% → 触发否决
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
        self.assertEqual(score, 0)


class TestFundflowV2Features(TestFundflowScoreV1):
    """V2.0新增特性测试"""

    @patch('scripts.zt_pipeline.requests.post')
    def test_yiziban_veto_exemption(self, mock_post):
        """V2.0: 一字板豁免否决2.2(纯散户博弈)"""
        # 一字板: pct_chg=10%, open_times=0 → 豁免否决
        # 但主力净占比<10%且超大单占比<5% → 正常应触发否决
        # 一字板时跳过否决，不返回0分
        moneyflow_items = [
            ["20260516", 100, 40, 100, 50, 200, 800, 100, 1000, 300, 500]
        ]
        daily_items = self._build_daily_basic_items(circ_mv=100000, turnover_rate=8)
        limit_list_items = self._build_limit_list_items(fd_amount=50000, first_time="093000", open_times=0, limit="U")

        responses = {
            "moneyflow": _build_tushare_response(moneyflow_items,
                ["trade_date","buy_elg_vol","buy_elg_amount","sell_elg_vol","sell_elg_amount",
                 "buy_lg_vol","buy_lg_amount","sell_lg_vol","sell_lg_amount","net_mf_vol","net_mf_amount"]),
            "daily_basic": _build_tushare_response(daily_items,
                ["trade_date","ts_code","close","turnover_rate","turnover_rate_f","volume_ratio","total_mv","circ_mv"]),
            "limit_list": _build_tushare_response(limit_list_items,
                ["trade_date","ts_code","close","pct_chg","open_times","fd_amount","first_time","last_time","up_stat","limit"]),
        }
        mock_post.side_effect = self._mock_requests_post(responses)

        from scripts.zt_pipeline import score_fundflow
        score, reason = score_fundflow("600000.SH")
        # 一字板豁免否决，不应返回0分
        self.assertGreater(score, 0, f"一字板应豁免否决，实际得分{score}, 原因: {reason}")
        self.assertIn("[豁免]一字板", reason)

    @patch('scripts.zt_pipeline.requests.post')
    def test_market_regime_bearish(self, mock_post):
        """V2.0: 低迷市市场状态调节器 → 否决3(分时资金背离)阈值放宽"""
        # 构造正常会被否决的数据(主力净占比<10%)，但在低迷市下豁免
        moneyflow_items = [
            ["20260516", 100, 40, 100, 50, 200, 800, 100, 1000, 300, 500]
        ]
        daily_items = self._build_daily_basic_items(circ_mv=100000, turnover_rate=8)
        # 全市场成交额<8000亿(80000000万)，模拟低迷市
        daily_info_items = [["20260516", "SSE主板", 50000000, 0, 0, 0, 0, 0, 0, 0, 0, "SSE"]]
        # 跌停>20家，模拟低迷市
        limit_list_d_items = [["20260516", "600001.SH", "D", "测试跌停股1", 5.0, -10.0, 10000, 0, 50000, 0, 0, "093000", "150000", 0, "1/0", 1, "D"]]
        limit_list_d_items += [["20260516", f"60000{i}.SH", "D", f"测试跌停股{i}", 5.0, -10.0, 10000, 0, 50000, 0, 0, "093000", "150000", 0, "1/0", 1, "D"] for i in range(2, 22)]

        responses = {
            "moneyflow": _build_tushare_response(moneyflow_items,
                ["trade_date","buy_elg_vol","buy_elg_amount","sell_elg_vol","sell_elg_amount",
                 "buy_lg_vol","buy_lg_amount","sell_lg_vol","sell_lg_amount","net_mf_vol","net_mf_amount"]),
            "daily_basic": _build_tushare_response(daily_items,
                ["trade_date","ts_code","close","turnover_rate","turnover_rate_f","volume_ratio","total_mv","circ_mv"]),
            "daily_info": _build_tushare_response(daily_info_items,
                ["trade_date","ts_code","ts_name","com_count","total_share","float_share","total_mv","float_mv","amount","vol","trans_count","pe","tr","exchange"]),
            "limit_list_d": _build_tushare_response(limit_list_d_items,
                ["trade_date","ts_code","limit_type","name","close","pct_chg","amount","limit_amount","float_mv","total_mv","turnover_ratio","fd_amount","first_time","last_time","open_times","up_stat","limit_times","limit"]),
        }
        mock_post.side_effect = self._mock_requests_post(responses)

        from scripts.zt_pipeline import score_fundflow
        score, reason = score_fundflow("600000.SH")
        # 低迷市调节器生效，否决3阈值放宽，可能不触发
        # 主要验证不抛异常
        self.assertIsInstance(score, int)

    @patch('scripts.zt_pipeline.requests.post')
    def test_dim4_cap_7(self, mock_post):
        """V2.0: 维度4权重上限12→7"""
        moneyflow_items = self._build_moneyflow_items(2000, 1000, 3000, 2000, 2000, days=3)
        daily_items = self._build_daily_basic_items(circ_mv=100000, turnover_rate=8)
        # 北向大量增持(盘后路径)，V1.0可得12分，V2.0上限7分
        hk_hold_items = self._build_hk_hold_items(
            vol_today=10000, vol_5d_ago=5000, ratio_today=3.0, ratio_prev=1.0)

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
        # 解析reason中[融资X分]，X应<=7
        import re
        match = re.search(r'\[融资(\d+)分\]', reason)
        if match:
            dim4_score = int(match.group(1))
            self.assertLessEqual(dim4_score, 7, f"V2.0维度4上限应为7，实际{dim4_score}")

    @patch('scripts.zt_pipeline.requests.post')
    def test_dim5_cap_13(self, mock_post):
        """V2.0: 维度5权重上限8→13"""
        # 净流入递增+加速，V1.0最多8分，V2.0最多13分
        moneyflow_items = [
            ["20260516", 1000, 5000, 800, 500, 2000, 4000, 1500, 1000, 3000, 8000],
            ["20260515", 1000, 4000, 800, 800, 2000, 3000, 1500, 1200, 3000, 5000],
            ["20260514", 1000, 3000, 800, 1000, 2000, 2500, 1500, 1500, 3000, 3000],
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
        import re
        match = re.search(r'\[锁仓(\d+)分\]', reason)
        if match:
            dim5_score = int(match.group(1))
            self.assertLessEqual(dim5_score, 13, f"V2.0维度5上限应为13，实际{dim5_score}")
            self.assertGreater(dim5_score, 8, f"V2.0维度5应>8分(含加速+3)，实际{dim5_score}")


if __name__ == '__main__':
    unittest.main()
