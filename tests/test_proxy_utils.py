#!/usr/bin/env python3
"""proxy_utils.py 单元测试

测试重点:
1. is_proxy_enabled - 代理启用检查
2. get_proxy_ip - 代理IP获取+缓存+过期刷新
3. get_proxies_dict - 代理dict格式化
4. get_requests_session_with_proxy - session创建
5. get_urllib_opener_with_proxy - opener创建
6. kill_chromium - 进程管理

运行: cd /Users/zhangying/projects/study/maneki-agent && python3 -m pytest tests/test_proxy_utils.py -v
"""

import json
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

PROJECT_ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import proxy_utils


class TestIsProxyEnabled(unittest.TestCase):
    """代理启用检查"""

    def test_proxy_enabled_true(self):
        """PROXY_ENABLED=true时应返回True"""
        with patch.object(proxy_utils, 'PROXY_ENABLED', True):
            self.assertTrue(proxy_utils.is_proxy_enabled())

    def test_proxy_enabled_false(self):
        """PROXY_ENABLED=false时应返回False"""
        with patch.object(proxy_utils, 'PROXY_ENABLED', False):
            self.assertFalse(proxy_utils.is_proxy_enabled())


class TestGetProxyIP(unittest.TestCase):
    """代理IP获取+缓存"""

    def setUp(self):
        """重置缓存"""
        proxy_utils._cached_proxy = None

    def _make_mock_resp(self, text):
        """创建模拟urllib响应(支持with语句)"""
        mock_resp = MagicMock()
        mock_resp.read.return_value = text.encode('utf-8') if isinstance(text, str) else text
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    def test_get_proxy_ip_from_api(self):
        """从API获取代理IP"""
        api_response = json.dumps({
            "data": {
                "proxy_list": [
                    {"ip": "1.2.3.4", "port": 8080, "expired_seconds": 130}
                ]
            }
        })
        mock_resp = self._make_mock_resp(api_response)

        with patch.object(proxy_utils, 'PROXY_INST_ID', 'test_inst'), \
             patch.object(proxy_utils, 'PROXY_AKEY', 'test_key'), \
             patch.object(proxy_utils, 'PROXY_API_URL', 'http://test.api/GetIP/'), \
             patch('proxy_utils.urllib.request.urlopen', return_value=mock_resp):
            addr = proxy_utils.get_proxy_ip(force_refresh=True)
            self.assertEqual(addr, "1.2.3.4:8080")
            # 检查缓存
            self.assertIsNotNone(proxy_utils._cached_proxy)
            self.assertEqual(proxy_utils._cached_proxy["ip"], "1.2.3.4")
            self.assertEqual(proxy_utils._cached_proxy["port"], 8080)

    def test_get_proxy_ip_cache_reuse(self):
        """缓存未过期时应复用"""
        proxy_utils._cached_proxy = {
            "ip": "5.6.7.8", "port": 9090,
            "expires_at": time.time() + 100  # 未过期
        }
        addr = proxy_utils.get_proxy_ip()
        self.assertEqual(addr, "5.6.7.8:9090")

    def test_get_proxy_ip_cache_expired_refresh(self):
        """缓存过期时应刷新"""
        api_response = json.dumps({
            "data": {
                "proxy_list": [
                    {"ip": "9.8.7.6", "port": 7777, "expired_seconds": 130}
                ]
            }
        })
        mock_resp = self._make_mock_resp(api_response)

        proxy_utils._cached_proxy = {
            "ip": "5.6.7.8", "port": 9090,
            "expires_at": time.time() - 10  # 已过期
        }

        with patch.object(proxy_utils, 'PROXY_INST_ID', 'test_inst'), \
             patch.object(proxy_utils, 'PROXY_AKEY', 'test_key'), \
             patch.object(proxy_utils, 'PROXY_API_URL', 'http://test.api/GetIP/'), \
             patch('proxy_utils.urllib.request.urlopen', return_value=mock_resp):
            addr = proxy_utils.get_proxy_ip()
            self.assertEqual(addr, "9.8.7.6:7777")

    def test_get_proxy_ip_api_failure(self):
        """API失败时应返回None"""
        proxy_utils._cached_proxy = None
        with patch('proxy_utils.urllib.request.urlopen', side_effect=Exception("API unreachable")):
            addr = proxy_utils.get_proxy_ip(force_refresh=True)
            self.assertIsNone(addr)

    def test_get_proxy_ip_empty_api_response(self):
        """API返回空内容时应返回None"""
        mock_resp = self._make_mock_resp('')
        proxy_utils._cached_proxy = None

        with patch('proxy_utils.urllib.request.urlopen', return_value=mock_resp):
            addr = proxy_utils.get_proxy_ip(force_refresh=True)
            self.assertIsNone(addr)

    def test_get_proxy_ip_no_proxy_list(self):
        """API返回无proxy_list时应返回None"""
        api_response = json.dumps({"data": {"proxy_list": []}})
        mock_resp = self._make_mock_resp(api_response)
        proxy_utils._cached_proxy = None

        with patch.object(proxy_utils, 'PROXY_INST_ID', 'test_inst'), \
             patch.object(proxy_utils, 'PROXY_AKEY', 'test_key'), \
             patch.object(proxy_utils, 'PROXY_API_URL', 'http://test.api/GetIP/'), \
             patch('proxy_utils.urllib.request.urlopen', return_value=mock_resp):
            addr = proxy_utils.get_proxy_ip(force_refresh=True)
            self.assertIsNone(addr)


class TestGetProxiesDict(unittest.TestCase):
    """代理dict格式化"""

    def test_proxy_disabled_returns_none(self):
        """代理未启用时返回None"""
        with patch.object(proxy_utils, 'PROXY_ENABLED', False):
            result = proxy_utils.get_proxies_dict()
            self.assertIsNone(result)

    def test_proxies_dict_format(self):
        """返回正确格式的代理dict"""
        with patch.object(proxy_utils, 'PROXY_ENABLED', True), \
             patch.object(proxy_utils, '_cached_proxy', {
                 "ip": "1.2.3.4", "port": 8080,
                 "expires_at": time.time() + 100
             }):
            result = proxy_utils.get_proxies_dict()
            self.assertIsNotNone(result)
            self.assertEqual(result["http"], "http://1.2.3.4:8080")
            self.assertEqual(result["https"], "http://1.2.3.4:8080")

    def test_proxies_dict_with_explicit_addr(self):
        """传入显式proxy_addr时使用该地址"""
        with patch.object(proxy_utils, 'PROXY_ENABLED', True):
            result = proxy_utils.get_proxies_dict(proxy_addr="10.0.0.1:9999")
            self.assertEqual(result["http"], "http://10.0.0.1:9999")
            self.assertEqual(result["https"], "http://10.0.0.1:9999")


class TestGetRequestsSessionWithProxy(unittest.TestCase):
    """requests.Session创建"""

    def test_session_with_proxy(self):
        """代理启用时应创建带代理的session"""
        import requests
        mock_home_resp = MagicMock()
        mock_home_resp.status_code = 200

        with patch.object(proxy_utils, 'PROXY_ENABLED', True), \
             patch.object(proxy_utils, '_cached_proxy', {
                 "ip": "1.2.3.4", "port": 8080,
                 "expires_at": time.time() + 100
             }), \
             patch.object(requests.Session, 'get', return_value=mock_home_resp):
            session = proxy_utils.get_requests_session_with_proxy()
            self.assertIsNotNone(session)
            self.assertEqual(session.proxies["http"], "http://1.2.3.4:8080")
            self.assertEqual(session.proxies["https"], "http://1.2.3.4:8080")
            self.assertIn("Mozilla", session.headers["User-Agent"])

    def test_session_without_proxy(self):
        """代理未启用时应创建普通session"""
        with patch.object(proxy_utils, 'PROXY_ENABLED', False):
            session = proxy_utils.get_requests_session_with_proxy()
            self.assertIsNotNone(session)
            self.assertIsNone(session.proxies.get("http"))
            self.assertIn("Mozilla", session.headers["User-Agent"])


class TestGetUrllibOpenerWithProxy(unittest.TestCase):
    """urllib OpenerDirector创建"""

    def test_opener_disabled_returns_none(self):
        """代理未启用时返回None"""
        with patch.object(proxy_utils, 'PROXY_ENABLED', False):
            result = proxy_utils.get_urllib_opener_with_proxy()
            self.assertIsNone(result)

    def test_opener_with_proxy(self):
        """代理启用时应创建带代理的opener"""
        with patch.object(proxy_utils, 'PROXY_ENABLED', True), \
             patch.object(proxy_utils, '_cached_proxy', {
                 "ip": "1.2.3.4", "port": 8080,
                 "expires_at": time.time() + 100
             }):
            opener = proxy_utils.get_urllib_opener_with_proxy()
            self.assertIsNotNone(opener)
            has_ua = any(h[0] == "User-Agent" for h in opener.addheaders)
            self.assertTrue(has_ua)


class TestKillChromium(unittest.TestCase):
    """Chromium进程管理"""

    def test_kill_chromium_no_proc(self):
        """无proc时pkill所有Chromium"""
        with patch('subprocess.run'):
            proxy_utils.kill_chromium(None)

    def test_kill_chromium_with_proc(self):
        """有proc时terminate进程"""
        mock_proc = MagicMock()
        mock_proc.wait.return_value = 0
        proxy_utils.kill_chromium(mock_proc)
        mock_proc.terminate.assert_called_once()
        mock_proc.wait.assert_called_once()


if __name__ == "__main__":
    unittest.main()