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
        from scripts.zt_pipeline import score_sentiment

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
        """一票否决：主线崩塌（概念涨停数<2）"""
        from scripts.zt_pipeline import score_sentiment

        limit_fields = ["trade_date", "ts_code", "name", "close", "pct_change", "limit", "limit_times", "up_stat"]
        step_fields = ["trade_date", "ts_code", "name", "nums"]
        cpt_fields = ["ts_code", "name", "trade_date", "days", "up_stat", "cons_nums", "up_nums", "pct_chg", "rank"]

        responses = {
            "concept_detail": _build_tushare_response(
                self._build_concept_items(["机器人", "AI"]),
                ["id", "concept_name"]
            ),
            "limit_list_d": _build_tushare_response(
                self._build_limit_items(25, 2),  # 涨停数正常
                limit_fields
            ),
            "limit_step": _build_tushare_response(
                self._build_step_items([3, 2]),
                step_fields
            ),
            "top_list": _build_tushare_response([], []),
            "top_inst": _build_tushare_response([], []),
            "limit_cpt_list": _build_tushare_response(
                self._build_cpt_items([("机器人", 1), ("AI", 0)]),  # 概念涨停仅1只
                cpt_fields
            ),
        }
        mock_post.side_effect = self._mock_requests_post(responses)

        score, reason = score_sentiment("600000.SH")
        self.assertEqual(score, 0)
        self.assertIn("主线崩塌", reason)

    @patch('requests.post')
    def test_veto_hot_money_exit(self, mock_post):
        """一票否决：游资出逃（龙虎榜净卖出>3000万）"""
        from scripts.zt_pipeline import score_sentiment

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
        from scripts.zt_pipeline import score_sentiment

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
        from scripts.zt_pipeline import score_sentiment

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
        from scripts.zt_pipeline import score_sentiment

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
        from scripts.zt_pipeline import score_sentiment

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
        from scripts.zt_pipeline import score_sentiment

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
        """集合竞价：高开5-8% + 高关注度 + 高量比"""
        from scripts.zt_pipeline import score_sentiment

        limit_fields = ["trade_date", "ts_code", "name", "close", "pct_change", "limit", "limit_times", "up_stat"]
        step_fields = ["trade_date", "ts_code", "name", "nums"]
        auction_fields = ["ts_code", "trade_date", "vol", "price", "amount", "pre_close", "turnover_rate", "volume_ratio", "float_share"]

        # 使用今天的日期，因为代码中 today_str = datetime.now().strftime('%Y%m%d')
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
                [["600000.SH", today_str, 1000000000, 10.5, 5000000, 10.0, 0.05, 8.0, 20000000]],
                auction_fields
            ),
        }
        mock_post.side_effect = self._mock_requests_post(responses)

        score, reason = score_sentiment("600000.SH")
        # vol=1亿, float=2000万 → call_vol_ratio = 1000000000/20000000*100 = 5000%
        # OpenGap = (10.5-10)/10*100 = 5% → +5分
        # CallVolRatio=5000% → +5分
        # 量比8.0 → +3分
        # 金额500万 → +2分
        # 总分应包含集合竞价15分，原5维度约30分 → 约45分
        self.assertGreaterEqual(score, 40)  # 包含集合竞价15分
        self.assertIn("竞价高开5.0%+5", reason)
        # reason只取前5个，竞价关注度可能被截断，不检查

    @patch('requests.post')
    def test_auction_weak_open(self, mock_post):
        """集合竞价：低开>3% 扣分"""
        from scripts.zt_pipeline import score_sentiment

        limit_fields = ["trade_date", "ts_code", "name", "close", "pct_change", "limit", "limit_times", "up_stat"]
        step_fields = ["trade_date", "ts_code", "name", "nums"]
        auction_fields = ["ts_code", "trade_date", "vol", "price", "amount", "pre_close", "turnover_rate", "volume_ratio", "float_share"]

        # 使用今天的日期
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
        }
        mock_post.side_effect = self._mock_requests_post(responses)

        score, reason = score_sentiment("600000.SH")
        # OpenGap = (9.5-10)/10*100 = -5% → -4分
        self.assertIn("竞价低开-5.0%-4", reason)

    @patch('requests.post')
    def test_auction_no_data(self, mock_post):
        """集合竞价：无数据时不影响评分"""
        from scripts.zt_pipeline import score_sentiment

        limit_fields = ["trade_date", "ts_code", "name", "close", "pct_change", "limit", "limit_times", "up_stat"]
        step_fields = ["trade_date", "ts_code", "name", "nums"]

        # 使用今天的日期
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
        }
        mock_post.side_effect = self._mock_requests_post(responses)

        score, reason = score_sentiment("600000.SH")
        # 不应包含竞价相关reason
        self.assertNotIn("竞价", reason)
        self.assertGreaterEqual(score, 0)

    @patch('requests.post')
    def test_rating_levels(self, mock_post):
        """评级映射：高中低无"""
        from scripts.zt_pipeline import score_sentiment

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
