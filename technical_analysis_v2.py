import tushare as ts
import os
from dotenv import load_dotenv
import time
import json

load_dotenv('/Users/zhangying/projects/study/maneki-agent/.env')
TOKEN = os.getenv('TUSHARE_TOKEN')
ts.set_token(TOKEN)
pro = ts.pro_api()

stocks = [
    ('002971', '和远气体'), ('603615', '茶花股份'), ('603767', '中马传动'),
    ('600130', '波导股份'), ('603070', '万控智造'), ('000404', '长虹华意'),
    ('605006', '山东玻纤'), ('603291', '联合水务'), ('603125', '常青科技'),
    ('001376', '百通能源'), ('600828', '茂业商业'), ('001266', '宏英智能'),
    ('600533', '栖霞建设'), ('002146', '荣盛发展'), ('002887', '绿茵生态'),
    ('601866', '中远海发'), ('603683', '晶华新材'), ('600538', '国发股份'),
    ('002066', '瑞泰科技'), ('600825', '新华传媒'), ('001322', '箭牌家居'),
    ('600606', '绿地控股'), ('600939', '重庆建工'), ('002210', '飞马国际'),
    ('600881', '亚泰集团'), ('000710', '贝瑞基因'), ('600400', '红豆股份'),
    ('603344', '星德胜'), ('603685', '晨丰科技'), ('000882', '华联股份'),
    ('603178', '圣龙股份'), ('600198', '大唐电信'),
]

def get_data(ts_code):
    try:
        df = pro.stk_factor_pro(ts_code=ts_code, start_date='20250101', end_date='20260518')
        if df is None or len(df) < 2:
            return None
        df = df.sort_values('trade_date', ascending=False).reset_index(drop=True)
        return df
    except Exception as e:
        print(f"  获取 {ts_code} 失败: {e}")
        return None

def calc_score(df, code, name):
    if df is None or len(df) < 2:
        return None, "数据不足"
    
    score = 50
    reasons = []
    
    today = df.iloc[0]
    yesterday = df.iloc[1]
    
    # 1. MACD 分析 (bfq字段)
    macd_hist_today = today.get('macd_bfq')
    macd_hist_yest = yesterday.get('macd_bfq')
    macd_dif_today = today.get('macd_dif_bfq')
    macd_dea_today = today.get('macd_dea_bfq')
    
    if macd_hist_today is not None and macd_hist_yest is not None:
        try:
            h_t = float(macd_hist_today)
            h_y = float(macd_hist_yest)
            if h_y < 0 and h_t > 0:
                score += 15
                reasons.append(f"MACD金叉(+15分): 柱状图从{h_y:.3f}变为{h_t:.3f}")
            elif h_y > 0 and h_t < 0:
                score -= 10
                reasons.append(f"MACD死叉(-10分): 柱状图从{h_y:.3f}变为{h_t:.3f}")
            elif h_t > 0 and h_y > 0 and h_t > h_y:
                reasons.append(f"MACD红柱增长: {h_y:.3f}→{h_t:.3f}")
            elif h_t < 0 and h_y < 0 and abs(h_t) < abs(h_y):
                reasons.append(f"MACD绿柱缩短: {h_y:.3f}→{h_t:.3f}")
        except:
            pass
    
    # 2. KDJ 分析
    k_today = today.get('kdj_k_bfq')
    d_today = today.get('kdj_d_bfq')
    j_today = today.get('kdj_bfq')
    k_yest = yesterday.get('kdj_k_bfq')
    d_yest = yesterday.get('kdj_d_bfq')
    
    if k_today is not None and d_today is not None and k_yest is not None and d_yest is not None:
        try:
            kt = float(k_today)
            dt = float(d_today)
            ky = float(k_yest)
            dy = float(d_yest)
            if ky < dy and kt > dt:
                score += 10
                reasons.append(f"KDJ金叉(+10分): K({ky:.2f}→{kt:.2f})上穿D({dy:.2f}→{dt:.2f})")
            elif ky > dy and kt < dt:
                score -= 10
                reasons.append(f"KDJ死叉(-10分): K({ky:.2f}→{kt:.2f})下穿D({dy:.2f}→{dt:.2f})")
            
            if kt > 80:
                score -= 5
                reasons.append(f"KDJ超买区(-5分): K值={kt:.2f}>80")
            elif kt < 20:
                score += 5
                reasons.append(f"KDJ超卖区(+5分): K值={kt:.2f}<20")
        except:
            pass
    
    # 3. RSI(6) 分析
    rsi6 = today.get('rsi_bfq_6')
    if rsi6 is not None:
        try:
            r = float(rsi6)
            if 40 <= r <= 60:
                score += 10
                reasons.append(f"RSI(6)在合理区间(+10分): RSI={r:.2f}")
            elif r > 80:
                score -= 10
                reasons.append(f"RSI(6)超买(-10分): RSI={r:.2f}>80")
            elif r < 20:
                score += 5
                reasons.append(f"RSI(6)超卖可能反弹(+5分): RSI={r:.2f}<20")
            elif 60 < r <= 80:
                reasons.append(f"RSI(6)偏强区间: RSI={r:.2f}")
            elif 20 <= r < 40:
                reasons.append(f"RSI(6)偏弱区间: RSI={r:.2f}")
        except:
            pass
    
    # 4. 均线多头排列 MA5 > MA10 > MA20
    ma5 = today.get('ma_bfq_5')
    ma10 = today.get('ma_bfq_10')
    ma20 = today.get('ma_bfq_20')
    
    if ma5 is not None and ma10 is not None and ma20 is not None:
        try:
            m5 = float(ma5)
            m10 = float(ma10)
            m20 = float(ma20)
            if m5 > m10 > m20:
                score += 20
                reasons.append(f"均线多头排列(+20分): MA5({m5:.2f})>MA10({m10:.2f})>MA20({m20:.2f})")
            elif m5 < m10 < m20:
                score -= 15
                reasons.append(f"均线空头排列(-15分): MA5({m5:.2f})<MA10({m10:.2f})<MA20({m20:.2f})")
            else:
                reasons.append(f"均线交织: MA5={m5:.2f}, MA10={m10:.2f}, MA20={m20:.2f}")
        except:
            pass
    
    # 5. 突破布林中轨
    close_today = today.get('close')
    boll_mid_today = today.get('boll_mid_bfq')
    close_yest = yesterday.get('close')
    boll_mid_yest = yesterday.get('boll_mid_bfq')
    
    if close_today is not None and boll_mid_today is not None and close_yest is not None and boll_mid_yest is not None:
        try:
            ct = float(close_today)
            bmt = float(boll_mid_today)
            cy = float(close_yest)
            bmy = float(boll_mid_yest)
            if cy < bmy and ct > bmt:
                score += 10
                reasons.append(f"突破布林中轨(+10分): 收盘价从{cy:.2f}升至{ct:.2f}, 突破中轨{bmt:.2f}")
            elif cy > bmy and ct < bmt:
                score -= 5
                reasons.append(f"跌破布林中轨(-5分): 收盘价从{cy:.2f}降至{ct:.2f}, 跌破中轨{bmt:.2f}")
        except:
            pass
    
    score = max(0, min(100, score))
    
    if not reasons:
        reasons.append("无明显技术信号")
    
    return score, reasons

def main():
    results = []
    print("开始技术面分析评分...\n")
    
    for code, name in stocks:
        if code.startswith('0') or code.startswith('3') or code.startswith('1'):
            ts_code = f"{code}.SZ"
        else:
            ts_code = f"{code}.SH"
        
        print(f"分析 {code} {name}...", end=" ", flush=True)
        df = get_data(ts_code)
        score, reasons = calc_score(df, code, name)
        
        if score is not None:
            latest = df.iloc[0]
            results.append({
                'code': code,
                'name': name,
                'score': score,
                'reasons': reasons,
                'trade_date': latest.get('trade_date'),
                'close': float(latest.get('close')) if latest.get('close') else None,
                'macd_dif': float(latest.get('macd_dif_bfq')) if latest.get('macd_dif_bfq') else None,
                'macd_dea': float(latest.get('macd_dea_bfq')) if latest.get('macd_dea_bfq') else None,
                'macd_hist': float(latest.get('macd_bfq')) if latest.get('macd_bfq') else None,
                'kdj_k': float(latest.get('kdj_k_bfq')) if latest.get('kdj_k_bfq') else None,
                'kdj_d': float(latest.get('kdj_d_bfq')) if latest.get('kdj_d_bfq') else None,
                'kdj_j': float(latest.get('kdj_bfq')) if latest.get('kdj_bfq') else None,
                'rsi6': float(latest.get('rsi_bfq_6')) if latest.get('rsi_bfq_6') else None,
                'ma5': float(latest.get('ma_bfq_5')) if latest.get('ma_bfq_5') else None,
                'ma10': float(latest.get('ma_bfq_10')) if latest.get('ma_bfq_10') else None,
                'ma20': float(latest.get('ma_bfq_20')) if latest.get('ma_bfq_20') else None,
                'boll_mid': float(latest.get('boll_mid_bfq')) if latest.get('boll_mid_bfq') else None,
                'pct_chg': float(latest.get('pct_chg')) if latest.get('pct_chg') else None,
            })
            print(f"评分: {score}")
        else:
            results.append({
                'code': code, 'name': name, 'score': 'N/A',
                'reasons': [reasons], 'trade_date': None
            })
            print(f"数据不足")
        
        time.sleep(0.3)  # API限速
    
    # 排序
    valid = [r for r in results if isinstance(r['score'], (int, float))]
    invalid = [r for r in results if not isinstance(r['score'], (int, float))]
    valid.sort(key=lambda x: x['score'], reverse=True)
    
    print("\n" + "=" * 80)
    print("技术面分析评分结果（按分数从高到低排列）")
    print("=" * 80)
    
    for i, r in enumerate(valid, 1):
        print(f"\n第{i名 【r['code']} {r['name']}】 评分: {r['score']}分")
        print("-" * 60)
        for reason in r['reasons']:
            print(f"  • {reason}")
        print(f"\n  关键指标数据:")
        print(f"    日期: {r.get('trade_date')}  收盘价: {r.get('close')}  涨跌幅: {r.get('pct_chg')}%")
        if r.get('macd_dif') is not None:
            print(f"    MACD: DIF={r['macd_dif']:.3f}, DEA={r['macd_dea']:.3f}, 柱={r['macd_hist']:.3f}")
        if r.get('kdj_k') is not None:
            print(f"    KDJ: K={r['kdj_k']:.2f}, D={r['kdj_d']:.2f}, J={r['kdj_j']:.2f}")
        if r.get('rsi6') is not None:
            print(f"    RSI(6): {r['rsi6']:.2f}")
        if r.get('ma5') is not None:
            print(f"    均线: MA5={r['ma5']:.2f}, MA10={r['ma10']:.2f}, MA20={r['ma20']:.2f}")
        if r.get('boll_mid') is not None:
            print(f"    布林中轨: {r['boll_mid']:.2f}")
    
    if invalid:
        print("\n" + "=" * 80)
        print("无法获取数据的股票:")
        for r in invalid:
            print(f"  {r['code']} {r['name']}: {r['reasons'][0]}")
    
    # 保存JSON结果
    output_file = '/Users/zhangying/projects/study/maneki-agent/technical_analysis_results.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(valid, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存到 {output_file}")

if __name__ == "__main__":
    main()
