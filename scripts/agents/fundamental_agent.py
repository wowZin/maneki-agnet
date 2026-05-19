#!/usr/bin/env python3
"""基本面分析Agent - 使用Tushare API分析股票基本面"""
import os
import sys
import json
import datetime

# 设置环境
sys.path.insert(0, '/Users/zhangying/.hermes/hermes-agent/venv/lib/python3.11/site-packages')
os.chdir('/Users/zhangying/projects/study/maneki-agent')

import tushare as ts
from dotenv import load_dotenv

load_dotenv('/Users/zhangying/projects/study/maneki-agent/.env')

# 初始化Tushare
ts.set_token(os.getenv('TUSHARE_TOKEN'))
pro = ts.pro_api()

# 读取候选股票
with open('/Users/zhangying/projects/study/maneki-agent/data/signals/20260518_candidates.json', 'r') as f:
    data = json.load(f)

stocks = data['stocks']
trade_date = data['trade_date']

print(f"基本面分析Agent - 分析{len(stocks)}只股票")
print(f"数据日期: {trade_date}")
print("=" * 60)

# 获取前10只股票进行分析（控制API调用次数）
top_stocks = stocks[:10]
results = {}

for stock in top_stocks:
    code = stock['代码']
    name = stock['名称']
    score = 50  # 基础分
    reasons = []
    
    print(f"\n分析 {code} {name}...")
    
    try:
        # 1. 获取基本面数据 (daily_basic)
        basic = pro.daily_basic(ts_code=code + '.SZ' if code.startswith('0') or code.startswith('3') else code + '.SH',
                                 trade_date=trade_date, fields='pe,pb,pe_ttm,total_mv,circ_mv')
        
        if not basic.empty:
            row = basic.iloc[0]
            pe = row.get('pe')
            pb = row.get('pb')
            
            # PE估值评分
            if pe and pe > 0:
                if pe < 20:
                    score += 10
                    reasons.append(f"PE={pe:.1f}低估值+10分")
                elif pe > 50:
                    score -= 5
                    reasons.append(f"PE={pe:.1f}高估值-5分")
            
            # PB估值评分
            if pb and pb > 0:
                if pb < 1:
                    score += 10
                    reasons.append(f"PB={pb:.2f}破净+10分")
                elif pb < 2:
                    score += 5
                    reasons.append(f"PB={pb:.2f}低估值+5分")
        
        # 2. 获取财务指标 (fina_indicator)
        try:
            fina = pro.fina_indicator(ts_code=code + '.SZ' if code.startswith('0') or code.startswith('3') else code + '.SH',
                                       fields='end_date,roe,roedt,profit_dedt,yoy_profit,yoy_sales')
            if not fina.empty:
                latest = fina.iloc[0]
                
                # ROE评分
                roe = latest.get('roe')
                if roe:
                    if roe > 15:
                        score += 15
                        reasons.append(f"ROE={roe:.1f}%优秀+15分")
                    elif roe > 10:
                        score += 10
                        reasons.append(f"ROE={roe:.1f}%良好+10分")
                    elif roe < 5:
                        score -= 10
                        reasons.append(f"ROE={roe:.1f}%偏低-10分")
                
                # 净利润增长率
                yoy_profit = latest.get('yoy_profit')
                if yoy_profit:
                    if yoy_profit > 20:
                        score += 15
                        reasons.append(f"净利润YoY={yoy_profit:.1f}%高增长+15分")
                    elif yoy_profit < 0:
                        score -= 15
                        reasons.append(f"净利润YoY={yoy_profit:.1f}%下滑-15分")
                
                # 营收增长
                yoy_sales = latest.get('yoy_sales')
                if yoy_sales:
                    if yoy_sales > 15:
                        score += 10
                        reasons.append(f"营收YoY={yoy_sales:.1f}%增长+10分")
        except Exception as e:
            print(f"  财务数据获取失败: {e}")
        
        # 确保分数在0-100范围内
        score = max(0, min(100, score))
        
    except Exception as e:
        print(f"  基本面数据获取失败: {e}")
        score = 50
        reasons.append("数据获取失败，默认50分")
    
    results[code] = {
        "name": name,
        "score": score,
        "reasons": reasons
    }
    print(f"  评分: {score}分")
    print(f"  理由: {'; '.join(reasons)}")

# 保存结果
output = {
    "agent": "基本面分析",
    "trade_date": trade_date,
    "results": results
}

out_file = '/Users/zhangying/projects/study/maneki-agent/data/analysis/fundamental_results.json'
os.makedirs(os.path.dirname(out_file), exist_ok=True)
with open(out_file, 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"\n结果已保存: {out_file}")
