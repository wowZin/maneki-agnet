#!/usr/bin/env python3
"""涨停预测 - 盘中扫描脚本 (使用daily接口获取最新行情)"""
import json
import os
import re
from datetime import datetime
import urllib.request

TUSHARE_TOKEN = "ebba208f5d60f9e86a1fcb39cf6dad5dca63c5288e82637ad59c5ac7"

def tushare_api(api_name, params=None):
    """调用 Tushare REST API"""
    if params is None:
        params = {}
    payload = {
        "api_name": api_name,
        "token": TUSHARE_TOKEN,
        "params": params
    }
    req = urllib.request.Request(
        "https://api.tushare.pro",
        data=json.dumps(payload).encode('utf-8'),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    if data["code"] != 0:
        raise Exception(f"Tushare API error: {data['msg']}")
    fields = data["data"]["fields"]
    items = data["data"]["items"]
    return [dict(zip(fields, item)) for item in items]

print("=== 涨停预测 - 盘中扫描 ===")
print(f"扫描时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# Step 0: 检查交易日
today = datetime.now().strftime("%Y%m%d")
print("Step 0: 检查交易日...")
try:
    cal = tushare_api("trade_cal", {"exchange": "SSE", "start_date": today, "end_date": today})
    if cal and cal[0].get("is_open") == 1:
        print(f"  {today} 是交易日，继续扫描")
    else:
        print(f"  {today} 非交易日，跳过扫描")
        exit(0)
except Exception as e:
    print(f"  检查交易日失败: {e}，继续执行")

# Step 1: 获取当日日线行情(使用daily接口)
print("Step 1: 获取当日行情数据...")
try:
    # 获取最近交易日数据
    stocks = tushare_api("daily", {"trade_date": today})
    print(f"  获取到 {len(stocks)} 只股票")
except Exception as e:
    print(f"  错误: {e}")
    # 尝试获取最近交易日
    try:
        print("  尝试获取最近交易日...")
        cal = tushare_api("trade_cal", {"exchange": "SSE", "is_open": "1", "end_date": today, "start_date": "20260101"})
        recent_dates = sorted([c["cal_date"] for c in cal], reverse=True)[:5]
        print(f"  最近交易日: {recent_dates}")
        for d in recent_dates:
            try:
                stocks = tushare_api("daily", {"trade_date": d})
                if stocks:
                    today = d
                    print(f"  使用交易日 {d}，获取到 {len(stocks)} 只股票")
                    break
            except:
                continue
        else:
            print("  无法获取行情数据")
            exit(1)
    except Exception as e2:
        print(f"  获取交易日历也失败: {e2}")
        exit(1)

# Step 2: 获取股票基础信息用于过滤
print("Step 2: 获取股票基础信息...")
try:
    basics = tushare_api("stock_basic", {"exchange": "", "list_status": "L"})
    # 构建代码->名称映射
    code_name = {b["ts_code"]: b["name"] for b in basics}
    print(f"  获取到 {len(basics)} 只股票基础信息")
except Exception as e:
    print(f"  警告: 获取基础信息失败: {e}")
    code_name = {}

# Step 3: 过滤和计算涨幅
print("Step 3: 过滤股票...")
filtered = []
for s in stocks:
    code = s.get("ts_code", "")
    
    # 获取名称
    name = code_name.get(code, "")
    
    # 排除ST、退市、N开头
    if re.search(r"ST|\\*ST|退|N", name):
        continue
    
    # 排除创业板(300)、科创板(688)、北交所(8开头/4开头)
    pure_code = code.split(".")[0] if "." in code else code
    if re.match(r"^(300|688|8|4)", pure_code):
        continue
    
    # 计算涨幅
    pre_close = s.get("pre_close")
    close = s.get("close")
    if not pre_close or not close:
        continue
    try:
        pct = (float(close) - float(pre_close)) / float(pre_close) * 100
    except:
        continue
    
    if pct >= 3:
        filtered.append({
            "code": code,
            "name": name,
            "pct_change": round(pct, 2),
            "price": close,
            "volume": s.get("vol"),
            "amount": s.get("amount")
        })

print(f"  过滤后涨幅>=3%股票: {len(filtered)} 只")

# Step 4: 按涨幅排序
filtered.sort(key=lambda x: x["pct_change"], reverse=True)

print()
print("=== 涨幅Top 20 ===")
for i, s in enumerate(filtered[:20]):
    print(f"  {i+1:2d}. {s['code']} {s['name']:8s} 涨幅:{s['pct_change']:+6.2f}% 价格:{s['price']}")

# Step 5: 涨速估算
print()
print("=== 涨速估算 ===")
# 假设交易4小时
for s in filtered:
    s["surge_rate"] = round(s["pct_change"] / 4, 2)

filtered.sort(key=lambda x: x["surge_rate"], reverse=True)

print("涨速Top 10 (按涨幅/4h估算):")
for i, s in enumerate(filtered[:10]):
    print(f"  {i+1:2d}. {s['code']} {s['name']:8s} 涨速:{s['surge_rate']:+5.2f}%/h 涨幅:{s['pct_change']:+6.2f}%")

# Step 6: 保存结果
data_dir = "/Users/zhangying/projects/study/maneki-agent/data/signals"
os.makedirs(data_dir, exist_ok=True)

output_file = f"{data_dir}/scan_{today}.json"
result = {
    "scan_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "trade_date": today,
    "total_stocks": len(stocks),
    "filtered_count": len(filtered),
    "top20": filtered[:20],
    "surge_top10": filtered[:10]
}

with open(output_file, 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print()
print(f"=== 结果已保存到: {output_file} ===")
print(f"统计: 共扫描 {len(stocks)} 只股票，筛选出 {len(filtered)} 只涨幅>=3%")
