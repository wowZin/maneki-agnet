#!/usr/bin/env python3
"""使用requests获取东方财富涨速数据"""
import json
import re
import time
from datetime import datetime

try:
    import requests
except ImportError:
    import subprocess
    subprocess.check_call(['pip3', 'install', 'requests', '-q'])
    import requests

print("=== 5分钟涨速扫描 (requests) ===")
print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# 构建API URL
api_url = (
    "https://push2.eastmoney.com/api/qt/clist/get?"
    "np=1&fltt=2&invt=2&"
    "fs=m:0+t:6+f:!2,m:0+t:80+f:!2,m:1+t:2+f:!2,m:1+t:23+f:!2,m:0+t:81+s:262144+f:!2&"
    "fields=f12,f13,f14,f2,f4,f3,f5,f6,f7,f15,f18,f16,f17,f10,f8,f9,f11&"
    "fid=f11&pn=1&pz=500&po=1&dect=1&"
    "ut=fa5fd1943c7b386f172d6893dbfba10b&cb="
)

headers = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://quote.eastmoney.com/',
    'Accept': '*/*',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Connection': 'keep-alive',
}

print("Step 1: 请求东方财富API...")
session = requests.Session()
session.headers.update(headers)

for attempt in range(3):
    try:
        resp = session.get(api_url, timeout=30, verify=True)
        content = resp.text
        print(f"  HTTP状态: {resp.status_code}, 内容长度: {len(content)}")
        break
    except Exception as e:
        print(f"  尝试 {attempt+1}/3 失败: {e}")
        if attempt < 2:
            time.sleep(2)
        else:
            print("  所有尝试失败")
            # 尝试akshare作为降级
            print("\n  降级: 使用akshare获取涨速数据...")
            try:
                import akshare as ak
                df = ak.stock_zh_a_spot_em()
                df = df[~df['名称'].str.contains('ST|退|N', na=False)]
                df = df[~df['代码'].str.match(r'^(300|301|688|8|4|920)')]
                df = df.sort_values('涨速', ascending=False).head(100)
                stocks = []
                for _, row in df.iterrows():
                    stocks.append({
                        "代码": row['代码'],
                        "名称": row['名称'],
                        "涨幅%": float(row['涨跌幅']) if row['涨跌幅'] != '-' else 0,
                        "5分钟涨速%": float(row['涨速']) if row['涨速'] != '-' else 0,
                        "最新价": float(row['最新价']) if row['最新价'] != '-' else 0,
                        "成交额": float(row['成交额']) if row['成交额'] != '-' else 0,
                        "量比": str(row.get('量比', '-'))
                    })
                top100 = stocks
                print(f"  akshare获取到 {len(top100)} 只")
                # 跳到保存
                import os
                data_dir = "/Users/zhangying/projects/study/maneki-agent/data/signals"
                os.makedirs(data_dir, exist_ok=True)
                today = datetime.now().strftime("%Y%m%d")
                time_str = datetime.now().strftime("%H%M%S")
                output = {
                    "scan_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "trade_date": today,
                    "data_source": "akshare_fallback",
                    "data_note": "东方财富CDP连接失败，降级使用akshare获取",
                    "count": len(top100),
                    "total_filtered": len(top100),
                    "stocks": top100
                }
                out_file = f"{data_dir}/{today}_{time_str}.json"
                with open(out_file, "w", encoding="utf-8") as f:
                    json.dump(output, f, ensure_ascii=False, indent=2)
                print(f"\n已保存: {out_file}")
                exit(0)
            except Exception as e2:
                print(f"  akshare也失败: {e2}")
                exit(1)

print("Step 2: 解析JSON数据...")
try:
    content = content.strip()
    if content.startswith('(') and content.endswith(')'):
        content = content[1:-1]
    api_data = json.loads(content)
except json.JSONDecodeError as e:
    print(f"  JSON解析失败: {e}")
    print(f"  原始内容前200字符: {content[:200]}")
    exit(1)

if not api_data.get("data") or not api_data["data"].get("diff"):
    print(f"  API返回异常: {json.dumps(api_data, ensure_ascii=False)[:200]}")
    exit(1)

stocks = api_data["data"]["diff"]
print(f"  获取到 {len(stocks)} 条数据")

# Step 3: 过滤数据
print("Step 3: 过滤数据...")
filtered = []
for s in stocks:
    code = s.get("f12", "")
    name = s.get("f14", "")
    
    if re.search(r"ST|\*ST|退|N", name or ""):
        continue
    if re.match(r"^(300|301|688|8|4|920)", code):
        continue
    
    pct = s.get("f3")
    f11 = s.get("f11")
    price = s.get("f2")
    amount = s.get("f6")
    
    if pct is None or pct == "-":
        continue
    try:
        pct = float(pct)
        f11 = float(f11) if f11 and f11 != "-" else 0
        price = float(price) if price and price != "-" else 0
        amount = float(amount) if amount and amount != "-" else 0
    except:
        continue
    
    filtered.append({
        "代码": code,
        "名称": name,
        "涨幅%": pct,
        "5分钟涨速%": f11,
        "最新价": price,
        "成交额": amount,
        "量比": s.get("f10", "-")
    })

print(f"  过滤后: {len(filtered)} 只")

filtered.sort(key=lambda x: x["5分钟涨速%"], reverse=True)
top100 = filtered[:100]

print()
print(f"=== 5分钟涨速前100 (实际{len(top100)}只) ===")
print(f"{'排名':>4} {'代码':8} {'名称':8} {'5分涨速':>8} {'涨幅%':>7} {'最新价':>8} {'成交额':>10}")
print("-" * 60)
for i, s in enumerate(top100[:20]):
    amt = s["成交额"]
    amt_str = f"{amt/1e8:.1f}亿" if amt > 1e8 else f"{amt/1e4:.0f}万"
    print(f"  {i+1:2d}  {s['代码']:8} {s['名称']:8} {s['5分钟涨速%']:+8.2f} {s['涨幅%']:+7.2f} {s['最新价']:8.2f} {amt_str:>10}")

if len(top100) > 20:
    print(f"  ... (共{len(top100)}只，仅显示前20)")

import os
data_dir = "/Users/zhangying/projects/study/maneki-agent/data/signals"
os.makedirs(data_dir, exist_ok=True)

today = datetime.now().strftime("%Y%m%d")
time_str = datetime.now().strftime("%H%M%S")
output = {
    "scan_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "trade_date": today,
    "data_source": "eastmoney_http_requests",
    "data_note": "东方财富实时行情(requests方式获取)",
    "count": len(top100),
    "total_filtered": len(filtered),
    "stocks": top100
}

out_file = f"{data_dir}/{today}_{time_str}.json"
with open(out_file, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)
print(f"\n已保存: {out_file}")
