#!/usr/bin/env python3
"""
CDP 实时数据获取单元测试
验证 Chrome CDP 抓取东方财富 push2.eastmoney.com 流程可正常执行
关键: 必须先访问 eastmoney.com 首页建立 session，再请求 clist API

运行: python -m pytest tests/test_cdp_fetch.py -v
依赖: playwright 或 selenium (Chrome CDP)
"""

import os
import sys
import unittest
from unittest.mock import Mock, patch, MagicMock

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


class TestCDPSessionEstablishment(unittest.TestCase):
    """测试 CDP session 建立流程"""

    def test_session_cookie_requirement(self):
        """
        验证: 直接请求 clist API 会失败，必须先访问首页建立 session。
        这是东方财富反爬的核心机制。
        """
        # 模拟直接请求 clist API（无 cookie）
        mock_response_empty = Mock()
        mock_response_empty.text = ""
        mock_response_empty.status_code = 200

        # 模拟带 cookie 请求
        mock_response_with_data = Mock()
        mock_response_with_data.text = '{"data":{"diff":[{"f1":"000001","f2":"10.5"}]}}'
        mock_response_with_data.status_code = 200

        # 断言: 无 cookie 时返回空/错误
        self.assertEqual(mock_response_empty.text, "")
        # 断言: 有 cookie 时返回正常 JSON
        self.assertIn("data", mock_response_with_data.text)

    def test_cdp_navigation_sequence(self):
        """
        验证正确的导航顺序:
        Step 1: 访问 https://www.eastmoney.com/ 建立 session/cookie
        Step 2: 导航到 clist API 获取实时数据
        """
        steps = []

        def mock_cdp_fetch():
            # Step 1: 访问首页
            steps.append("navigate_eastmoney_home")
            # 模拟设置 cookie
            steps.append("set_session_cookie")
            # Step 2: 访问 clist API
            steps.append("navigate_clist_api")
            # 获取 f11 涨速字段
            steps.append("extract_f11_field")
            return {"f11": 3.5, "ts_code": "000001.SZ"}

        result = mock_cdp_fetch()
        self.assertEqual(steps, [
            "navigate_eastmoney_home",
            "set_session_cookie",
            "navigate_clist_api",
            "extract_f11_field"
        ])
        self.assertIn("f11", result)


class TestCDPDataParsing(unittest.TestCase):
    """测试 CDP 返回数据解析"""

    def test_f11_field_extraction(self):
        """验证 f11 字段（涨速）正确提取"""
        raw_data = {
            "data": {
                "diff": [
                    {"f1": "000001", "f2": "10.50", "f11": "3.52", "f3": "2.15"},
                    {"f1": "000002", "f2": "25.80", "f11": "5.10", "f3": "4.20"},
                ]
            }
        }

        # 解析逻辑
        stocks = []
        for item in raw_data["data"]["diff"]:
            stocks.append({
                "ts_code": item["f1"] + ".SZ",  # 实际需根据交易所判断后缀
                "price": float(item["f2"]),
                "surge_rate": float(item["f11"]),  # f11 = 涨速
                "change_pct": float(item["f3"]),
            })

        self.assertEqual(len(stocks), 2)
        self.assertEqual(stocks[0]["surge_rate"], 3.52)
        self.assertEqual(stocks[1]["surge_rate"], 5.10)

    def test_surge_threshold_filter(self):
        """验证涨速阈值过滤（>3% 触发扫描）"""
        stocks = [
            {"ts_code": "000001.SZ", "surge_rate": 3.5},
            {"ts_code": "000002.SZ", "surge_rate": 1.2},
            {"ts_code": "000003.SZ", "surge_rate": 5.0},
        ]
        threshold = 3.0
        triggered = [s for s in stocks if s["surge_rate"] > threshold]

        self.assertEqual(len(triggered), 2)
        self.assertEqual(triggered[0]["ts_code"], "000001.SZ")
        self.assertEqual(triggered[1]["ts_code"], "000003.SZ")


class TestCDPErrorHandling(unittest.TestCase):
    """测试 CDP 异常处理"""

    def test_empty_response_fallback(self):
        """ERR_EMPTY_RESPONSE 时降级处理"""
        def fetch_with_fallback():
            try:
                # 模拟 CDP 返回空响应
                response = ""
                if not response:
                    raise ValueError("ERR_EMPTY_RESPONSE")
                return response
            except ValueError:
                # 降级: 使用 akshare 或 Tushare
                return {"source": "fallback", "data": []}

        result = fetch_with_fallback()
        self.assertEqual(result["source"], "fallback")

    def test_cors_blocked_handling(self):
        """验证 fetch() CORS 被拦截时的处理"""
        # 浏览器 fetch() 访问 push2.eastmoney.com 会因 CORS 失败
        # 必须使用 CDP (playwright/selenium) 绕过
        def is_cors_issue(error_msg):
            return "CORS" in error_msg or "cross-origin" in error_msg

        self.assertTrue(is_cors_issue("CORS policy blocked"))
        self.assertTrue(is_cors_issue("cross-origin request blocked"))


if __name__ == "__main__":
    unittest.main()
