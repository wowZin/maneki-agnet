"""
工具函数与缓存机制 V1.0 单元测试
测试 CR Round 1 修复项引入的新函数和逻辑
- Fix7: call_tushare 缓存命中/未命中/清空
- Fix10a: safe_float_none / safe_int_none 模块级函数
"""
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('TUSHARE_TOKEN', 'test_token_for_unit_test')


class TestSafeFloatNone(unittest.TestCase):
    """safe_float_none: None和非法值返回None，有效值返回float"""

    def test_none_returns_none(self):
        from plays.limit_up.pipeline import safe_float_none
        self.assertIsNone(safe_float_none(None))

    def test_empty_string_returns_none(self):
        from plays.limit_up.pipeline import safe_float_none
        self.assertIsNone(safe_float_none(""))

    def test_invalid_string_returns_none(self):
        from plays.limit_up.pipeline import safe_float_none
        self.assertIsNone(safe_float_none("abc"))

    def test_valid_string_returns_float(self):
        from plays.limit_up.pipeline import safe_float_none
        self.assertEqual(safe_float_none("3.14"), 3.14)

    def test_int_returns_float(self):
        from plays.limit_up.pipeline import safe_float_none
        self.assertEqual(safe_float_none(42), 42.0)

    def test_zero_returns_zero_not_none(self):
        """0必须返回0.0，不是None——区分'无数据'和'值为0'"""
        from plays.limit_up.pipeline import safe_float_none
        self.assertEqual(safe_float_none(0), 0.0)
        self.assertIsNotNone(safe_float_none(0))

    def test_negative_returns_negative(self):
        from plays.limit_up.pipeline import safe_float_none
        self.assertEqual(safe_float_none(-5.5), -5.5)


class TestSafeIntNone(unittest.TestCase):
    """safe_int_none: None和非法值返回None，有效值返回int"""

    def test_none_returns_none(self):
        from scripts.zt_pipeline import safe_int_none
        self.assertIsNone(safe_int_none(None))

    def test_empty_string_returns_none(self):
        from scripts.zt_pipeline import safe_int_none
        self.assertIsNone(safe_int_none(""))

    def test_invalid_string_returns_none(self):
        from scripts.zt_pipeline import safe_int_none
        self.assertIsNone(safe_int_none("abc"))

    def test_valid_string_returns_int(self):
        from scripts.zt_pipeline import safe_int_none
        self.assertEqual(safe_int_none("7"), 7)

    def test_float_returns_int(self):
        from scripts.zt_pipeline import safe_int_none
        self.assertEqual(safe_int_none(3.7), 3)

    def test_zero_returns_zero_not_none(self):
        """0必须返回0，不是None"""
        from scripts.zt_pipeline import safe_int_none
        self.assertEqual(safe_int_none(0), 0)
        self.assertIsNotNone(safe_int_none(0))


class TestSafeFloat(unittest.TestCase):
    """safe_float: 原有行为——None和非法值返回0.0"""

    def test_none_returns_zero(self):
        from scripts.zt_pipeline import safe_float
        self.assertEqual(safe_float(None), 0.0)

    def test_invalid_returns_zero(self):
        from scripts.zt_pipeline import safe_float
        self.assertEqual(safe_float("abc"), 0.0)

    def test_valid_returns_float(self):
        from scripts.zt_pipeline import safe_float
        self.assertEqual(safe_float("3.14"), 3.14)


class TestTushareCache(unittest.TestCase):
    """call_tushare 缓存机制测试 (Fix7)"""

    def setUp(self):
        from scripts.zt_pipeline import clear_tushare_cache
        clear_tushare_cache()

    def tearDown(self):
        from scripts.zt_pipeline import clear_tushare_cache
        clear_tushare_cache()

    @patch('requests.post')
    def test_cache_miss_calls_api(self, mock_post):
        """缓存未命中：应调用API"""
        from scripts.zt_pipeline import call_tushare, clear_tushare_cache
        clear_tushare_cache()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": {"fields": ["ts_code", "close"], "items": [["000001.SZ", 10.5]]}
        }
        mock_post.return_value = mock_resp

        result = call_tushare("daily", "test_token", {"ts_code": "000001.SZ"})
        self.assertEqual(mock_post.call_count, 1)
        self.assertIn("data", result)

    @patch('requests.post')
    def test_cache_hit_no_api_call(self, mock_post):
        """缓存命中：不应再调用API"""
        from scripts.zt_pipeline import call_tushare, clear_tushare_cache
        clear_tushare_cache()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": {"fields": ["ts_code", "close"], "items": [["000001.SZ", 10.5]]}
        }
        mock_post.return_value = mock_resp

        # 第一次调用
        result1 = call_tushare("daily", "test_token", {"ts_code": "000001.SZ"})
        # 第二次调用（相同参数）应命中缓存
        result2 = call_tushare("daily", "test_token", {"ts_code": "000001.SZ"})

        self.assertEqual(mock_post.call_count, 1, "缓存命中时不应重复调用API")

    @patch('requests.post')
    def test_different_params_no_cache_hit(self, mock_post):
        """不同参数不命中缓存"""
        from scripts.zt_pipeline import call_tushare, clear_tushare_cache
        clear_tushare_cache()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": {"fields": ["ts_code"], "items": []}
        }
        mock_post.return_value = mock_resp

        call_tushare("daily", "test_token", {"ts_code": "000001.SZ"})
        call_tushare("daily", "test_token", {"ts_code": "000002.SZ"})

        self.assertEqual(mock_post.call_count, 2, "不同参数不应命中缓存")

    @patch('requests.post')
    def test_clear_cache_resets(self, mock_post):
        """清空缓存后重新调用API"""
        from scripts.zt_pipeline import call_tushare, clear_tushare_cache
        clear_tushare_cache()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": {"fields": ["ts_code"], "items": []}
        }
        mock_post.return_value = mock_resp

        call_tushare("daily", "test_token", {"ts_code": "000001.SZ"})
        clear_tushare_cache()
        call_tushare("daily", "test_token", {"ts_code": "000001.SZ"})

        self.assertEqual(mock_post.call_count, 2, "清缓存后应重新调用API")

    @patch('requests.post')
    def test_failed_api_also_cached(self, mock_post):
        """API失败也缓存，避免反复重试"""
        from scripts.zt_pipeline import call_tushare, clear_tushare_cache
        clear_tushare_cache()

        mock_post.side_effect = Exception("Network error")

        # 第一次调用失败
        result1 = call_tushare("daily", "test_token", {"ts_code": "000001.SZ"})
        # 第二次调用应从缓存返回空dict，不再抛异常
        result2 = call_tushare("daily", "test_token", {"ts_code": "000001.SZ"})

        self.assertEqual(mock_post.call_count, 1, "失败也应缓存，避免重试")
        self.assertIsInstance(result2, dict)


class TestListToDict(unittest.TestCase):
    """list_to_dict: Tushare list→dict 转换器测试"""

    def test_list_input_converts(self):
        from scripts.zt_pipeline import list_to_dict
        items = [["000001.SZ", 10.5, 1000]]
        fields = ["ts_code", "close", "vol"]
        result = list_to_dict(items, fields)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["ts_code"], "000001.SZ")
        self.assertEqual(result[0]["close"], 10.5)

    def test_dict_input_passthrough(self):
        from scripts.zt_pipeline import list_to_dict
        items = [{"ts_code": "000001.SZ", "close": 10.5}]
        result = list_to_dict(items, ["ts_code", "close"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["ts_code"], "000001.SZ")

    def test_shorter_list_than_fields(self):
        """list比fields短时，缺失字段不出现"""
        from scripts.zt_pipeline import list_to_dict
        items = [["000001.SZ"]]
        result = list_to_dict(items, ["ts_code", "close", "vol"])
        self.assertEqual(result[0]["ts_code"], "000001.SZ")
        self.assertNotIn("close", result[0])

    def test_empty_input(self):
        from scripts.zt_pipeline import list_to_dict
        result = list_to_dict([], ["ts_code"])
        self.assertEqual(result, [])


if __name__ == '__main__':
    unittest.main()
