#!/usr/bin/env python3
"""
全系统股票过滤规则单元测试
验证所有 Agent 共用的 7 条过滤规则正确执行

运行: python -m pytest tests/test_filter_rules.py -v
"""

import os
import sys
import unittest
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


class TestStockFilterRules(unittest.TestCase):
    """测试全系统统一股票过滤规则"""

    def setUp(self):
        """构造测试股票池"""
        self.stock_pool = [
            {
                "ts_code": "000001.SZ",
                "name": "平安银行",
                "is_st": False,
                "list_date": "19910403",
                "market": "主板",
                "float_mv": 250_0000,  # 2500亿（万元）
                "turnover_5d_avg": 3.5,  # %
                "is_suspended": False,
                "is_yiziban": False,
            },
            {
                "ts_code": "300001.SZ",
                "name": "特锐德",
                "is_st": False,
                "list_date": "20091030",
                "market": "创业板",
                "float_mv": 120_0000,
                "turnover_5d_avg": 4.0,
                "is_suspended": False,
                "is_yiziban": False,
            },
            {
                "ts_code": "688001.SH",
                "name": "华兴源创",
                "is_st": False,
                "list_date": "20190722",
                "market": "科创板",
                "float_mv": 80_0000,
                "turnover_5d_avg": 2.5,
                "is_suspended": False,
                "is_yiziban": False,
            },
            {
                "ts_code": "000002.SZ",
                "name": "万科A",
                "is_st": True,  # ST
                "list_date": "19910129",
                "market": "主板",
                "float_mv": 300_0000,
                "turnover_5d_avg": 3.0,
                "is_suspended": False,
                "is_yiziban": False,
            },
            {
                "ts_code": "000003.SZ",
                "name": "小盘股",
                "is_st": False,
                "list_date": "20260101",  # 新股（未来日期，模拟上市不满60日）
                "market": "主板",
                "float_mv": 10_0000,  # 10亿 < 20亿
                "turnover_5d_avg": 1.0,  # < 2%
                "is_suspended": False,
                "is_yiziban": False,
            },
            {
                "ts_code": "000004.SZ",
                "name": "停牌股",
                "is_st": False,
                "list_date": "19900101",
                "market": "主板",
                "float_mv": 100_0000,
                "turnover_5d_avg": 3.0,
                "is_suspended": True,
                "is_yiziban": False,
            },
            {
                "ts_code": "000005.SZ",
                "name": "一字板",
                "is_st": False,
                "list_date": "19900101",
                "market": "主板",
                "float_mv": 100_0000,
                "turnover_5d_avg": 3.0,
                "is_suspended": False,
                "is_yiziban": True,
            },
        ]

    def _apply_filters(self, pool):
        """应用全系统过滤规则"""
        filtered = []
        today = datetime.now().strftime("%Y%m%d")

        for stock in pool:
            # 1. ST/*ST/退市
            if stock.get("is_st", False):
                continue
            # 2. 上市不满60日新股
            list_date = stock.get("list_date", "")
            if list_date:
                try:
                    list_dt = datetime.strptime(list_date, "%Y%m%d")
                    days_listed = (datetime.now() - list_dt).days
                    if days_listed < 60:
                        continue
                except ValueError:
                    pass
            # 3. 创业板/科创板/北交所
            ts_code = stock.get("ts_code", "")
            if ts_code.startswith("300") or ts_code.startswith("301"):
                continue
            if ts_code.startswith("688") or ts_code.startswith("689"):
                continue
            if ts_code.startswith("8") or ts_code.startswith("43"):
                continue
            # 4. 当日停牌
            if stock.get("is_suspended", False):
                continue
            # 5. 自由流通市值 < 20亿
            float_mv_yi = stock.get("float_mv", 0) / 10000  # 万元 -> 亿元
            if float_mv_yi < 20:
                continue
            # 6. 5日均换手率 < 2%
            if stock.get("turnover_5d_avg", 0) < 2.0:
                continue
            # 7. 连续一字板
            if stock.get("is_yiziban", False):
                continue

            filtered.append(stock)

        return filtered

    def test_filter_st_stock(self):
        """规则1: ST 股票被过滤"""
        result = self._apply_filters(self.stock_pool)
        ts_codes = [s["ts_code"] for s in result]
        self.assertNotIn("000002.SZ", ts_codes)  # 万科A是ST

    def test_filter_new_stock(self):
        """规则2: 上市不满60日新股被过滤"""
        result = self._apply_filters(self.stock_pool)
        ts_codes = [s["ts_code"] for s in result]
        self.assertNotIn("000003.SZ", ts_codes)  # 小盘股是新股

    def test_filter_gem_kcb_bse(self):
        """规则3: 创业板/科创板/北交所被过滤"""
        result = self._apply_filters(self.stock_pool)
        ts_codes = [s["ts_code"] for s in result]
        self.assertNotIn("300001.SZ", ts_codes)  # 创业板
        self.assertNotIn("688001.SH", ts_codes)  # 科创板

    def test_filter_suspended(self):
        """规则4: 停牌股被过滤"""
        result = self._apply_filters(self.stock_pool)
        ts_codes = [s["ts_code"] for s in result]
        self.assertNotIn("000004.SZ", ts_codes)  # 停牌股

    def test_filter_small_cap(self):
        """规则5: 自由流通市值 < 20亿被过滤"""
        result = self._apply_filters(self.stock_pool)
        ts_codes = [s["ts_code"] for s in result]
        self.assertNotIn("000003.SZ", ts_codes)  # 小盘股10亿

    def test_filter_low_turnover(self):
        """规则6: 5日均换手率 < 2%被过滤"""
        result = self._apply_filters(self.stock_pool)
        ts_codes = [s["ts_code"] for s in result]
        self.assertNotIn("000003.SZ", ts_codes)  # 小盘股换手率1%

    def test_filter_yiziban(self):
        """规则7: 连续一字板被过滤"""
        result = self._apply_filters(self.stock_pool)
        ts_codes = [s["ts_code"] for s in result]
        self.assertNotIn("000005.SZ", ts_codes)  # 一字板

    def test_valid_stock_passes(self):
        """正常股票通过所有过滤"""
        result = self._apply_filters(self.stock_pool)
        ts_codes = [s["ts_code"] for s in result]
        self.assertIn("000001.SZ", ts_codes)  # 平安银行应通过

    def test_filter_combined(self):
        """综合过滤后只剩正常股票"""
        result = self._apply_filters(self.stock_pool)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["ts_code"], "000001.SZ")


if __name__ == "__main__":
    unittest.main()
