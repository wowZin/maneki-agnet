#!/usr/bin/env python3
"""
zt_daily_review.py 单元测试
覆盖: build_signal_pct_map, calculate_win_rate, analyze_dimension_performance, confidence_distribution
"""

import sys
from pathlib import Path

# 项目根目录
PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from scripts.zt_daily_review import (
    build_signal_pct_map,
    calculate_win_rate,
    analyze_dimension_performance,
    confidence_distribution,
    safe_float,
)


# ===== build_signal_pct_map 测试 =====

class TestBuildSignalPctMap:
    """测试信号涨幅映射构建"""

    def test_basic_mapping(self):
        """基本映射：6位纯代码 → ts_code"""
        signals = [
            {"代码": "002952", "涨幅%": 10.0},
            {"代码": "600783", "涨幅%": 5.5},
        ]
        result = build_signal_pct_map(signals)
        assert result["002952.SZ"] == 10.0
        assert result["600783.SH"] == 5.5

    def test_ts_code_format_passthrough(self):
        """已有 ts_code 格式直接使用"""
        signals = [
            {"ts_code": "002952.SZ", "涨幅%": 8.0},
        ]
        result = build_signal_pct_map(signals)
        assert result["002952.SZ"] == 8.0

    def test_dedup_first_occurrence(self):
        """去重取首次出现的涨幅"""
        signals = [
            {"代码": "002952", "涨幅%": 10.0},
            {"代码": "002952", "涨幅%": 12.0},  # 第二次出现，应被忽略
        ]
        result = build_signal_pct_map(signals)
        assert result["002952.SZ"] == 10.0

    def test_empty_signals(self):
        """空信号列表"""
        result = build_signal_pct_map([])
        assert result == {}

    def test_code_field_fallback(self):
        """code 字段作为备选"""
        signals = [
            {"code": "000001", "涨幅%": 3.0},
        ]
        result = build_signal_pct_map(signals)
        assert result["000001.SZ"] == 3.0

    def test_missing_pct_defaults_zero(self):
        """缺失涨幅%默认0"""
        signals = [
            {"代码": "002952"},
        ]
        result = build_signal_pct_map(signals)
        assert result["002952.SZ"] == 0.0

    def test_sh_code_prefix(self):
        """上海股票代码(6开头)正确映射"""
        signals = [{"代码": "601398", "涨幅%": 2.0}]
        result = build_signal_pct_map(signals)
        assert "601398.SH" in result

    def test_sz_code_prefix(self):
        """深圳股票代码(0开头)正确映射"""
        signals = [{"代码": "000001", "涨幅%": 1.5}]
        result = build_signal_pct_map(signals)
        assert "000001.SZ" in result


# ===== calculate_win_rate 测试 =====

class TestCalculateWinRate:
    """测试胜率计算"""

    def test_all_win(self):
        """全部获胜：收盘涨幅都大于扫描涨幅"""
        pushed = [
            {"code": "002952.SZ"},
            {"code": "600783.SH"},
        ]
        signal_map = {"002952.SZ": 5.0, "600783.SH": 3.0}
        daily_data = {
            "002952.SZ": {"close": 30.0, "pct_chg": 8.0},
            "600783.SH": {"close": 20.0, "pct_chg": 5.0},
        }
        result = calculate_win_rate(pushed, signal_map, daily_data)
        assert result["win_count"] == 2
        assert result["total"] == 2
        assert result["win_rate"] == 100.0

    def test_all_lose(self):
        """全部失败：收盘涨幅都小于扫描涨幅"""
        pushed = [
            {"code": "002952.SZ"},
            {"code": "600783.SH"},
        ]
        signal_map = {"002952.SZ": 8.0, "600783.SH": 6.0}
        daily_data = {
            "002952.SZ": {"close": 28.0, "pct_chg": 5.0},
            "600783.SH": {"close": 18.0, "pct_chg": 3.0},
        }
        result = calculate_win_rate(pushed, signal_map, daily_data)
        assert result["win_count"] == 0
        assert result["total"] == 2
        assert result["win_rate"] == 0.0

    def test_mixed(self):
        """部分获胜"""
        pushed = [
            {"code": "002952.SZ"},
            {"code": "600783.SH"},
            {"code": "000001.SZ"},
        ]
        signal_map = {"002952.SZ": 5.0, "600783.SH": 6.0, "000001.SZ": 2.0}
        daily_data = {
            "002952.SZ": {"close": 30.0, "pct_chg": 8.0},   # 8 > 5 → win
            "600783.SH": {"close": 18.0, "pct_chg": 3.0},    # 3 < 6 → lose
            "000001.SZ": {"close": 15.0, "pct_chg": 2.0},    # 2 == 2 → not win (equal)
        }
        result = calculate_win_rate(pushed, signal_map, daily_data)
        assert result["win_count"] == 1
        assert result["total"] == 3
        assert abs(result["win_rate"] - 33.33) < 0.1

    def test_missing_signal_data(self):
        """信号数据缺失的股票不参与统计"""
        pushed = [
            {"code": "002952.SZ"},
            {"code": "600783.SH"},  # 无信号数据
        ]
        signal_map = {"002952.SZ": 5.0}
        daily_data = {
            "002952.SZ": {"close": 30.0, "pct_chg": 8.0},
            "600783.SH": {"close": 20.0, "pct_chg": 5.0},
        }
        result = calculate_win_rate(pushed, signal_map, daily_data)
        assert result["total"] == 1
        assert result["win_count"] == 1

    def test_missing_daily_data(self):
        """日线数据缺失的股票不参与统计"""
        pushed = [
            {"code": "002952.SZ"},
            {"code": "600783.SH"},  # 无日线数据
        ]
        signal_map = {"002952.SZ": 5.0, "600783.SH": 3.0}
        daily_data = {
            "002952.SZ": {"close": 30.0, "pct_chg": 8.0},
        }
        result = calculate_win_rate(pushed, signal_map, daily_data)
        assert result["total"] == 1
        assert result["win_count"] == 1

    def test_empty_pushed(self):
        """空推送列表"""
        result = calculate_win_rate([], {}, {})
        assert result["win_count"] == 0
        assert result["total"] == 0
        assert result["win_rate"] == 0

    def test_no_matching_data(self):
        """推送列表无匹配数据"""
        pushed = [{"code": "002952.SZ"}]
        result = calculate_win_rate(pushed, {}, {})
        assert result["total"] == 0
        assert result["win_rate"] == 0


# ===== analyze_dimension_performance 测试 =====

class TestAnalyzeDimensionPerformance:
    """测试维度评分统计（现在只统计推送股票）"""

    def test_basic_stats(self):
        """基本统计：命中/未命中的维度平均分"""
        analysis = [
            {
                "code": "002952.SZ",
                "scores": {"fundamental": 60, "technical": 40},
                "hit": True,
            },
            {
                "code": "600783.SH",
                "scores": {"fundamental": 30, "technical": 20},
                "hit": False,
            },
        ]
        result = analyze_dimension_performance(analysis)
        assert result["fundamental"]["hit_avg"] == 60.0
        assert result["fundamental"]["miss_avg"] == 30.0
        assert result["technical"]["hit_avg"] == 40.0
        assert result["technical"]["miss_avg"] == 20.0

    def test_only_pushed_stocks_counted(self):
        """验证只统计推送股票（非全量分析）"""
        # 模拟推送股票只有2只，全量有3只
        pushed = [
            {
                "code": "002952.SZ",
                "scores": {"fundamental": 60},
                "hit": True,
            },
            {
                "code": "600783.SH",
                "scores": {"fundamental": 30},
                "hit": False,
            },
        ]
        result = analyze_dimension_performance(pushed)
        # 只有2只推送股票被统计
        assert result["fundamental"]["total"] == 2

    def test_empty_analysis(self):
        """空分析列表"""
        result = analyze_dimension_performance([])
        assert result == {}

    def test_multiple_hit_miss(self):
        """多个命中/未命中记录"""
        analysis = [
            {"code": "A", "scores": {"fundamental": 50}, "hit": True},
            {"code": "B", "scores": {"fundamental": 70}, "hit": True},
            {"code": "C", "scores": {"fundamental": 20}, "hit": False},
            {"code": "D", "scores": {"fundamental": 10}, "hit": False},
        ]
        result = analyze_dimension_performance(analysis)
        assert result["fundamental"]["hit_avg"] == 60.0  # (50+70)/2
        assert result["fundamental"]["miss_avg"] == 15.0  # (20+10)/2


# ===== confidence_distribution 测试 =====

class TestConfidenceDistribution:
    """测试置信度分布（现在只统计推送股票）"""

    def test_using_total_as_confidence(self):
        """无confidence字段时用total替代"""
        analysis = [
            {"code": "A", "total": 45},
            {"code": "B", "total": 30},
            {"code": "C", "total": 15},
        ]
        result = confidence_distribution(analysis)
        assert result["high"] == 1   # 45 >= 40
        assert result["medium"] == 1  # 30 >= 25
        assert result["low"] == 1     # 15 < 25

    def test_using_confidence_field(self):
        """有confidence字段时直接使用"""
        analysis = [
            {"code": "A", "confidence": 50, "total": 10},
            {"code": "B", "confidence": 35, "total": 10},
            {"code": "C", "confidence": 10, "total": 10},
        ]
        result = confidence_distribution(analysis)
        assert result["high"] == 1
        assert result["medium"] == 1
        assert result["low"] == 1

    def test_only_pushed_stocks(self):
        """验证只统计推送股票"""
        pushed = [
            {"code": "A", "total": 45},
            {"code": "B", "total": 15},
        ]
        result = confidence_distribution(pushed)
        assert result["high"] == 1
        assert result["low"] == 1
        assert result["medium"] == 0

    def test_empty_analysis(self):
        """空分析列表"""
        result = confidence_distribution([])
        assert result == {"high": 0, "medium": 0, "low": 0}

    def test_confidence_none_fallback(self):
        """confidence为None时回退到total"""
        analysis = [
            {"code": "A", "confidence": None, "total": 50},
        ]
        result = confidence_distribution(analysis)
        assert result["high"] == 1

    def test_boundary_values(self):
        """边界值测试"""
        analysis = [
            {"code": "A", "total": 40},  # high boundary
            {"code": "B", "total": 25},  # medium boundary
            {"code": "C", "total": 24.9},  # low
        ]
        result = confidence_distribution(analysis)
        assert result["high"] == 1
        assert result["medium"] == 1
        assert result["low"] == 1
