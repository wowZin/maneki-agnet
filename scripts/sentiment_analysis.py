#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
候选股票情绪面/板块热度分析评分
"""

import akshare as ak
import pandas as pd
import time
import json
import sys

# 候选股票列表
STOCKS = [
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
    ("600198", "大唐电信"),
]

def get_concept_boards():
    """获取所有概念板块及涨幅、资金流向"""
    print("正在获取概念板块列表...")
    concept_df = ak.stock_board_concept_name_em()
    print(f"共获取到 {len(concept_df)} 个概念板块")
    print(f"概念板块列名: {concept_df.columns.tolist()}")
    print(concept_df.head(3))
    return concept_df

def get_stock_concept(stock_code):
    """获取个股所属概念板块"""
    try:
        df = ak.stock_board_concept_cons_em(symbol=stock_code)
        # 返回个股所属的概念板块名称列表
        if '概念名称' in df.columns:
            return df['概念名称'].tolist()
        elif '板块名称' in df.columns:
            return df['板块名称'].tolist()
        else:
            print(f"  {stock_code} 所属板块列名: {df.columns.tolist()}")
            return []
    except Exception as e:
        print(f"  获取 {stock_code} 所属板块失败: {e}")
        return []

def get_concept_detail(concept_name):
    """获取概念板块成分股详情(涨幅排名等)"""
    try:
        df = ak.stock_board_concept_cons_em(symbol=concept_name)
        return df
    except Exception as e:
        print(f"  获取板块 {concept_name} 详情失败: {e}")
        return pd.DataFrame()

def main():
    print("=" * 60)
    print("候选股票情绪面/板块热度分析评分")
    print("=" * 60)

    # Step 1: 获取概念板块列表及涨幅
    concept_df = get_concept_boards()

    # 确定涨幅列名
    change_col = None
    for col in concept_df.columns:
        if '涨' in col and '幅' in col:
            change_col = col
            break
        elif '涨跌幅' in col:
            change_col = col
            break
    
    if change_col is None:
        # 尝试其他列名
        print(f"所有列名: {concept_df.columns.tolist()}")
        for col in concept_df.columns:
            if '涨' in col or 'change' in col.lower():
                change_col = col
                break
    
    # 确定资金净流入列名
    fund_col = None
    for col in concept_df.columns:
        if '资金' in col or '净流' in col:
            fund_col = col
            break
    
    # 确定板块名称列
    name_col = None
    for col in concept_df.columns:
        if '名称' in col or '板块' in col:
            name_col = col
            break
        elif '概念' in col:
            name_col = col
            break

    print(f"\n涨幅列: {change_col}")
    print(f"资金列: {fund_col}")
    print(f"名称列: {name_col}")

    if change_col:
        concept_df[change_col] = pd.to_numeric(concept_df[change_col], errors='coerce')
    if fund_col:
        concept_df[fund_col] = pd.to_numeric(concept_df[fund_col], errors='coerce')

    # 筛选涨幅>3%的板块
    hot_concepts = set()
    hot_concepts_detail = {}
    if change_col:
        hot_df = concept_df[concept_df[change_col] > 3]
        if name_col:
            hot_concepts = set(hot_df[name_col].tolist())
            for _, row in hot_df.iterrows():
                cname = row[name_col]
                hot_concepts_detail[cname] = {
                    'change': row[change_col],
                    'fund': row[fund_col] if fund_col else None
                }
        print(f"\n涨幅>3%的概念板块共 {len(hot_concepts)} 个:")
        for cname, detail in sorted(hot_concepts_detail.items(), key=lambda x: x[1]['change'], reverse=True)[:20]:
            fund_str = f", 资金净流入: {detail['fund']:.2f}亿" if detail['fund'] is not None else ""
            print(f"  {cname}: 涨幅 {detail['change']:.2f}%{fund_str}")

    # 筛选资金净流入>5亿的板块
    big_fund_concepts = set()
    if fund_col:
        fund_df = concept_df[concept_df[fund_col] > 5]
        if name_col:
            big_fund_concepts = set(fund_df[name_col].tolist())
        print(f"\n资金净流入>5亿的概念板块共 {len(big_fund_concepts)} 个")

    # 筛选板块整体下跌的
    down_concepts = set()
    if change_col:
        down_df = concept_df[concept_df[change_col] < 0]
        if name_col:
            down_concepts = set(down_df[name_col].tolist())
        print(f"\n整体下跌的概念板块共 {len(down_concepts)} 个")

    # Step 2: 逐只股票获取所属概念板块并评分
    results = []
    
    for idx, (code, name) in enumerate(STOCKS):
        print(f"\n[{idx+1}/{len(STOCKS)}] 分析 {code} {name}...")
        time.sleep(0.3)  # 控制请求频率
        
        score = 50  # 基础分
        reasons = []
        
        # 获取个股所属概念板块
        stock_concepts = get_stock_concept(code)
        print(f"  所属概念板块: {stock_concepts}")
        
        if not stock_concepts:
            reasons.append("无法获取所属板块信息")
            results.append({"code": code, "name": name, "score": score, "reasons": reasons})
            continue
        
        # 规则1: 所属概念板块涨幅>3% +15分(每个板块算一次,最多加45分)
        hot_match = [c for c in stock_concepts if c in hot_concepts]
        if hot_match:
            add_score = min(15 * len(hot_match), 45)  # 最多3个板块
            score += add_score
            for hc in hot_match:
                chg = hot_concepts_detail.get(hc, {}).get('change', 'N/A')
                reasons.append(f"所属板块[{hc}]涨幅{chg:.2f}%>3%, +15分")
        
        # 规则4: 板块整体下跌 扣10分(每个板块算一次,最多扣30分)
        down_match = [c for c in stock_concepts if c in down_concepts]
        if down_match:
            # 排除已经算过热点的
            down_only = [c for c in down_match if c not in hot_match]
            if down_only:
                deduct = min(10 * len(down_only), 30)
                score -= deduct
                for dc in down_only:
                    chg = hot_concepts_detail.get(dc, {}).get('change', 0)
                    if chg == 0:
                        # 查找下跌板块的具体跌幅
                        if name_col and change_col:
                            row = concept_df[concept_df[name_col] == dc]
                            if not row.empty:
                                chg = row[change_col].values[0]
                    reasons.append(f"所属板块[{dc}]整体下跌{chg:.2f}%, -10分")
        
        # 规则2: 个股为板块龙头 +10分
        # 需要检查个股在热门板块内涨幅是否前3
        is_leader = False
        leader_boards = []
        # 只检查热门板块
        for hc in hot_match[:3]:  # 最多检查3个热门板块,避免太多请求
            time.sleep(0.3)
            detail_df = get_concept_detail(hc)
            if detail_df.empty:
                continue
            
            # 找涨幅列
            stock_change_col = None
            for col in detail_df.columns:
                if '涨' in col and '幅' in col:
                    stock_change_col = col
                    break
            
            if stock_change_col is None:
                continue
            
            detail_df[stock_change_col] = pd.to_numeric(detail_df[stock_change_col], errors='coerce')
            detail_df = detail_df.sort_values(stock_change_col, ascending=False)
            
            # 找代码列
            code_col = None
            for col in detail_df.columns:
                if '代码' in col:
                    code_col = col
                    break
            
            if code_col is None:
                continue
            
            top3_codes = detail_df[code_col].head(3).tolist()
            if code in top3_codes:
                is_leader = True
                rank = top3_codes.index(code) + 1
                leader_boards.append(f"{hc}(第{rank}名)")
        
        if is_leader:
            score += 10
            reasons.append(f"为板块龙头[{', '.join(leader_boards)}], +10分")
        
        # 规则3: 板块资金净流入>5亿 +10分(每个板块算一次,最多加30分)
        fund_match = [c for c in stock_concepts if c in big_fund_concepts]
        if fund_match:
            add_score_fund = min(10 * len(fund_match), 30)
            score += add_score_fund
            for fc in fund_match:
                fund_val = hot_concepts_detail.get(fc, {}).get('fund', 'N/A')
                reasons.append(f"所属板块[{fc}]资金净流入>{5}亿({fund_val}), +10分")
        
        # 限制分数在0-100
        score = max(0, min(100, score))
        
        if not reasons:
            reasons.append("所属板块无显著热点或冷点,维持基础分50分")
        
        results.append({"code": code, "name": name, "score": score, "reasons": reasons})
        print(f"  评分: {score}")
        print(f"  理由: {'; '.join(reasons)}")
    
    # 输出最终结果
    print("\n" + "=" * 60)
    print("情绪面分析评分结果")
    print("=" * 60)
    
    # 按分数降序排列
    results.sort(key=lambda x: x['score'], reverse=True)
    
    for r in results:
        print(f"\n{r['code']} {r['name']}: {r['score']}分")
        for reason in r['reasons']:
            print(f"  - {reason}")
    
    # 保存结果
    output_path = "/Users/zhangying/projects/study/maneki-agent/data/sentiment_scores.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存到: {output_path}")

if __name__ == "__main__":
    main()
