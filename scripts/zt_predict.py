#!/usr/bin/env python3
"""涨停预测扫描主程序"""
import json
import urllib.request
import re
import websocket
import time
import os
import sys
import datetime
from dotenv import load_dotenv

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

# ===== Step 2: 获取涨速数据 =====
print()
print("=" * 60)
print("Step 2: 获取涨速数据 (Chrome CDP)")
print("=" * 60)

try:
    targets = json.loads(urllib.request.urlopen("http://localhost:9222/json/list", timeout=5).read())
except Exception as e:
    print(f"连接Chrome CDP失败: {e}")
    print("请确保Chrome已启动: open -a 'Google Chrome' --args --remote-debugging-port=9222")
    sys.exit(1)

page_target = None
for t in targets:
    if t.get("type") == "page":
        page_target = t
        break

if not page_target:
    print("未找到可用页面")
    sys.exit(1)

ws_url = page_target["webSocketDebuggerUrl"]
print(f"找到页面: {page_target.get('url', '')[:60]}...")

# 构建API URL
api_url = (
    "https://push2.eastmoney.com/api/qt/clist/get?"
    "np=1&fltt=2&invt=2&"
    "fs=m:0+t:6+f:!2,m:0+t:80+f:!2,m:1+t:2+f:!2,m:1+t:23+f:!2,m:0+t:81+s:262144+f:!2&"
    "fields=f12,f13,f14,f2,f4,f3,f5,f6,f7,f15,f18,f16,f17,f10,f8,f9,f11&"
    "fid=f11&pn=1&pz=500&po=1&dect=1&"
    "ut=fa5fd1943c7b386f172d6893dbfba10b&cb="
)

ws = websocket.create_connection(ws_url, timeout=30)
ws.send(json.dumps({
    "id": 1,
    "method": "Page.navigate",
    "params": {"url": api_url}
}))

time.sleep(3)

ws.send(json.dumps({
    "id": 2,
    "method": "Runtime.evaluate",
    "params": {
        "expression": "document.body ? document.body.innerText : '{}'",
        "returnByValue": True
    }
}))

result = None
while True:
    msg = ws.recv()
    data = json.loads(msg)
    if data.get("id") == 2:
        result = data
        break

ws.close()

# 解析数据
value = result.get("result", {}).get("result", {}).get("value", "{}")
api_data = json.loads(value)

if not api_data.get("data") or not api_data["data"].get("diff"):
    print(f"API返回异常")
    sys.exit(1)

stocks = api_data["data"]["diff"]
print(f"获取到 {len(stocks)} 条数据")

# 过滤数据
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
        "成交额": amount
    })

print(f"过滤后: {len(filtered)} 只")

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
