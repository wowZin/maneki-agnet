import akshare as ak
import pandas as pd
import warnings
import time
import random
warnings.filterwarnings('ignore')

stocks = [
    ("002971", "和远气体"),
    ("603615", "茶花股份"),
    ("603767", "中马传动"),
    ("600130", "波导股份"),
    ("603070", "万控智造"),
    ("000404", "长虹华意"),
    ("605006", "山东玻纤"),
    ("603291", "联合水务"),
    ("603125", "常青科技"),
    ("001376", "百通能源"),
    ("600828", "茂业商业"),
    ("001266", "宏英智能"),
    ("600533", "栖霞建设"),
    ("002146", "荣盛发展"),
    ("002887", "绿茵生态"),
    ("601866", "中远海发"),
    ("603683", "晶华新材"),
    ("600538", "国发股份"),
    ("002066", "瑞泰科技"),
    ("600825", "新华传媒"),
    ("001322", "箭牌家居"),
    ("600606", "绿地控股"),
    ("600939", "重庆建工"),
    ("002210", "飞马国际"),
    ("600881", "亚泰集团"),
    ("000710", "贝瑞基因"),
    ("600400", "红豆股份"),
    ("603344", "星德胜"),
    ("603685", "晨丰科技"),
    ("000882", "华联股份"),
    ("603178", "圣龙股份"),
    ("600198", "大唐电信")
]

def get_fund_flow_data(code, name, max_retries=3):
    """获取个股资金流数据，带重试"""
    market = "sh" if code.startswith("6") else "sz"
    for attempt in range(max_retries):
        try:
            df = ak.stock_individual_fund_flow(stock=code, market=market)
            if df is not None and len(df) > 0:
                return df.head(5)
        except Exception as e:
            print(f"  尝试{attempt+1}获取 {code} {name} 失败: {e}")
            time.sleep(2 + random.random() * 3)
    return None

def calculate_score(df, code, name):
    """根据评分依据计算得分"""
    score = 50
    reasons = []
    
    if df is None or len(df) == 0:
        return 50, "无法获取资金流数据"
    
    today = df.iloc[0]
    cols = list(df.columns)
    
    # Debug: print columns for first stock
    if code == "002971":
        print(f"  [DEBUG] 列名: {cols}")
        print(f"  [DEBUG] 今日数据:\n{today}")
    
    try:
        main_net_inflow = None
        main_net_ratio = None
        big_buy = None
        
        for col in cols:
            col_str = str(col)
            if '主力净流入' in col_str or '主力净买' in col_str:
                if '占比' in col_str or '比例' in col_str or '%' in col_str:
                    main_net_ratio = today[col]
                else:
                    main_net_inflow = today[col]
            elif '大单净' in col_str or '大单买入' in col_str:
                big_buy = today[col]
        
        def parse_num(val):
            if val is None:
                return 0
            if isinstance(val, (int, float)):
                return float(val)
            if isinstance(val, str):
                val = val.replace(',', '').replace('亿', '').replace('%', '').strip()
                return float(val) if val else 0
            return 0
        
        # 规则1: 主力净流入>0且占比>3% +20分; 主力净流出占比>3% -20分
        if main_net_inflow is not None and main_net_ratio is not None:
            inflow_val = parse_num(main_net_inflow)
            ratio_val = parse_num(main_net_ratio)
            
            if inflow_val > 0 and ratio_val > 3:
                score += 20
                reasons.append(f"主力净流入{inflow_val:.2f}亿,占比{ratio_val:.2f}%>3%(+20分)")
            elif ratio_val < -3:
                score -= 20
                reasons.append(f"主力净流出占比{ratio_val:.2f}%<-3%(-20分)")
        
        # 规则2: 大单净买入>0 +15分
        if big_buy is not None:
            big_val = parse_num(big_buy)
            if big_val > 0:
                score += 15
                reasons.append(f"大单净买入{big_val:.2f}亿>0(+15分)")
        
        # 规则3: 连续3日主力净流入 +10分
        if len(df) >= 3:
            consecutive_inflow = True
            for i in range(3):
                row = df.iloc[i]
                for col in cols:
                    if ('主力净流入' in str(col) or '主力净买' in str(col)) and '占比' not in str(col) and '比例' not in str(col):
                        val = parse_num(row[col])
                        if val <= 0:
                            consecutive_inflow = False
                            break
            if consecutive_inflow:
                score += 10
                reasons.append("连续3日主力净流入(+10分)")
        
        if not reasons:
            reasons.append("资金面表现平平")
            
    except Exception as e:
        reasons.append(f"数据解析异常: {e}")
    
    score = max(0, min(100, score))
    return score, "; ".join(reasons)

print("="*80)
print("候选股票资金面分析评分报告")
print("="*80)

results = []
for code, name in stocks:
    df = get_fund_flow_data(code, name)
    score, reason = calculate_score(df, code, name)
    results.append({
        '代码': code,
        '名称': name,
        '评分': score,
        '评分理由': reason
    })
    print(f"{code} {name}: 评分={score}分, 理由={reason}")
    time.sleep(1 + random.random() * 2)

print("\n" + "="*80)
print("按评分排序结果:")
print("="*80)
df_results = pd.DataFrame(results)
df_sorted = df_results.sort_values('评分', ascending=False)
print(df_sorted.to_string(index=False))
