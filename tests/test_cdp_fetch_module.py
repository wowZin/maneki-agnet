#!/usr/bin/env python3
"""CDP涨速获取模块(cdp_fetch.py)单元测试

测试重点:
1. 交易时段检查 (is_trading_hours)
2. CDP就绪检查 (check_cdp_ready)
3. 连接重试 (connect_cdp) - mock场景
4. 导航+获取重试 (navigate_and_fetch) - mock场景
5. 数据解析 (parse_surge_data)
6. 完整流程重试 (get_surge_rate_cdp) - mock场景
7. 保存数据 (save_surge_data)

运行: cd /Users/zhangying/projects/study/maneki-agent && python3 -m pytest tests/test_cdp_fetch_module.py -v
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch, call

PROJECT_ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from cdp_fetch import (
    is_trading_hours,
    check_cdp_ready,
    connect_cdp,
    navigate_and_fetch,
    parse_surge_data,
    save_surge_data,
    get_surge_rate_cdp,
)


class TestIsTradingHours(unittest.TestCase):
    """交易时段检查"""

    @patch('cdp_fetch.datetime')
    def test_weekday_trading_morning(self, mock_dt):
        """周一早盘 10:00 应为交易时段"""
        mock_now = MagicMock()
        mock_now.weekday.return_value = 0  # Monday
        mock_now.hour = 10
        mock_now.minute = 0
        mock_dt.now.return_value = mock_now
        ok, reason = is_trading_hours()
        self.assertTrue(ok)
        self.assertIsNone(reason)

    @patch('cdp_fetch.datetime')
    def test_weekday_trading_afternoon(self, mock_dt):
        """周二午盘 13:30 应为交易时段"""
        mock_now = MagicMock()
        mock_now.weekday.return_value = 1  # Tuesday
        mock_now.hour = 13
        mock_now.minute = 30
        mock_dt.now.return_value = mock_now
        ok, reason = is_trading_hours()
        self.assertTrue(ok)

    @patch('cdp_fetch.datetime')
    def test_weekday_non_trading(self, mock_dt):
        """周三 12:00 非交易时段"""
        mock_now = MagicMock()
        mock_now.weekday.return_value = 2  # Wednesday
        mock_now.hour = 12
        mock_now.minute = 0
        mock_dt.now.return_value = mock_now
        ok, reason = is_trading_hours()
        self.assertFalse(ok)
        self.assertIn("非交易时段", reason)

    @patch('cdp_fetch.datetime')
    def test_weekend(self, mock_dt):
        """周六应为非交易时段"""
        mock_now = MagicMock()
        mock_now.weekday.return_value = 5  # Saturday
        mock_now.hour = 10
        mock_now.minute = 0
        mock_dt.now.return_value = mock_now
        ok, reason = is_trading_hours()
        self.assertFalse(ok)
        self.assertEqual(reason, "周末休市")


class TestCheckCDPReady(unittest.TestCase):
    """CDP就绪检查"""

    def test_cdp_ready(self):
        """正常返回含Browser字段时应就绪"""
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"Browser": "Chromium/120.0"}'
        with patch('urllib.request.urlopen', return_value=mock_resp):
            self.assertTrue(check_cdp_ready())

    def test_cdp_not_ready_no_browser(self):
        """返回不含Browser字段时不应就绪"""
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"some": "data"}'
        with patch('urllib.request.urlopen', return_value=mock_resp):
            self.assertFalse(check_cdp_ready())

    def test_cdp_not_ready_connection_error(self):
        """连接失败时不应就绪"""
        with patch('urllib.request.urlopen', side_effect=Exception("Connection refused")):
            self.assertFalse(check_cdp_ready())


class TestConnectCDP(unittest.TestCase):
    """CDP连接重试"""

    def test_connect_success_first_try(self):
        """第一次连接成功"""
        import websocket as ws_mod
        mock_ws = MagicMock()
        targets = [{"type": "page", "webSocketDebuggerUrl": "ws://localhost:9222/devtools/page/123", "url": "https://example.com"}]
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(targets).encode()

        with patch('urllib.request.urlopen', return_value=mock_resp), \
             patch.object(ws_mod, 'create_connection', return_value=mock_ws):
            ws, page_url = connect_cdp(max_retries=1, retry_interval=0.1)
            self.assertIsNotNone(ws)
            self.assertEqual(ws, mock_ws)

    def test_connect_retry_then_success(self):
        """第一次无page target, 第二次成功"""
        import websocket as ws_mod
        mock_ws = MagicMock()
        targets_empty = [{"type": "service_worker", "webSocketDebuggerUrl": "ws://..."}]
        targets_ok = [{"type": "page", "webSocketDebuggerUrl": "ws://localhost:9222/devtools/page/456", "url": "https://test.com"}]

        call_count = 0
        def mock_urlopen(url, timeout=None):
            nonlocal call_count
            call_count += 1
            mock_resp = MagicMock()
            if call_count == 1:
                mock_resp.read.return_value = json.dumps(targets_empty).encode()
            else:
                mock_resp.read.return_value = json.dumps(targets_ok).encode()
            return mock_resp

        with patch('urllib.request.urlopen', side_effect=mock_urlopen), \
             patch.object(ws_mod, 'create_connection', return_value=mock_ws):
            ws, page_url = connect_cdp(max_retries=3, retry_interval=0.1)
            self.assertIsNotNone(ws)
            self.assertEqual(call_count, 2)

    def test_connect_all_retries_fail(self):
        """所有重试都失败"""
        with patch('urllib.request.urlopen', side_effect=Exception("Connection refused")):
            ws, page_url = connect_cdp(max_retries=3, retry_interval=0.1)
            self.assertIsNone(ws)
            self.assertIsNone(page_url)


class TestNavigateAndFetch(unittest.TestCase):
    """导航+获取数据 — 通过mock ws.send/ws.recv测试内部逻辑"""

    def test_navigate_success(self):
        """成功获取数据的完整导航流程"""
        api_data = {
            "data": {
                "diff": [{"f12": "000001", "f14": "平安银行", "f3": 2.5, "f11": 3.5}]
            }
        }
        api_text = json.dumps(api_data)

        # 构造mock ws: send记录消息, recv返回id=3的evaluate响应
        # navigate_and_fetch内部: msg_id从0开始, 发送id=1(home), id=2(api), id=3(eval)
        # recv循环只匹配id=3的响应，忽略id=1/id=2的CDP响应
        mock_ws = MagicMock()
        eval_response = {
            "id": 3,
            "result": {"result": {"value": api_text}}
        }

        # recv()被调用多次，第一次返回id=1的导航响应, 第二次id=2, 第三次id=3(eval)
        # 但navigate_and_fetch只关心id等于当前msg_id(=3)的响应
        recv_queue = [
            json.dumps({"id": 1}),  # home导航响应 (被忽略)
            json.dumps({"id": 2}),  # api导航响应 (被忽略)
            json.dumps(eval_response),  # evaluate响应 (被匹配)
        ]
        recv_state = {"idx": 0}
        def mock_recv():
            idx = recv_state["idx"]
            if idx < len(recv_queue):
                recv_state["idx"] = idx + 1
                return recv_queue[idx]
            return json.dumps({"id": -1})

        mock_ws.recv.side_effect = mock_recv

        with patch('time.sleep'):
            result = navigate_and_fetch(mock_ws, max_retries=1, home_wait=0, api_wait=0)
            self.assertIsNotNone(result)
            self.assertIn("data", result)
            self.assertEqual(len(result["data"]["diff"]), 1)

    def test_navigate_empty_data_returns_none(self):
        """API返回空数据(diff为空列表)应返回None(视为session失效)"""
        empty_data = {"data": {"diff": []}}
        mock_ws = MagicMock()

        # 单次尝试, max_retries=1
        eval_response = {"id": 3, "result": {"result": {"value": json.dumps(empty_data)}}}
        recv_queue = [
            json.dumps({"id": 1}),
            json.dumps({"id": 2}),
            json.dumps(eval_response),
        ]
        recv_state = {"idx": 0}
        def mock_recv():
            idx = recv_state["idx"]
            if idx < len(recv_queue):
                recv_state["idx"] = idx + 1
                return recv_queue[idx]
            return json.dumps({"id": -1})

        mock_ws.recv.side_effect = mock_recv

        with patch('time.sleep'):
            # max_retries=1, 只尝试一次，空数据即返回None
            result = navigate_and_fetch(mock_ws, max_retries=1, home_wait=0, api_wait=0)
            self.assertIsNone(result)

    def test_navigate_json_parse_fail_returns_none(self):
        """JSON解析失败(非JSON内容)且max_retries=1应返回None"""
        mock_ws = MagicMock()
        # 返回非JSON文本
        eval_response = {"id": 3, "result": {"result": {"value": "ERR_EMPTY_RESPONSE"}}}
        recv_queue = [
            json.dumps({"id": 1}),
            json.dumps({"id": 2}),
            json.dumps(eval_response),
        ]
        recv_state = {"idx": 0}
        def mock_recv():
            idx = recv_state["idx"]
            if idx < len(recv_queue):
                recv_state["idx"] = idx + 1
                return recv_queue[idx]
            return json.dumps({"id": -1})

        mock_ws.recv.side_effect = mock_recv

        with patch('time.sleep'):
            result = navigate_and_fetch(mock_ws, max_retries=1, home_wait=0, api_wait=0)
            self.assertIsNone(result)

    def test_navigate_no_response_timeout(self):
        """recv未返回匹配id的响应，超时后返回None"""
        mock_ws = MagicMock()
        # recv只返回不匹配的id
        recv_queue = [
            json.dumps({"id": 99}),  # 不匹配msg_id=3
            json.dumps({"id": 100}),
        ]
        recv_state = {"idx": 0}
        def mock_recv():
            idx = recv_state["idx"]
            if idx < len(recv_queue):
                recv_state["idx"] = idx + 1
                return recv_queue[idx]
            # 返回不匹配的id，让循环继续直到超时
            return json.dumps({"id": -1})

        mock_ws.recv.side_effect = mock_recv

        with patch('time.sleep'), \
             patch('time.time', side_effect=[0, 0, 0, 20]):  # 模拟超时(deadline=time.time()+10=10, 20>10)
            result = navigate_and_fetch(mock_ws, max_retries=1, home_wait=0, api_wait=0)
            self.assertIsNone(result)


class TestParseSurgeData(unittest.TestCase):
    """数据解析过滤"""

    def test_parse_normal_data(self):
        """正常解析+过滤"""
        api_data = {
            "data": {
                "diff": [
                    {"f12": "000001", "f14": "平安银行", "f3": 2.5, "f11": 3.5, "f2": 12.5, "f6": 500000, "f10": 1.5},
                    {"f12": "300001", "f14": "特锐德", "f3": 5.0, "f11": 4.0, "f2": 20.0, "f6": 300000, "f10": 2.0},  # 创业板应被过滤
                    {"f12": "600000", "f14": "浦发银行", "f3": 1.8, "f11": 2.0, "f2": 8.0, "f6": 200000, "f10": 0.8},
                ]
            }
        }
        result = parse_surge_data(api_data)
        self.assertEqual(len(result), 2)  # 创业板被过滤
        # 按涨速排序: 3.5 > 2.0
        self.assertEqual(result[0]["5分钟涨速%"], 3.5)
        self.assertEqual(result[1]["5分钟涨速%"], 2.0)

    def test_parse_st_filtered(self):
        """ST股票应被过滤"""
        api_data = {
            "data": {
                "diff": [
                    {"f12": "000001", "f14": "ST某某", "f3": 5, "f11": 10, "f2": 1, "f6": 100, "f10": 1},
                    {"f12": "000002", "f14": "万科", "f3": 2, "f11": 3, "f2": 10, "f6": 200, "f10": 1},
                ]
            }
        }
        result = parse_surge_data(api_data)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["名称"], "万科")

    def test_parse_kcb_filtered(self):
        """科创板688应被过滤"""
        api_data = {
            "data": {
                "diff": [
                    {"f12": "688001", "f14": "科创某某", "f3": 10, "f11": 5, "f2": 50, "f6": 1000, "f10": 3},
                ]
            }
        }
        result = parse_surge_data(api_data)
        self.assertEqual(len(result), 0)

    def test_parse_top100_limit(self):
        """超过100只应截断"""
        diff = [{"f12": f"0000{i:03d}", "f14": f"股票{i}", "f3": 1.0, "f11": float(i), "f2": 10, "f6": 1000, "f10": 1} for i in range(150)]
        api_data = {"data": {"diff": diff}}
        result = parse_surge_data(api_data)
        self.assertEqual(len(result), 100)
        # 最高涨速排在前面
        self.assertEqual(result[0]["5分钟涨速%"], 149.0)

    def test_parse_empty_data(self):
        """空数据返回空列表"""
        result = parse_surge_data(None)
        self.assertEqual(result, [])
        result = parse_surge_data({})
        self.assertEqual(result, [])

    def test_parse_none_pct_filtered(self):
        """涨幅为None应被过滤"""
        api_data = {
            "data": {
                "diff": [
                    {"f12": "000001", "f14": "万科", "f3": None, "f11": 3, "f2": 10, "f6": 100, "f10": 1},
                    {"f12": "000002", "f14": "平安", "f3": 2, "f11": 1, "f2": 15, "f6": 200, "f10": 1},
                ]
            }
        }
        result = parse_surge_data(api_data)
        self.assertEqual(len(result), 1)


class TestSaveSurgeData(unittest.TestCase):
    """保存数据"""

    def test_save_creates_file(self):
        """保存应创建JSON文件"""
        stocks = [{"代码": "000001", "名称": "平安银行", "涨幅%": 2.5, "5分钟涨速%": 3.5}]
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('cdp_fetch.DATA_DIR', Path(tmpdir)):
                out_file = save_surge_data(stocks, total_filtered=50)
                self.assertTrue(os.path.exists(out_file))
                with open(out_file) as f:
                    saved = json.load(f)
                self.assertEqual(saved["count"], 1)
                self.assertEqual(saved["total_filtered"], 50)
                self.assertEqual(saved["stocks"][0]["名称"], "平安银行")


class TestGetSurgeRateCDP(unittest.TestCase):
    """完整流程（带mock）"""

    def test_non_trading_hours_returns_none(self):
        """非交易时段应返回None"""
        with patch('cdp_fetch.is_trading_hours', return_value=(False, "周末休市")):
            result = get_surge_rate_cdp(skip_trading_check=False)
            self.assertIsNone(result)

    def test_skip_trading_check_allowed(self):
        """跳过交易检查时继续执行"""
        mock_ws = MagicMock()
        api_data = {
            "data": {
                "diff": [{"f12": "000001", "f14": "平安银行", "f3": 2.5, "f11": 3.5, "f2": 12.5, "f6": 500000, "f10": 1.5}]
            }
        }

        with patch('cdp_fetch.is_trading_hours') as mock_th, \
             patch('cdp_fetch.connect_cdp', return_value=(mock_ws, "test")) as mock_conn, \
             patch('cdp_fetch.navigate_and_fetch', return_value=api_data) as mock_nav, \
             patch('cdp_fetch.save_surge_data', return_value="/tmp/test.json") as mock_save, \
             patch('cdp_fetch.parse_surge_data') as mock_parse:
            
            mock_parse.return_value = [{"代码": "000001", "名称": "平安银行", "涨幅%": 2.5, "5分钟涨速%": 3.5, "最新价": 12.5, "成交额": 500000, "量比": 1.5}]
            result = get_surge_rate_cdp(skip_trading_check=True)
            
            # 验证跳过了交易时段检查
            mock_th.assert_not_called()
            # 验证执行了连接和导航
            mock_conn.assert_called_once()
            mock_nav.assert_called_once()
            self.assertIsNotNone(result)

    def test_cdp_connect_failure_returns_none(self):
        """CDP连接失败应返回None"""
        with patch('cdp_fetch.is_trading_hours', return_value=(True, None)), \
             patch('cdp_fetch.connect_cdp', return_value=(None, None)):
            result = get_surge_rate_cdp(skip_trading_check=False)
            self.assertIsNone(result)

    def test_navigate_failure_returns_none(self):
        """导航失败应返回None"""
        mock_ws = MagicMock()
        with patch('cdp_fetch.is_trading_hours', return_value=(True, None)), \
             patch('cdp_fetch.connect_cdp', return_value=(mock_ws, "test")), \
             patch('cdp_fetch.navigate_and_fetch', return_value=None):
            result = get_surge_rate_cdp(skip_trading_check=False)
            self.assertIsNone(result)
            mock_ws.close.assert_called()  # 确保WS被关闭

    def test_success_with_custom_retry_params(self):
        """自定义重试参数应传递给连接和导航"""
        mock_ws = MagicMock()
        api_data = {"data": {"diff": [{"f12": "000001", "f14": "万科", "f3": 1, "f11": 2, "f2": 10, "f6": 100, "f10": 1}]}}

        with patch('cdp_fetch.is_trading_hours', return_value=(True, None)), \
             patch('cdp_fetch.connect_cdp', return_value=(mock_ws, "test")) as mock_conn, \
             patch('cdp_fetch.navigate_and_fetch', return_value=api_data) as mock_nav, \
             patch('cdp_fetch.parse_surge_data', return_value=[]), \
             patch('cdp_fetch.save_surge_data', return_value="/tmp/test.json"):
            
            get_surge_rate_cdp(
                skip_trading_check=True,
                connect_retries=5,
                navigate_retries=3,
            )
            
            mock_conn.assert_called_once_with(max_retries=5, retry_interval=2)
            mock_nav.assert_called_once_with(mock_ws, max_retries=3, home_wait=2, api_wait=3)


if __name__ == "__main__":
    unittest.main()