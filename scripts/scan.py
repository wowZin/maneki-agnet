#!/usr/bin/env python3
"""涨停预测 - 盘中扫描脚本"""
import akshare as ak
import pandas as pd
import re
import os
import json
from datetime import datetime

print("=== 涨停预测 - 盘中扫描 ===")
print(f"扫描时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# Step 1: 获取沪深A股实时行情
print("Step 1: 获取实时行情数据...")
try:
    df = ak.stock_zh_a_spot_em()
    print(f"  获取到 {len(df)} 只股票")
except Exception as e:
    print(f"  错误: {e}")
    exit(1)

# Step 2: 过滤
print("Step 2: 过滤股票...")

# 排除ST、退市、N开头
df = df[~df['名称'].str.contains('ST|\\*ST|退|N', na=False, regex=True)]

# 排除创业板(300)、科创板(688)、北交所(8开头/4开头)
df = df[~df['代码'].str.match(r'^(300|688|8|4)', na=False)]

# 涨幅>=3%
df['涨跌幅'] = pd.to_numeric(df['涨跌幅'], errors='coerce')
df = df.dropna(subset=['涨跌幅'])
df_high = df[df['涨跌幅'] >= 3].copy()

print(f"  过滤后涨幅>=3%股票: {len(df_high)} 只")

# Step 3: 按涨幅排序
df_high = df_high.sort_values('涨跌幅', ascending=False)

print()
print("=== 涨幅Top 20 ===")
for i, (_, row) in enumerate(df_high.head(20).iterrows()):
    print(f"  {i+1:2d}. {row['代码']} {row['名称']:8s} 涨幅:{row['涨跌幅']:+6.2f}% 最新价:{row['最新价']}")

# Step 4: 涨速估算
print()
print("=== 涨速估算 ===")
now_hour = datetime.now().hour
trading_hours = max(1, now_hour - 9.5)

df_high['预估涨速'] = df_high['涨跌幅'] / trading_hours
df_high_sorted = df_high.sort_values('预估涨速', ascending=False)

print("涨速Top 10:")
for i, (_, row) in enumerate(df_high_sorted.head(10).iterrows()):
    print(f"  {i+1:2d}. {row['代码']} {row['名称']:8s} 涨速:{row['预估涨速']:+5.2f}%/h 涨幅:{row['涨跌幅']:+6.2f}%")

# Step 5: 保存结果
data_dir = "/Users/zhangying/projects/study/maneki-agent/data/signals"
os.makedirs(data_dir, exist_ok=True)

today = datetime.now().strftime("%Y%m%d")
output_file = f"{data_dir}/scan_{today}.csv"
df_high.to_csv(output_file, index=False, encoding='utf-8-sig')

# 也保存一份JSON便于读取
json_file = f"{data_dir}/scan_{today}.json"
result = {
    "scan_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "total_stocks": len(df),
    "filtered_count": len(df_high),
    "top20": [],
    "surge_top10": []
}
for _, row in df_high.head(20).iterrows():
    result["top20"].append({
        "code": row['代码'], "name": row['名称'],
        "pct_change": float(row['涨跌幅']), "price": float(row['最新价'])
    })
for _, row in df_high_sorted.head(10).iterrows():
    result["surge_top10"].append({
        "code": row['代码'], "name": row['名称'],
        "surge_rate": round(float(row['预估涨速']), 2),
        "pct_change": float(row['涨跌幅'])
    })

with open(json_file, 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print()
print(f"=== 结果已保存 ===")
print(f"  CSV: {output_file}")
print(f"  JSON: {json_file}")
print(f"统计: 共扫描 {len(df)} 只股票，筛选出 {len(df_high)} 只涨幅>=3%")
