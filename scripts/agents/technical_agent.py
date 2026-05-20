#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
技术面涨停潜力预判Agent V1.0
基于五维度量化评分体系：
1. 量能结构维度 40分（涨停第一驱动力）
2. 趋势与均线维度 25分（行情骨架）
3. 关键位置形态维度 12分（起爆临界点）
4. 筹码结构维度 15分（连板持续性核心）
5. 资金与盘口维度 8分（日内起爆信号）

含一票否决规则（风控底线）
"""

import os
import sys
import json
import datetime
import requests
from typing import Tuple, Dict, List, Optional

# 项目路径
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_DIR, '.env'))

TUSHARE_TOKEN = os.getenv('TUSHARE_TOKEN')


def call_tushare(api_name: str, params: dict, fields: str = '') -> Optional[dict]:
    """调用Tushare REST API"""
    url = 'https://api.tushare.pro'
    headers = {'Content-Type': 'application/json'}
    data = {
        'api_name': api_name,
        'token': TUSHARE_TOKEN,
        'params': params,
        'fields': fields
    }
    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
        result = response.json()
        if result.get('code') != 0:
            return None
        return result.get('data', {})
    except Exception as e:
        return None


def get_daily_data(ts_code: str, days: int = 30) -> List[dict]:
    """获取日线行情数据（最近N天）"""
    today = datetime.datetime.now()
    end_date = today.strftime('%Y%m%d')
    start_date = (today - datetime.timedelta(days=days*2)).strftime('%Y%m%d')  # 多取一些确保有足够交易日
    
    data = call_tushare('daily', {'ts_code': ts_code, 'start_date': start_date, 'end_date': end_date},
                        'trade_date,open,high,low,close,pre_close,pct_chg,vol,amount')
    
    if not data or 'items' not in data:
        return []
    
    fields = data.get('fields', [])
    items = data.get('items', [])
    
    # 按日期降序排列
    result = [dict(zip(fields, item)) for item in items]
    result.sort(key=lambda x: x.get('trade_date', ''), reverse=True)
    return result[:days]


def get_factor_data(ts_code: str, days: int = 30) -> List[dict]:
    """获取技术因子数据（stk_factor_pro）"""
    today = datetime.datetime.now()
    end_date = today.strftime('%Y%m%d')
    start_date = (today - datetime.timedelta(days=days*2)).strftime('%Y%m%d')
    
    # 使用不复权字段
    fields = ('trade_date,close,open,high,low,pre_close,change,pct_change,vol,amount,'
              'vol_ratio,turnover_rate,ma_bfq_5,ma_bfq_10,ma_bfq_20,ma_bfq_60,'
              'macd_dif_bfq,macd_dea_bfq,macd_bfq,kdj_k_bfq,kdj_d_bfq,kdj_bfq,'
              'rsi_bfq_6,boll_upper_bfq,boll_mid_bfq,boll_lower_bfq')
    
    data = call_tushare('stk_factor_pro', {'ts_code': ts_code, 'start_date': start_date, 'end_date': end_date}, fields)
    
    if not data or 'items' not in data:
        return []
    
    result = [dict(zip(data.get('fields', []), item)) for item in data.get('items', [])]
    result.sort(key=lambda x: x.get('trade_date', ''), reverse=True)
    return result[:days]


def get_daily_basic(ts_code: str, trade_date: str = None) -> Optional[dict]:
    """获取每日基本面数据"""
    params = {'ts_code': ts_code}
    if trade_date:
        params['trade_date'] = trade_date
    
    data = call_tushare('daily_basic', params, 'trade_date,turnover_rate,volume_ratio,total_mv,circ_mv')
    
    if not data or 'items' not in data or not data['items']:
        return None
    
    return dict(zip(data.get('fields', []), data['items'][0]))


def get_moneyflow(ts_code: str, days: int = 3) -> List[dict]:
    """获取资金流向数据（T+1滞后）"""
    today = datetime.datetime.now()
    end_date = today.strftime('%Y%m%d')
    start_date = (today - datetime.timedelta(days=days*3)).strftime('%Y%m%d')
    
    data = call_tushare('moneyflow', {'ts_code': ts_code, 'start_date': start_date, 'end_date': end_date},
                        'trade_date,buy_elg_vol,buy_elg_amount,sell_elg_vol,sell_elg_amount,'
                        'net_mf_vol,net_mf_amount,buy_lg_amount,sell_lg_amount')
    
    if not data or 'items' not in data:
        return []
    
    result = [dict(zip(data.get('fields', []), item)) for item in data.get('items', [])]
    result.sort(key=lambda x: x.get('trade_date', ''), reverse=True)
    return result[:days]


# ============ 一票否决规则 ============

def check_veto_rules(factor_data: List[dict], daily_data: List[dict], moneyflow_data: List[dict]) -> Tuple[bool, List[str]]:
    """
    一票否决规则检查
    触发任意一条直接判定涨停预测：否
    """
    if len(factor_data) < 2:
        return False, ["数据不足"]
    
    veto_flags = []
    today = factor_data[0]
    yesterday = factor_data[1] if len(factor_data) > 1 else {}
    
    # 1. 放量破位：收盘价跌破20日线，且成交量 > 1.8倍近20日均量
    close = safe_float(today.get('close'))
    ma20 = safe_float(today.get('ma_bfq_20'))
    vol = safe_float(today.get('vol'))
    # 计算20日均量（简化：用换手率判断）
    turnover = safe_float(today.get('turnover_rate'))
    
    if close and ma20 and close < ma20:
        # 用量比判断放量：量比>1.8视为放量
        vol_ratio = safe_float(today.get('vol_ratio'))
        if vol_ratio and vol_ratio > 1.8:
            veto_flags.append(f"放量破位:收盘{close:.2f}<MA20={ma20:.2f},量比{vol_ratio:.2f}>1.8")
    
    # 2. 高位滞涨：阶段涨幅>60%，换手率>25%，长上影（上影线/实体>1.5）
    # 计算阶段涨幅（近20日）
    if len(daily_data) >= 20:
        high_20d = max(safe_float(d.get('high', 0)) for d in daily_data[:20])
        low_20d = min(safe_float(d.get('low', float('inf'))) for d in daily_data[:20])
        if low_20d > 0:
            stage_gain = (high_20d - low_20d) / low_20d * 100
        else:
            stage_gain = 0
    else:
        stage_gain = 0
    
    open_price = safe_float(today.get('open'))
    high_price = safe_float(today.get('high'))
    low_price = safe_float(today.get('low'))
    
    if stage_gain > 60 and turnover and turnover > 25:
        # 检查长上影
        if close and open_price and high_price:
            upper_shadow = high_price - max(close, open_price)
            body = abs(close - open_price)
            if body > 0 and upper_shadow / body > 1.5:
                veto_flags.append(f"高位滞涨:阶段涨幅{stage_gain:.1f}%,换手{turnover:.1f}%,长上影")
    
    # 3. 筹码高位发散：BOLL带宽>50%视为极端发散（V1.1: 从30%放宽至50%）
    boll_upper = safe_float(today.get('boll_upper_bfq'))
    boll_lower = safe_float(today.get('boll_lower_bfq'))
    boll_mid = safe_float(today.get('boll_mid_bfq'))
    
    if boll_upper and boll_lower and boll_mid and boll_mid > 0:
        boll_width = (boll_upper - boll_lower) / boll_mid * 100
        if boll_width > 50:  # V1.1: 从30放宽至50
            veto_flags.append(f"筹码发散:布林带宽{boll_width:.1f}%>50%")
    
    # 4. 持续缩量阴跌：连续3日量比<0.3且累计跌幅>3%（V1.1: 从量比<0.5放宽至<0.3，新增跌幅>3%）
    if len(factor_data) >= 3:
        vol_ratios = [safe_float(factor_data[i].get('vol_ratio')) for i in range(3)]
        pct_changes = [safe_float(factor_data[i].get('pct_change')) for i in range(3)]
        
        valid_vr = [vr for vr in vol_ratios if vr]
        valid_pc = [pc for pc in pct_changes if pc]
        if len(valid_vr) == 3 and all(vr < 0.3 for vr in valid_vr):
            if len(valid_pc) == 3 and sum(valid_pc) < -3:
                veto_flags.append(f"持续缩量阴跌:3日量比均<0.3,累计跌{sum(valid_pc):.1f}%>3%")
    
    # 5. 资金持续出逃：近2日主力净流入累计为负
    if len(moneyflow_data) >= 2:
        net_mf_2d = sum(safe_float(d.get('net_mf_amount', 0)) for d in moneyflow_data[:2])
        if net_mf_2d < 0:
            # 分时承接强度简化判断：收盘价/均价
            if boll_mid and close and close < boll_mid * 0.98:
                veto_flags.append(f"资金持续出逃:近2日净流出{net_mf_2d:.2f}万,跌破均价")
    
    return len(veto_flags) > 0, veto_flags


# ============ 五维度评分 ============

def safe_float(val) -> Optional[float]:
    """安全转换为float"""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def calc_volume_score(factor_data: List[dict], daily_basic: Optional[dict]) -> Tuple[float, List[str]]:
    """
    维度1：量能结构（40分）
    - 量比启动：量比∈[1.8,4.0] +15分
    - 温和放量：量>3日均量1.3倍且<20日均量2.5倍 +15分
    - 洗盘起爆：前2日缩量+当日放量 +10分
    - 换手健康：换手率∈[3%,12%] +10分
    """
    if len(factor_data) < 3:
        return 0, ["量能数据不足"]
    
    score = 0
    reasons = []
    
    today = factor_data[0]
    yesterday = factor_data[1]
    day_before = factor_data[2]
    
    # 量比
    vol_ratio = safe_float(today.get('vol_ratio'))
    if vol_ratio:
        if 1.8 <= vol_ratio <= 4.0:
            score += 15
            reasons.append(f"量比={vol_ratio:.2f}∈[1.8,4.0]+15分")
        elif vol_ratio < 1.5:
            # V1.1: 量比<1.5不再扣分，仅不加分
            reasons.append(f"量比={vol_ratio:.2f}<1.5缩量(不加分)")
        elif vol_ratio > 6.0:
            # V1.1: 异常放量扣5分而非0分
            score -= 5
            reasons.append(f"量比={vol_ratio:.2f}>6.0异常放量-5分")
    
    # 换手率 (V1.1: 无量拉升扣5分而非10分；暴量扣10分而非15分)
    turnover = safe_float(today.get('turnover_rate'))
    if turnover:
        if 3 <= turnover <= 12:
            score += 10
            reasons.append(f"换手率={turnover:.2f}%∈[3%,12%]+10分")
        elif turnover < 1.5:
            score -= 5
            reasons.append(f"换手率={turnover:.2f}%无量拉升-5分")
        elif turnover > 20:
            score -= 10
            reasons.append(f"换手率={turnover:.2f}%高位暴量-10分")
    
    # 洗盘-起爆节奏：前2日缩量+当日放量
    vol_ratio_yest = safe_float(yesterday.get('vol_ratio'))
    vol_ratio_before = safe_float(day_before.get('vol_ratio'))
    
    if vol_ratio_yest and vol_ratio_before and vol_ratio:
        if vol_ratio_yest < 0.8 and vol_ratio_before < 0.8 and vol_ratio >= 1.5:
            score += 10
            reasons.append(f"洗盘起爆:前2日缩量+当日量比{vol_ratio:.2f}+10分")
    
    # 温和放量判断（简化：量比在合理区间）
    if vol_ratio and 1.3 <= vol_ratio <= 2.5:
        score += 5
        reasons.append(f"温和放量:量比{vol_ratio:.2f}+5分")
    
    return min(40, max(0, score)), reasons


def calc_trend_score(factor_data: List[dict]) -> Tuple[float, List[str]]:
    """
    维度2：趋势与均线（25分）
    - 多头排列：MA5>MA10>MA20且斜率向上 +15分
    - 回踩企稳：近5日最低价触及10/20日线后站回 +10分
    """
    if len(factor_data) < 5:
        return 0, ["趋势数据不足"]
    
    score = 0
    reasons = []
    
    today = factor_data[0]
    
    ma5 = safe_float(today.get('ma_bfq_5'))
    ma10 = safe_float(today.get('ma_bfq_10'))
    ma20 = safe_float(today.get('ma_bfq_20'))
    ma60 = safe_float(today.get('ma_bfq_60'))
    close = safe_float(today.get('close'))
    
    # 多头排列
    if ma5 and ma10 and ma20:
        if ma5 > ma10 > ma20:
            score += 15
            reasons.append(f"均线多头排列:MA5={ma5:.2f}>MA10={ma10:.2f}>MA20={ma20:.2f}+15分")
        elif ma5 < ma10 < ma20:
            score -= 10  # V1.1: 从15降至10
            # V1.1: 空头排列扣10分而非15分
            reasons.append(f"均线空头排列:MA5={ma5:.2f}<MA10={ma10:.2f}<MA20={ma20:.2f}-10分")
        else:
            reasons.append(f"均线交织:MA5={ma5:.2f},MA10={ma10:.2f},MA20={ma20:.2f}")
    
    # 60日线方向
    if ma60:
        # 用近期数据判断60日线斜率
        if len(factor_data) >= 5:
            ma60_5d_ago = safe_float(factor_data[4].get('ma_bfq_60'))
            if ma60_5d_ago and ma60 < ma60_5d_ago:
                score -= 5  # V1.1: 从10降至5
                # V1.1: MA60下倾扣5分而非10分
                reasons.append(f"MA60下倾-5分")
    
    # 回踩企稳：检查近5日最低价是否触及均线后站回
    if close and ma10 and ma20:
        low_5d = min(safe_float(factor_data[i].get('low', float('inf'))) or float('inf') for i in range(5))
        if low_5d <= ma10 * 1.01 and close > ma10:  # 触及10日线后站回
            score += 10
            reasons.append(f"回踩MA10后企稳+10分")
        elif low_5d <= ma20 * 1.01 and close > ma20:
            score += 10
            reasons.append(f"回踩MA20后企稳+10分")
    
    # 硬标准：收盘价必须>20日线
    if close and ma20:
        if close <= ma20:
            score -= 5
            reasons.append(f"收盘{close:.2f}<=MA20={ma20:.2f}弱势")
    
    return min(25, max(0, score)), reasons


def calc_position_score(factor_data: List[dict], daily_data: List[dict]) -> Tuple[float, List[str]]:
    """
    维度3：关键位置形态（12分）
    - 平台突破：横盘7~20日后放量突破 +8分
    - 支撑确认：回踩后缩量企稳 +4分
    """
    if len(factor_data) < 20:
        return 0, ["位置数据不足"]
    
    score = 0
    reasons = []
    
    today = factor_data[0]
    close = safe_float(today.get('close'))
    high = safe_float(today.get('high'))
    low = safe_float(today.get('low'))
    open_price = safe_float(today.get('open'))
    vol_ratio = safe_float(today.get('vol_ratio'))
    
    # 计算振幅
    if close and open_price and high and low:
        amplitude = (high - low) / open_price * 100 if open_price > 0 else 0
        
        # 平台突破判断：振幅>4%且放量
        if amplitude > 4 and vol_ratio and vol_ratio > 1.5:
            # 检查前7-20日是否横盘
            recent_highs = [safe_float(factor_data[i].get('high')) for i in range(1, 21)]
            recent_lows = [safe_float(factor_data[i].get('low')) for i in range(1, 21)]
            
            if recent_highs and recent_lows:
                box_high = max(h for h in recent_highs if h)
                box_low = min(l for l in recent_lows if l)
                box_range = (box_high - box_low) / box_low * 100 if box_low > 0 else 100
                
                # 横盘判断：箱体振幅<15%
                if box_range < 15 and close > box_high:
                    score += 8
                    reasons.append(f"平台突破:突破箱体上沿{box_high:.2f}+8分")
    
    # 支撑确认：下影线实体比<0.3
    if close and open_price and low:
        lower_shadow = min(close, open_price) - low
        body = abs(close - open_price)
        if body > 0 and lower_shadow / body < 0.3:
            score += 4
            reasons.append(f"下影线实体比<0.3缩量企稳+4分")
    
    # 负向：多次假突破（3日内上影线占比>60%）
    if len(factor_data) >= 3:
        upper_shadow_count = 0
        for i in range(3):
            d = factor_data[i]
            c = safe_float(d.get('close'))
            o = safe_float(d.get('open'))
            h = safe_float(d.get('high'))
            if c and o and h:
                us = h - max(c, o)
                body = abs(c - o)
                if body > 0 and us / body > 1:
                    upper_shadow_count += 1
        
        if upper_shadow_count >= 2:  # 3日中2日以上长上影
            score -= 12
            reasons.append(f"假突破形态:近3日{upper_shadow_count}日长上影-12分")
    
    return min(12, max(0, score)), reasons


def calc_chip_score(factor_data: List[dict]) -> Tuple[float, List[str]]:
    """
    维度4：筹码结构（15分）
    - 低位密集：集中度<12%，下方获利盘>70% +10分
    - 锁定良好：近5日筹码未发散 +5分
    
    注：Tushare无直接筹码分布数据，用布林带/VWAP偏离度代理
    """
    if len(factor_data) < 5:
        return 0, ["筹码数据不足"]
    
    score = 0
    reasons = []
    
    today = factor_data[0]
    
    # 用布林带宽度代理筹码集中度
    boll_upper = safe_float(today.get('boll_upper_bfq'))
    boll_lower = safe_float(today.get('boll_lower_bfq'))
    boll_mid = safe_float(today.get('boll_mid_bfq'))
    close = safe_float(today.get('close'))
    
    if boll_upper and boll_lower and boll_mid:
        # 布林带宽 = (上轨-下轨)/中轨
        boll_width = (boll_upper - boll_lower) / boll_mid * 100
        
        # 集中度判断：带宽<12%视为低位密集
        if boll_width < 12:
            score += 10
            reasons.append(f"筹码集中:布林带宽{boll_width:.1f}%<12%+10分")
        elif boll_width > 25:
            score -= 5  # V1.1: 从10降至5
            # V1.1: 筹码发散扣5分而非10分
            reasons.append(f"筹码发散:布林带宽{boll_width:.1f}%>25%-5分")
    
    # 用收盘价相对布林中轨位置代理获利盘
    if close and boll_mid:
        price_deviation = (close - boll_mid) / boll_mid * 100
        # 价格在中轨以上表示偏强势
        if price_deviation > 2:
            reasons.append(f"价格高于中轨{price_deviation:.1f}%")
        elif price_deviation < -5:
            score -= 5
            reasons.append(f"价格低于中轨{price_deviation:.1f}%弱势")
    
    # 近5日筹码是否发散
    if len(factor_data) >= 5:
        widths = []
        for i in range(5):
            d = factor_data[i]
            bu = safe_float(d.get('boll_upper_bfq'))
            bl = safe_float(d.get('boll_lower_bfq'))
            bm = safe_float(d.get('boll_mid_bfq'))
            if bu and bl and bm:
                widths.append((bu - bl) / bm * 100)
        
        if widths and len(widths) >= 5:
            # 检查是否扩大
            if widths[0] > widths[-1] * 1.3:  # 今日带宽比5日前大30%
                score -= 5
                reasons.append(f"筹码集中度扩大{(widths[0]-widths[-1])/widths[-1]*100:.1f}%")
            else:
                score += 5
                reasons.append(f"筹码锁定良好+5分")
    
    return min(15, max(0, score)), reasons


def calc_capital_score(factor_data: List[dict], moneyflow_data: List[dict]) -> Tuple[float, List[str]]:
    """
    维度5：资金与盘口（8分）
    - 订单失衡：主动买盘占比>55% +5分
    - 分时承接：收盘价/VWAP>1.01 +3分
    
    注：盘中实时数据用akshare，此处用T+1数据简化
    """
    score = 0
    reasons = []
    
    today = factor_data[0]
    close = safe_float(today.get('close'))
    boll_mid = safe_float(today.get('boll_mid_bfq'))  # 作为VWAP代理
    
    # 用布林中轨作为日内均价代理
    if close and boll_mid:
        price_vwap_ratio = close / boll_mid
        if price_vwap_ratio > 1.01:
            score += 3
            reasons.append(f"分时承接:收盘/VWAP={price_vwap_ratio:.3f}>1.01+3分")
        elif price_vwap_ratio < 0.98:
            score -= 3
            reasons.append(f"分时走弱:收盘/VWAP={price_vwap_ratio:.3f}<0.98-3分")
    
    # 资金流向（T+1数据）
    if moneyflow_data:
        latest = moneyflow_data[0]
        net_mf = safe_float(latest.get('net_mf_amount'))
        buy_lg = safe_float(latest.get('buy_lg_amount'))
        sell_lg = safe_float(latest.get('sell_lg_amount'))
        
        if net_mf and net_mf > 0:
            # 计算净流入比例
            total = (buy_lg or 0) + (sell_lg or 0)
            if total > 0:
                net_pct = net_mf / total * 100
                if net_pct > 5:
                    score += 5
                    reasons.append(f"主力净流入{net_pct:.1f}%+5分")
                elif net_pct > 2:
                    score += 3
                    reasons.append(f"主力净流入{net_pct:.1f}%+3分")
        elif net_mf and net_mf < 0:
            total = (buy_lg or 0) + (sell_lg or 0)
            if total > 0:
                net_pct = abs(net_mf) / total * 100
                if net_pct > 5:
                    score -= 8
                    reasons.append(f"主力净流出{net_pct:.1f}%-8分")
    
    return min(8, max(0, score)), reasons


# ============ 主评分函数 ============

def analyze_technical(ts_code: str, name: str = "") -> dict:
    """
    技术面涨停潜力预判 V1.0
    
    返回:
    {
        "ts_code": "002971.SZ",
        "name": "和远气体",
        "limit_up_prediction": "是/否",
        "total_score": 75,
        "level": "高/中/低/无",
        "veto_flags": [],
        "dimension_scores": {
            "volume": {"score": 35, "reasons": [...]},
            "trend": {"score": 20, "reasons": [...]},
            "position": {"score": 10, "reasons": [...]},
            "chip": {"score": 12, "reasons": [...]},
            "capital": {"score": 6, "reasons": [...]}
        },
        "core_logic": ["量比=2.6,换手率=7.2%...", ...],
        "risks": ["临近前高压力区...", ...],
        "conclusion": "具备短线起爆潜力，建议仓位5%，止损位..."
    }
    """
    result = {
        "ts_code": ts_code,
        "name": name,
        "limit_up_prediction": "否",
        "total_score": 0,
        "level": "无",
        "veto_flags": [],
        "dimension_scores": {},
        "core_logic": [],
        "risks": [],
        "conclusion": ""
    }
    
    # 获取数据
    factor_data = get_factor_data(ts_code, days=30)
    daily_data = get_daily_data(ts_code, days=30)
    daily_basic = get_daily_basic(ts_code)
    moneyflow_data = get_moneyflow(ts_code, days=3)
    
    if len(factor_data) < 3:
        result["risks"].append("技术数据不足")
        result["conclusion"] = "数据不足，无法分析"
        return result
    
    # 1. 一票否决检查
    is_vetoed, veto_flags = check_veto_rules(factor_data, daily_data, moneyflow_data)
    result["veto_flags"] = veto_flags
    
    if is_vetoed:
        result["limit_up_prediction"] = "否"
        result["level"] = "无"
        result["risks"] = veto_flags
        result["conclusion"] = f"触发风控否决: {'; '.join(veto_flags)}"
        return result
    
    # 2. 五维度评分
    volume_score, volume_reasons = calc_volume_score(factor_data, daily_basic)
    trend_score, trend_reasons = calc_trend_score(factor_data)
    position_score, position_reasons = calc_position_score(factor_data, daily_data)
    chip_score, chip_reasons = calc_chip_score(factor_data)
    capital_score, capital_reasons = calc_capital_score(factor_data, moneyflow_data)
    
    result["dimension_scores"] = {
        "volume": {"score": volume_score, "weight": 40, "reasons": volume_reasons},
        "trend": {"score": trend_score, "weight": 25, "reasons": trend_reasons},
        "position": {"score": position_score, "weight": 12, "reasons": position_reasons},
        "chip": {"score": chip_score, "weight": 15, "reasons": chip_reasons},
        "capital": {"score": capital_score, "weight": 8, "reasons": capital_reasons}
    }
    
    # 3. 计算总分
    total = volume_score + trend_score + position_score + chip_score + capital_score
    result["total_score"] = total
    
    # 4. 核心逻辑汇总
    core_logic = []
    if volume_reasons:
        core_logic.append(f"[量能] {'; '.join(volume_reasons)}")
    if trend_reasons:
        core_logic.append(f"[趋势] {'; '.join(trend_reasons)}")
    if chip_reasons:
        core_logic.append(f"[筹码] {'; '.join(chip_reasons)}")
    if position_reasons:
        core_logic.append(f"[位置] {'; '.join(position_reasons)}")
    if capital_reasons:
        core_logic.append(f"[资金] {'; '.join(capital_reasons)}")
    result["core_logic"] = core_logic
    
    # 5. 风险隐患
    risks = []
    # 高位压力
    if len(daily_data) >= 20:
        high_20d = max(safe_float(d.get('high', 0)) or 0 for d in daily_data[:20])
        close = safe_float(factor_data[0].get('close'))
        if close and high_20d and close > high_20d * 0.95:
            risks.append(f"临近前高压力区{high_20d:.2f}")
    
    # 换手率预警
    turnover = safe_float(factor_data[0].get('turnover_rate'))
    if turnover and turnover > 10:
        risks.append(f"换手率{turnover:.1f}%较高，警惕分歧")
    
    # 均线风险
    ma20 = safe_float(factor_data[0].get('ma_bfq_20'))
    close = safe_float(factor_data[0].get('close'))
    if close and ma20:
        if close < ma20 * 1.05:
            risks.append(f"接近MA20={ma20:.2f}支撑")
    
    result["risks"] = risks
    
    # 6. 涨停潜力等级
    if total >= 70:
        result["level"] = "高"
        result["limit_up_prediction"] = "是"
    elif total >= 50:
        result["level"] = "中"
        result["limit_up_prediction"] = "观察"
    elif total >= 30:
        result["level"] = "低"
        result["limit_up_prediction"] = "否"
    else:
        result["level"] = "无"
        result["limit_up_prediction"] = "否"
    
    # 7. 结论
    if result["limit_up_prediction"] == "是":
        result["conclusion"] = (
            f"具备短线起爆潜力，综合得分{total}分。"
            f"建议仓位5%，止损位：跌破MA20({ma20:.2f}附近)且放量。"
            f"重点跟踪14:00后分时承接与板块联动。"
        )
    elif result["limit_up_prediction"] == "观察":
        result["conclusion"] = (
            f"中等潜力，综合得分{total}分。单一维度强共振，可列入观察池。"
            f"关注后续量能变化与板块轮动。"
        )
    else:
        result["conclusion"] = f"涨停潜力{result['level']}，综合得分{total}分。{'; '.join(risks) if risks else '技术面支撑不足'}"
    
    return result


# ============ CLI 入口 ============

def main():
    """命令行入口"""
    import argparse
    parser = argparse.ArgumentParser(description='技术面涨停潜力预判Agent V1.0')
    parser.add_argument('--code', type=str, help='股票代码，如002971.SZ')
    parser.add_argument('--name', type=str, default='', help='股票名称')
    parser.add_argument('--file', type=str, help='从候选文件读取股票列表')
    args = parser.parse_args()
    
    if args.file:
        # 从文件读取
        with open(args.file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if isinstance(data, dict) and 'stocks' in data:
            stocks = data['stocks']
        elif isinstance(data, list):
            stocks = data
        else:
            print("无法解析文件格式")
            return
        
        results = []
        for s in stocks[:10]:  # 限制前10只
            code = s.get('代码') or s.get('code') or s.get('ts_code', '')
            name = s.get('名称') or s.get('name', '')
            if '.' not in code:
                code = f"{code}.SZ" if code.startswith(('0', '3')) else f"{code}.SH"
            
            print(f"分析 {code} {name}...")
            r = analyze_technical(code, name)
            results.append(r)
            print(f"  评分: {r['total_score']}分, 等级: {r['level']}")
        
        # 保存结果
        output_file = os.path.join(PROJECT_DIR, 'data', 'analysis', 'technical_results.json')
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump({
                "agent": "技术面分析V1.0",
                "trade_date": datetime.datetime.now().strftime('%Y%m%d'),
                "results": results
            }, f, ensure_ascii=False, indent=2)
        print(f"\n结果已保存: {output_file}")
    
    elif args.code:
        r = analyze_technical(args.code, args.name)
        print(json.dumps(r, ensure_ascii=False, indent=2))
    
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
