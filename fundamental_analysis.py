#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基本面分析评分脚本
评分依据：
1. PE/PB估值(低估值加分): PE<行业均值+10分, PB<1+10分
2. 净利润增长率(增长加分): YoY>20%+15分, YoY<0扣15分
3. ROE水平: ROE>15%+15分, ROE<5%扣10分
4. 营收增长: YoY>15%+10分
"""

import requests
import json
import pandas as pd
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv('/Users/zhangying/projects/study/maneki-agent/.env')
TUSHARE_TOKEN = os.getenv('TUSHARE_TOKEN')

# 候选股票列表
STOCKS = [
    ('002971', '和远气体'),
    ('603615', '茶花股份'),
    ('603767', '中马传动'),
    ('600130', '波导股份'),
    ('603070', '万控智造'),
    ('000404', '长虹华意'),
    ('605006', '山东玻纤'),
    ('603291', '联合水务'),
    ('603125', '常青科技'),
    ('001376', '百通能源'),
    ('600828', '茂业商业'),
    ('001266', '宏英智能'),
    ('600533', '栖霞建设'),
    ('002146', '荣盛发展'),
    ('002887', '绿茵生态'),
    ('601866', '中远海发'),
    ('603683', '晶华新材'),
    ('600538', '国发股份'),
    ('002066', '瑞泰科技'),
    ('600825', '新华传媒'),
    ('001322', '箭牌家居'),
    ('600606', '绿地控股'),
    ('600939', '重庆建工'),
    ('002210', '飞马国际'),
    ('600881', '亚泰集团'),
    ('000710', '贝瑞基因'),
    ('600400', '红豆股份'),
    ('603344', '星德胜'),
    ('603685', '晨丰科技'),
    ('000882', '华联股份'),
    ('603178', '圣龙股份'),
    ('600198', '大唐电信'),
]

def call_tushare(api_name, params):
    """调用Tushare API"""
    url = 'https://api.tushare.pro'
    headers = {'Content-Type': 'application/json'}
    data = {
        'api_name': api_name,
        'token': TUSHARE_TOKEN,
        'params': params,
        'fields': ''
    }
    try:
        response = requests.post(url, headers=headers, data=json.dumps(data), timeout=30)
        result = response.json()
        if result.get('code') != 0:
            print(f"API错误: {api_name} - {result.get('msg')}")
            return None
        return result.get('data', {})
    except Exception as e:
        print(f"API调用异常: {api_name} - {e}")
        return None

def get_daily_basic_single(ts_code, trade_date):
    """获取单只股票每日基本面数据"""
    data = call_tushare('daily_basic', {
        'ts_code': ts_code,
        'trade_date': trade_date
    })
    if data and 'fields' in data and 'items' in data:
        items = data.get('items', [])
        if items:
            fields = data.get('fields', [])
            return dict(zip(fields, items[0]))
    return None

def get_fina_indicator_single(ts_code, period):
    """获取单只股票财务指标数据"""
    data = call_tushare('fina_indicator', {
        'ts_code': ts_code,
        'period': period
    })
    if data and 'fields' in data and 'items' in data:
        items = data.get('items', [])
        if items:
            fields = data.get('fields', [])
            return dict(zip(fields, items[0]))
    return None

def get_latest_trade_date():
    """获取最近交易日"""
    today = datetime.now()
    data = call_tushare('trade_cal', {
        'exchange': 'SSE',
        'start_date': (today - timedelta(days=15)).strftime('%Y%m%d'),
        'end_date': today.strftime('%Y%m%d'),
        'is_open': '1'
    })
    if data and 'items' in data:
        items = data.get('items', [])
        if items:
            # 返回最近的交易日
            return items[-1][1]  # cal_date字段
    return (today - timedelta(days=1)).strftime('%Y%m%d')

def calculate_score(code, name, basic_data, fina_data, market_pe=25):
    """计算单只股票的基本面评分"""
    score = 50  # 基础分
    reasons = []
    
    ts_code = f"{code}.SH" if code.startswith('6') else f"{code}.SZ"
    
    # 1. PE估值评分
    if basic_data:
        pe = basic_data.get('pe')
        if pe is not None and pe != '' and pd.notna(pe):
            try:
                pe = float(pe)
                if pe > 0:  # 盈利公司
                    if pe < market_pe * 0.8:  # PE低于市场均值80%
                        score += 10
                        reasons.append(f"PE({pe:.2f})低于市场均值({market_pe:.2f})+10分")
                    elif pe < market_pe:
                        score += 5
                        reasons.append(f"PE({pe:.2f})接近市场均值+5分")
                    elif pe < 30:
                        score += 3
                        reasons.append(f"PE({pe:.2f})合理+3分")
                    else:
                        reasons.append(f"PE({pe:.2f})偏高，不加分")
                else:
                    reasons.append(f"PE({pe:.2f})亏损/负值，不加分")
            except:
                reasons.append("PE数据解析失败")
        
        # 2. PB估值评分
        pb = basic_data.get('pb')
        if pb is not None and pb != '' and pd.notna(pb):
            try:
                pb = float(pb)
                if pb > 0:
                    if pb < 1:
                        score += 10
                        reasons.append(f"PB({pb:.2f})<1+10分")
                    elif pb < 1.5:
                        score += 7
                        reasons.append(f"PB({pb:.2f})<1.5+7分")
                    elif pb < 2:
                        score += 5
                        reasons.append(f"PB({pb:.2f})<2+5分")
                    else:
                        reasons.append(f"PB({pb:.2f})偏高，不加分")
                else:
                    reasons.append(f"PB({pb:.2f})负值，不加分")
            except:
                reasons.append("PB数据解析失败")
    else:
        reasons.append("无PE/PB数据")
    
    # 财务指标评分
    if fina_data:
        # ROE
        roe = fina_data.get('roe') or fina_data.get('roe_waa')  # 加权ROE
        if roe is not None and roe != '' and pd.notna(roe):
            try:
                roe = float(roe)
                if roe > 15:
                    score += 15
                    reasons.append(f"ROE({roe:.2f}%)>15%+15分")
                elif roe > 10:
                    score += 10
                    reasons.append(f"ROE({roe:.2f}%)>10%+10分")
                elif roe > 5:
                    score += 5
                    reasons.append(f"ROE({roe:.2f}%)>5%+5分")
                elif roe < 5:
                    score -= 10
                    reasons.append(f"ROE({roe:.2f}%)<5%-10分")
            except:
                pass
        
        # 净利润增长率(YoY) - profit_yoy或q_profit_yoy
        profit_yoy = fina_data.get('profit_yoy') or fina_data.get('q_profit_yoy') or fina_data.get('netprofit_yoy')
        if profit_yoy is not None and profit_yoy != '' and pd.notna(profit_yoy):
            try:
                profit_yoy = float(profit_yoy)
                if profit_yoy > 20:
                    score += 15
                    reasons.append(f"净利润增长率({profit_yoy:.2f}%)>20%+15分")
                elif profit_yoy > 10:
                    score += 8
                    reasons.append(f"净利润增长率({profit_yoy:.2f}%)>10%+8分")
                elif profit_yoy > 0:
                    score += 3
                    reasons.append(f"净利润增长率({profit_yoy:.2f}%)>0+3分")
                elif profit_yoy < 0:
                    score -= 15
                    reasons.append(f"净利润增长率({profit_yoy:.2f}%)<0%-15分")
            except:
                pass
        
        # 营收增长率
        or_yoy = fina_data.get('or_yoy') or fina_data.get('q_or_yoy')
        if or_yoy is not None and or_yoy != '' and pd.notna(or_yoy):
            try:
                or_yoy = float(or_yoy)
                if or_yoy > 15:
                    score += 10
                    reasons.append(f"营收增长率({or_yoy:.2f}%)>15%+10分")
                elif or_yoy > 10:
                    score += 5
                    reasons.append(f"营收增长率({or_yoy:.2f}%)>10%+5分")
                elif or_yoy > 0:
                    score += 2
                    reasons.append(f"营收增长率({or_yoy:.2f}%)>0+2分")
                else:
                    reasons.append(f"营收增长率({or_yoy:.2f}%)负增长，不加分")
            except:
                pass
    else:
        reasons.append("无财务指标数据")
    
    # 限制分数范围
    score = max(0, min(100, score))
    
    reason_str = '; '.join(reasons)
    return ts_code, score, reason_str

def main():
    print("=" * 80)
    print("基本面分析评分报告")
    print("=" * 80)
    
    # 获取最近交易日
    print("\n正在获取最近交易日...")
    trade_date = get_latest_trade_date()
    print(f"使用交易日: {trade_date}")
    
    # 市场平均PE (使用固定值，因为实际市场PE波动较大)
    market_pe = 25  # A股市场平均PE约25倍
    
    print(f"\n开始获取{len(STOCKS)}只股票的基本面数据...")
    
    results = []
    
    # 确定财报期
    today = datetime.now()
    current_year = today.year
    month = today.month
    
    # 根据当前月份确定最近可用财报期
    if month >= 11:
        periods = [f"{current_year}0930", f"{current_year}0630", f"{current_year-1}1231"]
    elif month >= 9:
        periods = [f"{current_year}0630", f"{current_year-1}1231", f"{current_year-1}0930"]
    elif month >= 5:
        periods = [f"{current_year-1}1231", f"{current_year-1}0930", f"{current_year-1}0630"]
    else:
        periods = [f"{current_year-1}0930", f"{current_year-1}0630", f"{current_year-2}1231"]
    
    for i, (code, name) in enumerate(STOCKS):
        ts_code = f"{code}.SH" if code.startswith('6') else f"{code}.SZ"
        print(f"\n[{i+1}/{len(STOCKS)}] 处理 {name}({ts_code})...")
        
        # 获取daily_basic数据
        basic_data = None
        for days in range(0, 15):
            date = (datetime.strptime(trade_date, '%Y%m%d') - timedelta(days=days)).strftime('%Y%m%d')
            basic_data = get_daily_basic_single(ts_code, date)
            if basic_data:
                print(f"  获取到{date}的PE/PB数据")
                break
        
        # 获取财务指标
        fina_data = None
        for period in periods:
            fina_data = get_fina_indicator_single(ts_code, period)
            if fina_data:
                print(f"  获取到{period}的财务指标")
                break
        
        # 计算评分
        ts_code_result, score, reason = calculate_score(code, name, basic_data, fina_data, market_pe)
        results.append((code, name, score, reason))
        print(f"  评分: {score}分")
    
    # 按分数排序
    results.sort(key=lambda x: x[2], reverse=True)
    
    # 输出结果
    print("\n" + "=" * 80)
    print("评分结果(按分数从高到低排序)")
    print("=" * 80)
    
    for code, name, score, reason in results:
        print(f"\n{name}({code}): {score}分")
        print(f"  {reason}")
    
    print("\n" + "=" * 80)
    print("评分汇总表")
    print("=" * 80)
    print(f"{'排名':<5}{'代码':<8}{'名称':<10}{'评分':<8}{'评级'}")
    print("-" * 50)
    
    for i, (code, name, score, reason) in enumerate(results, 1):
        if score >= 80:
            rating = "优秀"
        elif score >= 65:
            rating = "良好"
        elif score >= 50:
            rating = "一般"
        else:
            rating = "较差"
        print(f"{i:<5}{code:<8}{name:<10}{score:<8}{rating}")
    
    # 保存结果到文件
    output_file = '/Users/zhangying/projects/study/maneki-agent/fundamental_analysis_result.txt'
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("基本面分析评分报告\n")
        f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"数据日期: {trade_date}\n")
        f.write("=" * 80 + "\n\n")
        
        f.write("评分依据:\n")
        f.write("1. PE/PB估值(低估值加分): PE<市场均值(25倍)+10分, PB<1+10分\n")
        f.write("2. 净利润增长率: YoY>20%+15分, YoY<0扣15分\n")
        f.write("3. ROE水平: ROE>15%+15分, ROE<5%扣10分\n")
        f.write("4. 营收增长: YoY>15%+10分\n\n")
        
        f.write("=" * 80 + "\n")
        f.write("详细评分结果\n")
        f.write("=" * 80 + "\n")
        
        for code, name, score, reason in results:
            f.write(f"\n{name}({code}): {score}分\n")
            f.write(f"  评分理由: {reason}\n")
        
        f.write("\n" + "=" * 80 + "\n")
        f.write("评分汇总表\n")
        f.write("=" * 80 + "\n")
        f.write(f"{'排名':<5}{'代码':<8}{'名称':<10}{'评分':<8}{'评级'}\n")
        f.write("-" * 50 + "\n")
        
        for i, (code, name, score, reason) in enumerate(results, 1):
            if score >= 80:
                rating = "优秀"
            elif score >= 65:
                rating = "良好"
            elif score >= 50:
                rating = "一般"
            else:
                rating = "较差"
            f.write(f"{i:<5}{code:<8}{name:<10}{score:<8}{rating}\n")
    
    print(f"\n结果已保存到: {output_file}")

if __name__ == '__main__':
    main()
