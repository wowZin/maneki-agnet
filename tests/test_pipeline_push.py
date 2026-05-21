#!/usr/bin/env python3
"""
zt_pipeline.py push_feishu 推送规则单测
覆盖：>=50取前3（按总分降序），<50不推送
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))

import scripts.zt_pipeline as pipeline_mod
from scripts.zt_pipeline import push_feishu


def _make_results(scores):
    """构造测试数据: scores = [("A", 80), ("B", 40), ...]
    含 push_feishu 构建卡片所需的 name + scores 字段
    """
    return [
        {
            "code": code,
            "name": f"股票{code}",
            "total": total,
            "scores": {"fundamental": 0, "technical": 0, "fundflow": 0, "sentiment": 0},
        }
        for code, total in scores
    ]


_FAKE_CONFIG = {
    "FEISHU_APP_ID": "test_app_id",
    "FEISHU_APP_SECRET": "test_secret",
    "FEISHU_WEBHOOK": "https://test.webhook",
    "FEISHU_CHAT_ID_SIGNAL": "oc_fake_chat_id",
    "FEISHU_TEST_MODE": "",
}


class TestPushFeishuPushRule:
    """测试 push_feishu 推送筛选规则"""

    @patch("requests.post")
    def test_5_above_50_push_top3(self, mock_post, tmp_path):
        """5只>=50，只推送前3（按总分降序）"""
        mock_post.side_effect = [
            MagicMock(json=lambda: {"tenant_access_token": "fake_token"}),
            MagicMock(json=lambda: {"code": 0, "data": {"message_id": "msg_123"}}),
        ]
        results = _make_results([
            ("A", 80), ("B", 70), ("C", 60), ("D", 55), ("E", 50),
        ])
        with patch.object(pipeline_mod, "PROJECT_DIR", tmp_path), \
             patch.object(pipeline_mod, "CONFIG", _FAKE_CONFIG):
            result = push_feishu(results)
        assert result is True
        pushed_dir = tmp_path / "data" / "pushed"
        files = list(pushed_dir.glob("*.json"))
        assert len(files) == 1
        pushed_data = json.loads(files[0].read_text())
        assert len(pushed_data) == 3
        codes = {p["code"] for p in pushed_data}
        assert codes == {"A", "B", "C"}

    def test_all_below_50_no_push(self, tmp_path):
        """全部<50，不推送，返回False"""
        results = _make_results([("A", 40), ("B", 30), ("C", 20)])
        with patch.object(pipeline_mod, "PROJECT_DIR", tmp_path):
            result = push_feishu(results)
        assert result is False

    @patch("requests.post")
    def test_exactly_3_above_50(self, mock_post, tmp_path):
        """恰好3只>=50，全部推送"""
        mock_post.side_effect = [
            MagicMock(json=lambda: {"tenant_access_token": "fake_token"}),
            MagicMock(json=lambda: {"code": 0, "data": {"message_id": "msg_123"}}),
        ]
        results = _make_results([("A", 80), ("B", 60), ("C", 50)])
        with patch.object(pipeline_mod, "PROJECT_DIR", tmp_path), \
             patch.object(pipeline_mod, "CONFIG", _FAKE_CONFIG):
            result = push_feishu(results)
        assert result is True
        pushed_dir = tmp_path / "data" / "pushed"
        files = list(pushed_dir.glob("*.json"))
        pushed_data = json.loads(files[0].read_text())
        assert len(pushed_data) == 3

    @patch("requests.post")
    def test_1_above_50_many_below(self, mock_post, tmp_path):
        """1只>=50 + 多只<50，只推1只"""
        mock_post.side_effect = [
            MagicMock(json=lambda: {"tenant_access_token": "fake_token"}),
            MagicMock(json=lambda: {"code": 0, "data": {"message_id": "msg_123"}}),
        ]
        results = _make_results([("A", 55), ("B", 40), ("C", 30), ("D", 20)])
        with patch.object(pipeline_mod, "PROJECT_DIR", tmp_path), \
             patch.object(pipeline_mod, "CONFIG", _FAKE_CONFIG):
            result = push_feishu(results)
        assert result is True
        pushed_dir = tmp_path / "data" / "pushed"
        files = list(pushed_dir.glob("*.json"))
        pushed_data = json.loads(files[0].read_text())
        assert len(pushed_data) == 1
        assert pushed_data[0]["code"] == "A"

    @patch("requests.post")
    def test_sorted_by_total_desc(self, mock_post, tmp_path):
        """推送结果按总分降序"""
        mock_post.side_effect = [
            MagicMock(json=lambda: {"tenant_access_token": "fake_token"}),
            MagicMock(json=lambda: {"code": 0, "data": {"message_id": "msg_123"}}),
        ]
        results = _make_results([("C", 60), ("A", 80), ("B", 70), ("D", 40)])
        with patch.object(pipeline_mod, "PROJECT_DIR", tmp_path), \
             patch.object(pipeline_mod, "CONFIG", _FAKE_CONFIG):
            result = push_feishu(results)
        assert result is True
        pushed_dir = tmp_path / "data" / "pushed"
        files = list(pushed_dir.glob("*.json"))
        pushed_data = json.loads(files[0].read_text())
        totals = [p["total"] for p in pushed_data]
        assert totals == sorted(totals, reverse=True)

    def test_boundary_49_excluded(self, tmp_path):
        """总分=49不应被推送"""
        results = _make_results([("A", 49)])
        with patch.object(pipeline_mod, "PROJECT_DIR", tmp_path):
            result = push_feishu(results)
        assert result is False

    @patch("requests.post")
    def test_boundary_50_included(self, mock_post, tmp_path):
        """总分=50应被推送"""
        mock_post.side_effect = [
            MagicMock(json=lambda: {"tenant_access_token": "fake_token"}),
            MagicMock(json=lambda: {"code": 0, "data": {"message_id": "msg_123"}}),
        ]
        results = _make_results([("A", 50)])
        with patch.object(pipeline_mod, "PROJECT_DIR", tmp_path), \
             patch.object(pipeline_mod, "CONFIG", _FAKE_CONFIG):
            result = push_feishu(results)
        assert result is True
        pushed_dir = tmp_path / "data" / "pushed"
        files = list(pushed_dir.glob("*.json"))
        pushed_data = json.loads(files[0].read_text())
        assert len(pushed_data) == 1
        assert pushed_data[0]["code"] == "A"
