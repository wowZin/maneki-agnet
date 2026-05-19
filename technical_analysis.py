import tushare as ts
import os
from dotenv import load_dotenv
import json

# 加载环境变量
load_dotenv('/Users/zhangying/projects/study/maneki-agent/.env')
TOKEN = os.getenv('TUSHARE_TOKEN')

# 设置Tushare token
ts.set_token(TOKEN)
pro = ts.pro_api()

# 候选股票列表
stocks = [
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

def get_technical_indicators(ts_code):
    """获取技术指标数据"""
    try:
        # 获取 stk_factor_pro 数据（包含 MACD, KDJ, RSI 等）
        df = pro.stk_factor_pro(ts_code=ts_code, start_date='20250101', end_date='20260518')
        if df is None or len(df) == 0:
            return None
        # 按日期排序，最新的在前面
        df = df.sort_values('trade_date', ascending=False)
        return df
    except Exception as e:
        print(f"获取 {ts_code} 数据失败: {e}")
        return None

def calculate_score(df, stock_code, stock_name):
    """计算技术面评分"""
    if df is None or len(df) < 2:
        return None, "数据不足"
    
    score = 50  # 基础分
    reasons = []
    
    # 获取最近两天的数据
    today = df.iloc[0]
    yesterday = df.iloc[1] if len(df) > 1 else None
    
    # 1. MACD 分析
    macd_today = today.get('macd_dif')
    macd_signal_today = today.get('macd_dea')
    macd_hist_today = today.get('macd')
    
    macd_yest = yesterday.get('macd') if yesterday is not None else None
    
    if macd_hist_today is not None and macd_yest is not None:
        # MACD金叉：柱状图从负变正
        if macd_yest < 0 and macd_hist_today > 0:
            score += 15
            reasons.append(f"MACD金叉(+15分): 柱状图从{macd_yest:.3f}变为{macd_hist_today:.3f}")
        # MACD死叉：柱状图从正变负
        elif macd_yest > 0 and macd_hist_today < 0:
            score -= 10
            reasons.append(f"MACD死叉(-10分): 柱状图从{macd_yest:.3f}变为{macd_hist_today:.3f}")
    
    # 2. KDJ 分析
    k_today = today.get('kdj_k')
    d_today = today.get('kdj_d')
    j_today = today.get('kdj_j')
    
    k_yest = yesterday.get('kdj_k') if yesterday is not None else None
    d_yest = yesterday.get('kdj_d') if yesterday is not None else None
    
    if k_today is not None and d_today is not None and k_yest is not None and d_yest is not None:
        # KDJ金叉：K线从下向上穿越D线
        if k_yest < d_yest and k_today > d_today:
            score += 10
            reasons.append(f"KDJ金叉(+10分): K({k_today:.2f})上穿D({d_today:.2f})")
        
        # KDJ超买区：K>80
        if k_today > 80:
            score -= 5
            reasons.append(f"KDJ超买区(-5分): K值={k_today:.2f}>80")
    
    # 3. RSI 分析
    rsi_6 = today.get('rsi_6')
    
    if rsi_6 is not None:
        if 40 <= rsi_6 <= 60:
            score += 10
            reasons.append(f"RSI(6)在合理区间(+10分): RSI={rsi_6:.2f}")
        elif rsi_6 > 80:
            score -= 10
            reasons.append(f"RSI(6)超买(-10分): RSI={rsi_6:.2f}>80")
        elif rsi_6 < 20:
            score += 5  # 超卖可能反弹
            reasons.append(f"RSI(6)超卖可能反弹(+5分): RSI={rsi_6:.2f}<20")
    
    # 4. 均线多头排列分析
    ma5 = today.get('ma_5')
    ma10 = today.get('ma_10')
    ma20 = today.get('ma_20')
    
    if ma5 is not None and ma10 is not None and ma20 is not None:
        if ma5 > ma10 > ma20:
            score += 20
            reasons.append(f"均线多头排列(+20分): MA5({ma5:.2f})>MA10({ma10:.2f})>MA20({ma20:.2f})")
        elif ma5 < ma10 < ma20:
            score -= 15
            reasons.append(f"均线空头排列(-15分): MA5({ma5:.2f})<MA10({ma10:.2f})<MA20({ma20:.2f})")
    
    # 5. 布林带分析
    close = today.get('close')
    boll_upper = today.get('boll_upper')
    boll_mid = today.get('boll_mid')
    boll_lower = today.get('boll_lower')
    
    if close is not None and boll_mid is not None:
        # 突破布林中轨
        close_yest = yesterday.get('close') if yesterday is not None else None
        boll_mid_yest = yesterday.get('boll_mid') if yesterday is not None else None
        
        if close_yest is not None and boll_mid_yest is not None:
            if close_yest < boll_mid_yest and close > boll_mid:
                score += 10
                reasons.append(f"突破布林中轨(+10分): 收盘价{close:.2f}突破中轨{boll_mid:.2f}")
    
    # 限制分数在0-100之间
    score = max(0, min(100, score))
    
    if not reasons:
        reasons.append("无明显技术信号")
    
    return score, reasons

def main():
    results = []
    
    print("开始获取技术指标数据并分析...\n")
    
    for code, name in stocks:
        ts_code = f"{code}.SZ" if code.startswith('0') or code.startswith('3') else f"{code}.SH"
        
        print(f"正在分析: {code} {name}...")
        
        df = get_technical_indicators(ts_code)
        score, reasons = calculate_score(df, code, name)
        
        if score is not None:
            results.append({
                'code': code,
                'name': name,
                'score': score,
                'reasons': reasons,
                'latest_data': df.iloc[0].to_dict() if df is not None and len(df) > 0 else None
            })
        else:
            results.append({
                'code': code,
                'name': name,
                'score': 'N/A',
                'reasons': [reasons],
                'latest_data': None
            })
    
    # 按分数排序
    valid_results = [r for r in results if isinstance(r['score'], (int, float))]
    invalid_results = [r for r in results if not isinstance(r['score'], (int, float))]
    
    valid_results.sort(key=lambda x: x['score'], reverse=True)
    
    print("\n" + "="*80)
    print("技术面分析评分结果")
    print("="*80)
    
    for r in valid_results:
        print(f"\n【{r['code']} {r['name']}】评分: {r['score']}分")
        print("-" * 50)
        for reason in r['reasons']:
            print(f"  • {reason}")
        
        # 显示关键指标数据
        if r['latest_data']:
            d = r['latest_data']
            print(f"\n  数据支撑:")
            print(f"    交易日期: {d.get('trade_date')}")
            print(f"    收盘价: {d.get('close')}")
            print(f"    MACD: DIF={d.get('macd_dif'):.3f}, DEA={d.get('macd_dea'):.3f}, 柱={d.get('macd'):.3f}" if d.get('macd_dif') else "")
            print(f"    KDJ: K={d.get('kdj_k'):.2f}, D={d.get('kdj_d'):.2f}, J={d.get('kdj_j'):.2f}" if d.get('kdj_k') else "")
            print(f"    RSI(6): {d.get('rsi_6'):.2f}" if d.get('rsi_6') else "")
            print(f"    MA: MA5={d.get('ma_5'):.2f}, MA10={d.get('ma_10'):.2f}, MA20={d.get('ma_20'):.2f}" if d.get('ma_5') else "")
    
    if invalid_results:
        print("\n" + "="*80)
        print("无法获取数据的股票:")
        for r in invalid_results:
            print(f"  {r['code']} {r['name']}: {r['reasons'][0]}")
    
    return results

if __name__ == "__main__":
    main()
