#!/usr/bin/env python3
"""涨停预测扫描主程序 - 使用requests+代理获取涨速"""
import json
import os
import sys
import time
import datetime
from pathlib import Path
from dotenv import load_dotenv

# 添加scripts目录到sys.path以便导入proxy_utils
sys.path.insert(0, str(Path(__file__).parent))
import proxy_utils

# 加载环境变量
load_dotenv('/Users/zhangying/projects/study/maneki-agent/.env')

# ===== Step 1: 检查交易日 =====
print("=" * 60)
print("Step 1: 检查交易日")
print("=" * 60)

try:
    import tushare as ts
    ts.set_token(os.getenv('TUSHARE_TOKEN'))
    pro = ts.pro_api()
    today = datetime.date.today().strftime('%Y%m%d')
    print(f"检查日期: {today}")
    
    df = pro.trade_cal(exchange='SSE', start_date=today, end_date=today)
    if df.empty or df.iloc[0]['is_open'] != 1:
        print("今天不是交易日，退出")
        sys.exit(0)
    print("今天是交易日，继续执行")
except Exception as e:
    print(f"Tushare检查失败: {e}")
    # 假设今天是交易日（周一到周五）
    weekday = datetime.date.today().weekday()
    if weekday >= 5:  # 周六或周日
        print("今天是周末，退出")
        sys.exit(0)
    print("假设今天是交易日，继续执行")

# ===== Step 2: 获取涨速数据 (requests+代理) =====
print()
print("=" * 60)
print("Step 2: 获取涨速数据 (requests+代理)")
print("=" * 60)

from cdp_fetch import get_surge_rate_requests

stocks_result = get_surge_rate_requests()
if stocks_result is None:
    print("获取涨速数据失败，退出")
    sys.exit(1)

# 使用已获取的涨速数据
filtered = stocks_result

# 按涨速排序取前100
filtered.sort(key=lambda x: x["5分钟涨速%"], reverse=True)
top100 = filtered[:100]

print(f"取前100只作为候选股票")

# 保存候选列表
data_dir = "/Users/zhangying/projects/study/maneki-agent/data/signals"
os.makedirs(data_dir, exist_ok=True)

scan_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
trade_date = datetime.datetime.now().strftime("%Y%m%d")

candidates_output = {
    "scan_time": scan_time,
    "trade_date": trade_date,
    "data_source": "eastmoney_cdp_realtime",
    "count": len(top100),
    "stocks": top100
}

candidates_file = f"{data_dir}/{trade_date}_candidates.json"
with open(candidates_file, "w", encoding="utf-8") as f:
    json.dump(candidates_output, f, ensure_ascii=False, indent=2)
print(f"候选列表已保存: {candidates_file}")

# 输出候选股票代码列表（供后续分析使用）
print()
print("候选股票列表:")
for i, s in enumerate(top100[:10]):
    print(f"  {i+1}. {s['代码']} {s['名称']} 涨幅:{s['涨幅%']:+.2f}% 涨速:{s['5分钟涨速%']:+.2f}%")
if len(top100) > 10:
    print(f"  ... 共{len(top100)}只")
