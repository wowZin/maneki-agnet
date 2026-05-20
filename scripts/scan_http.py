#!/usr/bin/env python3
"""直接HTTP请求获取东方财富涨速数据（集成代理）"""
import json
import os
import sys
import urllib.request
import re
import time
from datetime import datetime
from pathlib import Path

# 添加scripts目录到sys.path以便导入proxy_utils
sys.path.insert(0, str(Path(__file__).parent))
import proxy_utils

print("=== 5分钟涨速扫描 (HTTP+代理) ===")
print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# 构建API URL - 沪深A股，按5分钟涨速排序
# pz=500 获取500条数据，过滤后取前100
api_url = (
    "https://push2.eastmoney.com/api/qt/clist/get?"
    "np=1&fltt=2&invt=2&"
    "fs=m:0+t:6+f:!2,m:0+t:80+f:!2,m:1+t:2+f:!2,m:1+t:23+f:!2,m:0+t:81+s:262144+f:!2&"
    "fields=f12,f13,f14,f2,f4,f3,f5,f6,f7,f15,f18,f16,f17,f10,f8,f9,f11&"
    "fid=f11&pn=1&pz=500&po=1&dect=1&"
    "ut=fa5fd1943c7b386f172d6893dbfba10b&cb="
)

print("Step 1: 请求东方财富API...")
# 代理启用时使用proxy opener，否则用直连
opener = proxy_utils.get_urllib_opener_with_proxy()

for attempt in range(3):
    try:
        req = urllib.request.Request(
            api_url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': 'https://quote.eastmoney.com/',
                'Accept': '*/*'
            }
        )
        if opener:
            response = opener.open(req, timeout=30)
        else:
            response = urllib.request.urlopen(req, timeout=30)
        content = response.read().decode('utf-8')
        break
    except Exception as e:
        print(f"  尝试 {attempt+1}/3 失败: {e}")
        if attempt < 2:
            time.sleep(2)
        else:
            print("  所有尝试失败，退出")
            exit(1)

print("Step 2: 解析JSON数据...")
try:
    # 清理可能的JSONP包装
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
    
    # 过滤ST、退市、新股
    if re.search(r"ST|\*ST|退|N", name or ""):
        continue
    # 过滤创业板(300/301)、科创板(688)、北交所(8/4/920开头)
    if re.match(r"^(300|301|688|8|4|920)", code):
        continue
    
    pct = s.get("f3")
    f11 = s.get("f11")  # 5分钟涨速
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

# 按涨速排序，取前100
filtered.sort(key=lambda x: x["5分钟涨速%"], reverse=True)
top100 = filtered[:100]

# Step 4: 输出结果
print()
print(f"=== 5分钟涨速前100 (实际{len(top100)}只) ===")
print(f"{'排名':>4} {'代码':8} {'名称':8} {'5分涨速':>8} {'涨幅%':>7} {'最新价':>8} {'成交额':>10}")
print("-" * 60)
for i, s in enumerate(top100[:20]):  # 只显示前20
    amt = s["成交额"]
    amt_str = f"{amt/1e8:.1f}亿" if amt > 1e8 else f"{amt/1e4:.0f}万"
    print(f"  {i+1:2d}  {s['代码']:8} {s['名称']:8} {s['5分钟涨速%']:+8.2f} {s['涨幅%']:+7.2f} {s['最新价']:8.2f} {amt_str:>10}")

if len(top100) > 20:
    print(f"  ... (共{len(top100)}只，仅显示前20)")

# Step 5: 保存到文件
import os
data_dir = "/Users/zhangying/projects/study/maneki-agent/data/signals"
os.makedirs(data_dir, exist_ok=True)

today = datetime.now().strftime("%Y%m%d")
time_str = datetime.now().strftime("%H%M%S")
output = {
    "scan_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "trade_date": today,
    "data_source": "eastmoney_http_direct",
    "data_note": "东方财富实时行情(HTTP直连方式获取)",
    "count": len(top100),
    "total_filtered": len(filtered),
    "stocks": top100
}

out_file = f"{data_dir}/{today}_{time_str}.json"
with open(out_file, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)
print(f"\n已保存: {out_file}")
