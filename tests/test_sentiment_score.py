"""
情绪面评分 V1.0 单元测试
测试 score_sentiment() 五维度量化评分逻辑
"""
import sys
import os
import unittest
from unittest.mock import patch, MagicMock, call

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


class TestSentimentScoreV1(unittest.TestCase):
    """情绪面五维度评分测试"""

    def setUp(self):
        """每个测试前清空Tushare缓存，避免缓存污染"""
        from plays.limit_up.pipeline import clear_tushare_cache
        clear_tushare_cache()

    def _mock_requests_post(self, responses_map):
        """
        创建mock，根据api_name返回不同响应
        responses_map支持两种格式：
          1. {api_name: response_dict} — 按api_name匹配（原有方式）
          2. {api_name: callable} — callable(json_data)返回response_dict，可按params区分
        V1.2新增：daily_info被调用3次(SSE/SZSE/历史)，需按params区分返回不同数据
        """
        def _post(url, **kwargs):
            json_data = kwargs.get("json", {})
            api_name = json_data.get("api_name", "")
            entry = responses_map.get(api_name, _build_tushare_response([]))
            # 如果entry是callable，调用它获取响应（用于按参数区分同一api_name的不同调用）
            if callable(entry):
                response_data = entry(json_data)
            else:
                response_data = entry
            mock_resp = MagicMock()
            mock_resp.json.return_value = response_data
            return mock_resp
        return _post

    def _build_limit_items(self, up_count, down_count):
        """构建涨停跌停数据 - 返回list格式（匹配limit_fields顺序）
        limit_fields = ["trade_date", "ts_code", "name", "close", "pct_change", "limit", "limit_times", "up_stat"]
        """
        items = []
        # 涨停股
        for i in range(up_count):
            items.append(["20260516", f"60{i:04d}.SH", f"涨停股{i}", 10.0 + i * 0.1, 10.0, "U", 1, "1/1"])
        # 跌停股
        for i in range(down_count):
            items.append(["20260516", f"00{i:04d}.SZ", f"跌停股{i}", 5.0 - i * 0.1, -10.0, "D", 1, "0/0"])
        return items

    def _build_step_items(self, heights):
        """构建连板天梯数据 - list格式
        step_fields = ["trade_date", "ts_code", "name", "nums"]
        """
        items = []
        for i, h in enumerate(heights):
            items.append(["20260516", f"60{i:04d}.SH", f"连板股{i}", h])
        return items

    def _build_concept_items(self, names):
        """构建概念板块数据 - list格式
        fields = ["id", "concept_name"]
        """
        return [[i, name] for i, name in enumerate(names)]

    def _build_top_list_items(self, net_rates):
        """构建龙虎榜数据 - list格式
        fields = ["trade_date", "ts_code", "name", "close", "pct_change", "turnover_rate", "amount", "l_sell", "l_buy", "l_amount", "net_amount", "net_rate"]
        """
        items = []
        for i, nr in enumerate(net_rates):
            items.append(["20260516", "600000.SH", "测试股", 10.0, 5.0, 15.0, 1000000, 500000, 800000, 1300000, 300000, nr])
        return items

    def _build_daily_basic_item(self, turnover_rate):
        """构建每日基础指标 - list格式
        fields = ["turnover_rate"]
        """
        return [[turnover_rate]]

    def _build_cpt_items(self, concept_ul_counts):
        """构建涨停板块统计数据 - list格式
        fields = ["ts_code", "name", "trade_date", "days", "up_stat", "cons_nums", "up_nums", "pct_chg", "rank"]
        concept_ul_counts: [(概念名, 涨停数), ...]
        """
        items = []
        for i, (name, cnt) in enumerate(concept_ul_counts):
            items.append([f"CON{i:04d}.DC", name, "20260516", 1, "1/1", cnt, cnt, 5.0, i + 1])
        return items

    # ===== 测试用例 =====

    @patch('requests.post')
    def test_veto_market_downturn(self, mock_post):
        """一票否决：市场退潮（涨停<15家）"""
        from plays.limit_up.pipeline import score_sentiment

        limit_fields = ["trade_date", "ts_code", "name", "close", "pct_change", "limit", "limit_times", "up_stat"]
        step_fields = ["trade_date", "ts_code", "name", "nums"]
        cpt_fields = ["ts_code", "name", "trade_date", "days", "up_stat", "cons_nums", "up_nums", "pct_chg", "rank"]

        responses = {
            "concept_detail": _build_tushare_response(
                self._build_concept_items(["机器人"]),
                ["id", "concept_name"]
            ),
            "limit_list_d": _build_tushare_response(
                self._build_limit_items(10, 3),
                limit_fields
            ),
            "limit_step": _build_tushare_response(
                self._build_step_items([3, 2]),
                step_fields
            ),
            "top_list": _build_tushare_response([], []),
            "top_inst": _build_tushare_response([], []),
            "limit_cpt_list": _build_tushare_response(
                self._build_cpt_items([("机器人", 5)]),
                cpt_fields
            ),
        }
        mock_post.side_effect = self._mock_requests_post(responses)

        score, reason = score_sentiment("600000.SH")
        self.assertEqual(score, 0)
        self.assertIn("市场退潮", reason)

    @patch('requests.post')
    def test_veto_theme_collapse(self, mock_post):
        """一票否决：主线崩塌（概念涨停=0）+ 纯跟风（=1）"""
        from plays.limit_up.pipeline import score_sentiment

        limit_fields = ["trade_date", "ts_code", "name", "close", "pct_change", "limit", "limit_times", "up_stat"]
        step_fields = ["trade_date", "ts_code", "name", "nums"]
        cpt_fields = ["ts_code", "name", "trade_date", "days", "up_stat", "cons_nums", "up_nums", "pct_chg", "rank"]

        # 场景1: 概念涨停=0 → 主线崩塌
        responses_0 = {
            "concept_detail": _build_tushare_response(
                self._build_concept_items(["机器人", "AI"]),
                ["id", "concept_name"]
            ),
            "limit_list_d": _build_tushare_response(
                self._build_limit_items(25, 2),
                limit_fields
            ),
            "limit_step": _build_tushare_response(
                self._build_step_items([3, 2]),
                step_fields
            ),
            "top_list": _build_tushare_response([], []),
            "top_inst": _build_tushare_response([], []),
            "limit_cpt_list": _build_tushare_response(
                self._build_cpt_items([("机器人", 0), ("AI", 0)]),  # 全部概念0涨停→主线崩塌
                cpt_fields
            ),
        }
        mock_post.side_effect = self._mock_requests_post(responses_0)
        score, reason = score_sentiment("600000.SH")
        self.assertEqual(score, 0)
        self.assertIn("主线崩塌", reason)

        # 场景2: 概念涨停=1 → 纯跟风（非主线崩塌）
        from plays.limit_up.pipeline import clear_tushare_cache
        clear_tushare_cache()
        responses_1 = {
            "concept_detail": _build_tushare_response(
                self._build_concept_items(["机器人", "AI"]),
                ["id", "concept_name"]
            ),
            "limit_list_d": _build_tushare_response(
                self._build_limit_items(25, 2),
                limit_fields
            ),
            "limit_step": _build_tushare_response(
                self._build_step_items([3, 2]),
                step_fields
            ),
            "top_list": _build_tushare_response([], []),
            "top_inst": _build_tushare_response([], []),
            "limit_cpt_list": _build_tushare_response(
                self._build_cpt_items([("机器人", 1), ("AI", 0)]),  # 概念涨停仅1只→纯跟风
                cpt_fields
            ),
        }
        mock_post.side_effect = self._mock_requests_post(responses_1)
        score, reason = score_sentiment("600000.SH")
        self.assertEqual(score, 0)
        self.assertIn("纯跟风", reason)

    @patch('requests.post')
    def test_veto_hot_money_exit(self, mock_post):
        """一票否决：游资出逃（龙虎榜净卖出>3000万）"""
        from plays.limit_up.pipeline import score_sentiment

        limit_fields = ["trade_date", "ts_code", "name", "close", "pct_change", "limit", "limit_times", "up_stat"]
        step_fields = ["trade_date", "ts_code", "name", "nums"]
        top_list_fields = ["trade_date", "ts_code", "name", "close", "pct_change", "turnover_rate", "amount", "l_sell", "l_buy", "l_amount", "net_amount", "net_rate"]
        cpt_fields = ["ts_code", "name", "trade_date", "days", "up_stat", "cons_nums", "up_nums", "pct_chg", "rank"]

        responses = {
            "concept_detail": _build_tushare_response(
                self._build_concept_items(["机器人"]),
                ["id", "concept_name"]
            ),
            "limit_list_d": _build_tushare_response(
                self._build_limit_items(25, 2),
                limit_fields
            ),
            "limit_step": _build_tushare_response(
                self._build_step_items([3, 2]),
                step_fields
            ),
            "top_list": _build_tushare_response(
                [["20260516", "600000.SH", "测试股", 10.0, 5.0, 15.0, 1000000, 800000, 500000, 1300000, -3500, -3.5]],  # 净卖出3500万
                top_list_fields
            ),
            "top_inst": _build_tushare_response([], []),
            "limit_cpt_list": _build_tushare_response(
                self._build_cpt_items([("机器人", 5)]),
                cpt_fields
            ),
        }
        mock_post.side_effect = self._mock_requests_post(responses)

        score, reason = score_sentiment("600000.SH")
        self.assertEqual(score, 0)
        self.assertIn("游资出逃", reason)

    @patch('requests.post')
    def test_high_market_sentiment(self, mock_post):
        """大盘情绪高涨：涨停≥35、跌停<5、连板≥4"""
        from plays.limit_up.pipeline import score_sentiment

        limit_fields = ["trade_date", "ts_code", "name", "close", "pct_change", "limit", "limit_times", "up_stat"]
        step_fields = ["trade_date", "ts_code", "name", "nums"]
        top_list_fields = ["trade_date", "ts_code", "name", "close", "pct_change", "turnover_rate", "amount", "l_sell", "l_buy", "l_amount", "net_amount", "net_rate"]

        responses = {
            "concept_detail": _build_tushare_response(
                self._build_concept_items(["机器人", "人工智能", "芯片", "半导体", "算力", "低空", "华为", "新能源"]),
                ["id", "concept_name"]
            ),
            "limit_list_d": _build_tushare_response(
                self._build_limit_items(40, 2),
                limit_fields
            ),
            "limit_step": _build_tushare_response(
                self._build_step_items([5, 4, 4, 3, 3, 2]),
                step_fields
            ),
            "top_list": _build_tushare_response(
                self._build_top_list_items([5.0]),
                top_list_fields
            ),
            "top_inst": _build_tushare_response([], []),
            "daily_basic": _build_tushare_response(
                self._build_daily_basic_item(15.0),
                ["turnover_rate"]
            ),
        }
        mock_post.side_effect = self._mock_requests_post(responses)

        score, reason = score_sentiment("600000.SH")
        # 大盘：涨停40家+10，跌停2家+8，最高5板+7 = 25
        # 题材：8概念+8，热门3+10 = 18
        # 梯队：高板2只+4 = 4
        # 人气：换手15%+5，龙虎榜+3 = 8
        # 舆情：5概念+3 = 3
        # 总分约58，应该在中区间
        self.assertGreaterEqual(score, 50)
        self.assertIn("[", reason)

    @patch('requests.post')
    def test_theme_hot_keywords(self, mock_post):
        """主线题材：热门关键词匹配"""
        from plays.limit_up.pipeline import score_sentiment

        limit_fields = ["trade_date", "ts_code", "name", "close", "pct_change", "limit", "limit_times", "up_stat"]
        step_fields = ["trade_date", "ts_code", "name", "nums"]

        responses = {
            "concept_detail": _build_tushare_response(
                self._build_concept_items(["机器人", "人工智能", "新能源"]),
                ["id", "concept_name"]
            ),
            "limit_list_d": _build_tushare_response(
                self._build_limit_items(25, 2),
                limit_fields
            ),
            "limit_step": _build_tushare_response(
                self._build_step_items([3, 2]),
                step_fields
            ),
            "top_list": _build_tushare_response([], []),
            "top_inst": _build_tushare_response([], []),
        }
        mock_post.side_effect = self._mock_requests_post(responses)

        score, reason = score_sentiment("600000.SH")
        # 大盘：涨停25家+5，跌停2家+8，最高3板+5 = 18
        # 题材：3概念热门+5 = 5
        # 总分应>0
        self.assertGreater(score, 0)

    @patch('requests.post')
    def test_turnover_active(self, mock_post):
        """个股人气：换手率10%-25%活跃区间"""
        from plays.limit_up.pipeline import score_sentiment

        limit_fields = ["trade_date", "ts_code", "name", "close", "pct_change", "limit", "limit_times", "up_stat"]
        step_fields = ["trade_date", "ts_code", "name", "nums"]
        top_list_fields = ["trade_date", "ts_code", "name", "close", "pct_change", "turnover_rate", "amount", "l_sell", "l_buy", "l_amount", "net_amount", "net_rate"]

        responses = {
            "concept_detail": _build_tushare_response(
                self._build_concept_items(["消费"]),
                ["id", "concept_name"]
            ),
            "limit_list_d": _build_tushare_response(
                self._build_limit_items(25, 2),
                limit_fields
            ),
            "limit_step": _build_tushare_response(
                self._build_step_items([3]),
                step_fields
            ),
            "top_list": _build_tushare_response(
                self._build_top_list_items([3.0]),
                top_list_fields
            ),
            "top_inst": _build_tushare_response([], []),
            "daily_basic": _build_tushare_response(
                self._build_daily_basic_item(18.5),
                ["turnover_rate"]
            ),
        }
        mock_post.side_effect = self._mock_requests_post(responses)

        score, reason = score_sentiment("600000.SH")
        self.assertIn("换手18.5%情绪活跃+2", reason)

    @patch('requests.post')
    def test_turnover_overheat(self, mock_post):
        """个股人气：换手率>25%过热扣分"""
        from plays.limit_up.pipeline import score_sentiment

        limit_fields = ["trade_date", "ts_code", "name", "close", "pct_change", "limit", "limit_times", "up_stat"]
        step_fields = ["trade_date", "ts_code", "name", "nums"]

        responses = {
            "concept_detail": _build_tushare_response(
                self._build_concept_items(["消费"]),
                ["id", "concept_name"]
            ),
            "limit_list_d": _build_tushare_response(
                self._build_limit_items(25, 2),
                limit_fields
            ),
            "limit_step": _build_tushare_response(
                self._build_step_items([3]),
                step_fields
            ),
            "top_list": _build_tushare_response([], []),
            "top_inst": _build_tushare_response([], []),
            "daily_basic": _build_tushare_response(
                self._build_daily_basic_item(30.0),
                ["turnover_rate"]
            ),
        }
        mock_post.side_effect = self._mock_requests_post(responses)

        score, reason = score_sentiment("600000.SH")
        self.assertIn("过热-2", reason)

    @patch('requests.post')
    def test_dragon_tiger_net_buy(self, mock_post):
        """个股人气：龙虎榜净买入加分"""
        from plays.limit_up.pipeline import score_sentiment

        limit_fields = ["trade_date", "ts_code", "name", "close", "pct_change", "limit", "limit_times", "up_stat"]
        step_fields = ["trade_date", "ts_code", "name", "nums"]
        top_list_fields = ["trade_date", "ts_code", "name", "close", "pct_change", "turnover_rate", "amount", "l_sell", "l_buy", "l_amount", "net_amount", "net_rate"]

        responses = {
            "concept_detail": _build_tushare_response(
                self._build_concept_items(["医药"]),
                ["id", "concept_name"]
            ),
            "limit_list_d": _build_tushare_response(
                self._build_limit_items(25, 2),
                limit_fields
            ),
            "limit_step": _build_tushare_response(
                self._build_step_items([3]),
                step_fields
            ),
            "top_list": _build_tushare_response(
                self._build_top_list_items([8.5, 3.2]),
                top_list_fields
            ),
            "top_inst": _build_tushare_response([], []),
        }
        mock_post.side_effect = self._mock_requests_post(responses)

        score, reason = score_sentiment("600000.SH")
        self.assertIn("龙虎榜", reason)

    @patch('requests.post')
    def test_auction_strong_open(self, mock_post):
        """集合竞价：高开5-8% + 高关注度(CallVolRatio量纲修正V1.2) + 高量比"""
        from plays.limit_up.pipeline import score_sentiment

        limit_fields = ["trade_date", "ts_code", "name", "close", "pct_change", "limit", "limit_times", "up_stat"]
        step_fields = ["trade_date", "ts_code", "name", "nums"]
        auction_fields = ["ts_code", "trade_date", "vol", "price", "amount", "pre_close", "turnover_rate", "volume_ratio", "float_share"]

        from datetime import datetime
        today_str = datetime.now().strftime('%Y%m%d')

        # CallVolRatio量纲修正(V1.2)：vol/yesterday_vol
        # vol=1亿(100000000), yesterday_vol=30000000(3000万) → ratio=3.33 ≥ 3.0 → +5分
        responses = {
            "concept_detail": _build_tushare_response(
                self._build_concept_items(["机器人"]),
                ["id", "concept_name"]
            ),
            "limit_list_d": _build_tushare_response(
                self._build_limit_items(25, 2),
                limit_fields
            ),
            "limit_step": _build_tushare_response(
                self._build_step_items([3]),
                step_fields
            ),
            "top_list": _build_tushare_response([], []),
            "top_inst": _build_tushare_response([], []),
            "stk_auction": _build_tushare_response(
                [["600000.SH", today_str, 100000000, 10.5, 5000000, 10.0, 0.05, 8.0, 20000000]],
                auction_fields
            ),
            # V1.2新增：昨日成交量mock
            "daily": _build_tushare_response(
                [["20260515", 30000000]],  # 昨日成交量3000万
                ["trade_date", "vol"]
            ),
            # V1.2新增：市场状态mock（默认震荡态）
            "daily_info": _build_tushare_response(
                [[today_str, "SSE", 2000, 500000000000]],
                ["trade_date", "ts_code", "com_count", "amount"]
            ),
            "limit_cpt_list": _build_tushare_response(
                self._build_cpt_items([("机器人", 3)]),
                ["ts_code", "name", "trade_date", "days", "up_stat", "cons_nums", "up_nums", "pct_chg", "rank"]
            ),
        }
        mock_post.side_effect = self._mock_requests_post(responses)

        score, reason = score_sentiment("600000.SH")
        # OpenGap = (10.5-10)/10*100 = 5% → 震荡态基础+5 × 1.0 = 5分
        # CallVolRatio = vol/yesterday_vol = 100000000/30000000 = 3.33 ≥ 3.0 → +5分
        # 量比8.0 → +3分
        # 金额500万 → +2分
        self.assertGreaterEqual(score, 40)
        # V1.2：reason格式变更为"竞价跳空5.0%[震荡态×1.0]→5分"
        self.assertIn("竞价跳空", reason)

    @patch('requests.post')
    def test_auction_weak_open(self, mock_post):
        """集合竞价：低开>3% 扣分（V1.2含市场状态乘数）"""
        from plays.limit_up.pipeline import score_sentiment

        limit_fields = ["trade_date", "ts_code", "name", "close", "pct_change", "limit", "limit_times", "up_stat"]
        step_fields = ["trade_date", "ts_code", "name", "nums"]
        auction_fields = ["ts_code", "trade_date", "vol", "price", "amount", "pre_close", "turnover_rate", "volume_ratio", "float_share"]

        from datetime import datetime
        today_str = datetime.now().strftime('%Y%m%d')

        responses = {
            "concept_detail": _build_tushare_response(
                self._build_concept_items(["机器人"]),
                ["id", "concept_name"]
            ),
            "limit_list_d": _build_tushare_response(
                self._build_limit_items(25, 2),
                limit_fields
            ),
            "limit_step": _build_tushare_response(
                self._build_step_items([3]),
                step_fields
            ),
            "top_list": _build_tushare_response([], []),
            "top_inst": _build_tushare_response([], []),
            "stk_auction": _build_tushare_response(
                [["600000.SH", today_str, 500000, 9.5, 2000000, 10.0, 0.02, 2.0, 20000000]],
                auction_fields
            ),
            # V1.2新增mock
            "daily": _build_tushare_response(
                [["20260515", 30000000]],
                ["trade_date", "vol"]
            ),
            "daily_info": _build_tushare_response(
                [[today_str, "SSE", 2000, 500000000000]],
                ["trade_date", "ts_code", "com_count", "amount"]
            ),
            "limit_cpt_list": _build_tushare_response(
                self._build_cpt_items([("机器人", 3)]),
                ["ts_code", "name", "trade_date", "days", "up_stat", "cons_nums", "up_nums", "pct_chg", "rank"]
            ),
        }
        mock_post.side_effect = self._mock_requests_post(responses)

        score, reason = score_sentiment("600000.SH")
        # V1.2：低开reason格式变更为"竞价跳空-5.0%[震荡态×1.0]→0分"（截断后为0）
        # 低开扣分被截断规则max(0, min(5, score))变为0分
        self.assertIn("竞价跳空", reason)

    @patch('requests.post')
    def test_auction_no_data(self, mock_post):
        """集合竞价：无数据时不影响评分"""
        from plays.limit_up.pipeline import score_sentiment

        limit_fields = ["trade_date", "ts_code", "name", "close", "pct_change", "limit", "limit_times", "up_stat"]
        step_fields = ["trade_date", "ts_code", "name", "nums"]

        from datetime import datetime
        today_str = datetime.now().strftime('%Y%m%d')

        responses = {
            "concept_detail": _build_tushare_response(
                self._build_concept_items(["机器人"]),
                ["id", "concept_name"]
            ),
            "limit_list_d": _build_tushare_response(
                self._build_limit_items(25, 2),
                limit_fields
            ),
            "limit_step": _build_tushare_response(
                self._build_step_items([3]),
                step_fields
            ),
            "top_list": _build_tushare_response([], []),
            "top_inst": _build_tushare_response([], []),
            "stk_auction": _build_tushare_response([], []),  # 无数据
            # V1.2新增mock
            "daily": _build_tushare_response([], []),
            "daily_info": _build_tushare_response([], []),
        }
        mock_post.side_effect = self._mock_requests_post(responses)

        score, reason = score_sentiment("600000.SH")
        # 不应包含竞价相关reason
        self.assertNotIn("竞价", reason)
        self.assertGreaterEqual(score, 0)

    @patch('requests.post')
    def test_auction_bull_market_multiplier(self, mock_post):
        """V1.2新增：牛市态下高开加分被放大×1.3"""
        from plays.limit_up.pipeline import score_sentiment

        limit_fields = ["trade_date", "ts_code", "name", "close", "pct_change", "limit", "limit_times", "up_stat"]
        step_fields = ["trade_date", "ts_code", "name", "nums"]
        auction_fields = ["ts_code", "trade_date", "vol", "price", "amount", "pre_close", "turnover_rate", "volume_ratio", "float_share"]

        from datetime import datetime
        today_str = datetime.now().strftime('%Y%m%d')

        # 牛市态：涨跌比>2.5 且 成交额>20日均1.2倍
        # limit_data: 50涨停(U) + 2跌停(D) → 涨跌比=25 > 2.5
        # daily_info: SSE/SZSE当日成交额=8000亿，20日历史均额约5000亿 → ratio>1.2 → 牛市
        def _daily_info_handler(json_data):
            """V1.2：daily_info被调用3次，按params区分返回不同数据"""
            params = json_data.get("params", {})
            ts_code = params.get("ts_code", "")
            if ts_code == "SSE":
                return _build_tushare_response(
                    [[today_str, "SSE", 2000, 400000000000]],  # SSE当日4000亿
                    ["trade_date", "ts_code", "com_count", "amount"]
                )
            elif ts_code == "SZSE":
                return _build_tushare_response(
                    [[today_str, "SZSE", 3000, 400000000000]],  # SZSE当日4000亿
                    ["trade_date", "ts_code", "com_count", "amount"]
                )
            else:
                # 20日历史数据：每天约5000亿（SSE+SZSE合计）
                hist_items = [[f"202605{d:02d}", 500000000000] for d in range(1, 16)]
                return _build_tushare_response(
                    hist_items,
                    ["trade_date", "amount"]
                )

        responses = {
            "concept_detail": _build_tushare_response(
                self._build_concept_items(["机器人"]),
                ["id", "concept_name"]
            ),
            "limit_list_d": _build_tushare_response(
                self._build_limit_items(50, 2),  # 50涨停2跌停 → 涨跌比=25>2.5
                limit_fields
            ),
            "limit_step": _build_tushare_response(
                self._build_step_items([5]),
                step_fields
            ),
            "top_list": _build_tushare_response([], []),
            "top_inst": _build_tushare_response([], []),
            "stk_auction": _build_tushare_response(
                [["600000.SH", today_str, 100000000, 10.5, 5000000, 10.0, 0.05, 8.0, 20000000]],
                auction_fields
            ),
            "daily": _build_tushare_response(
                [["20260515", 30000000]],
                ["trade_date", "vol"]
            ),
            # V1.2：daily_info按参数动态返回
            "daily_info": _daily_info_handler,
            "limit_cpt_list": _build_tushare_response(
                self._build_cpt_items([("机器人", 5)]),
                ["ts_code", "name", "trade_date", "days", "up_stat", "cons_nums", "up_nums", "pct_chg", "rank"]
            ),
        }
        mock_post.side_effect = self._mock_requests_post(responses)

        score, reason = score_sentiment("600000.SH")
        # 牛市态：高开5%基础+5 × 1.3 = 6.5 → 截断后5分（max=5）
        # reason中应包含牛市态标记
        self.assertIn("牛市态", reason)
        self.assertGreaterEqual(score, 50)

    @patch('requests.post')
    def test_auction_bear_market_multiplier(self, mock_post):
        """V1.2新增：熊市态下高开加分缩小×0.6，低开扣分放大"""
        from plays.limit_up.pipeline import score_sentiment

        limit_fields = ["trade_date", "ts_code", "name", "close", "pct_change", "limit", "limit_times", "up_stat"]
        step_fields = ["trade_date", "ts_code", "name", "nums"]
        auction_fields = ["ts_code", "trade_date", "vol", "price", "amount", "pre_close", "turnover_rate", "volume_ratio", "float_share"]

        from datetime import datetime
        today_str = datetime.now().strftime('%Y%m%d')

        # 熊市态：涨跌比<0.8 或 成交额<20日均0.7倍
        # 需避免否决区：涨停>=15家，但涨跌比<0.8 → 15涨停+20跌停=0.75<0.8
        # daily_info: 当日成交额极低(3000亿)，20日历史约5000亿 → ratio=0.6<0.7 → 熊市
        def _daily_info_handler(json_data):
            params = json_data.get("params", {})
            ts_code = params.get("ts_code", "")
            if ts_code == "SSE":
                return _build_tushare_response(
                    [[today_str, "SSE", 2000, 150000000000]],  # SSE当日1500亿（极低）
                    ["trade_date", "ts_code", "com_count", "amount"]
                )
            elif ts_code == "SZSE":
                return _build_tushare_response(
                    [[today_str, "SZSE", 3000, 150000000000]],  # SZSE当日1500亿（极低）
                    ["trade_date", "ts_code", "com_count", "amount"]
                )
            else:
                # 20日历史数据：每天约5000亿
                hist_items = [[f"202605{d:02d}", 500000000000] for d in range(1, 16)]
                return _build_tushare_response(
                    hist_items,
                    ["trade_date", "amount"]
                )

        responses = {
            "concept_detail": _build_tushare_response(
                self._build_concept_items(["机器人"]),
                ["id", "concept_name"]
            ),
            "limit_list_d": _build_tushare_response(
                self._build_limit_items(15, 20),  # 15涨停20跌停 → 涨跌比=0.75<0.8 → 熊市，但>=15不触发否决
                limit_fields
            ),
            "limit_step": _build_tushare_response(
                self._build_step_items([2]),
                step_fields
            ),
            "top_list": _build_tushare_response([], []),
            "top_inst": _build_tushare_response([], []),
            "stk_auction": _build_tushare_response(
                [["600000.SH", today_str, 50000000, 10.3, 2000000, 10.0, 0.03, 3.0, 20000000]],
                auction_fields
            ),
            "daily": _build_tushare_response(
                [["20260515", 30000000]],
                ["trade_date", "vol"]
            ),
            # V1.2：daily_info按参数动态返回（熊市态：成交额极低）
            "daily_info": _daily_info_handler,
            "limit_cpt_list": _build_tushare_response(
                self._build_cpt_items([("机器人", 2)]),
                ["ts_code", "name", "trade_date", "days", "up_stat", "cons_nums", "up_nums", "pct_chg", "rank"]
            ),
        }
        mock_post.side_effect = self._mock_requests_post(responses)

        score, reason = score_sentiment("600000.SH")
        # 熊市态：高开3%基础+3 × 0.6 = 1.8 → round=2分（缩小加分）
        # reason中应包含熊市态标记
        # 15涨停+20跌停不会触发否决(<15家才否决)，涨跌比0.75<0.8触发熊市态
        self.assertIn("熊市态", reason)

    @patch('requests.post')
    def test_rating_levels(self, mock_post):
        """评级映射：高中低无"""
        from plays.limit_up.pipeline import score_sentiment

        limit_fields = ["trade_date", "ts_code", "name", "close", "pct_change", "limit", "limit_times", "up_stat"]
        step_fields = ["trade_date", "ts_code", "name", "nums"]
        top_list_fields = ["trade_date", "ts_code", "name", "close", "pct_change", "turnover_rate", "amount", "l_sell", "l_buy", "l_amount", "net_amount", "net_rate"]

        responses = {
            "concept_detail": _build_tushare_response(
                self._build_concept_items(["机器人", "AI", "人工智能", "芯片", "半导体", "算力", "低空", "华为"]),
                ["id", "concept_name"]
            ),
            "limit_list_d": _build_tushare_response(
                self._build_limit_items(45, 1),
                limit_fields
            ),
            "limit_step": _build_tushare_response(
                self._build_step_items([5, 4, 4, 3, 3]),
                step_fields
            ),
            "top_list": _build_tushare_response(
                self._build_top_list_items([6.0]),
                top_list_fields
            ),
            "top_inst": _build_tushare_response([], []),
            "daily_basic": _build_tushare_response(
                self._build_daily_basic_item(12.0),
                ["turnover_rate"]
            ),
        }
        mock_post.side_effect = self._mock_requests_post(responses)

        score, reason = score_sentiment("600000.SH")
        # 验证reason包含等级标记
        self.assertTrue(
            "[高]" in reason or "[中]" in reason or "[低]" in reason or "[无]" in reason,
            f"Reason should contain rating level, got: {reason}"
        )


if __name__ == '__main__':
    unittest.main()
