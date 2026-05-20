#!/usr/bin/env python3
"""通过Chrome CDP获取东方财富涨速数据 - 直接导航到API URL

[DEPRECATED] 本脚本已被 cdp_fetch.py 替代。
  - cdp_fetch.py 提供更完善的重试逻辑、模块化设计、数据解析和存储功能
  - 请使用: python scripts/cdp_fetch.py --skip-trading-check (或其他参数)
  - 如需作为模块导入: from cdp_fetch import get_surge_rate_cdp, parse_surge_data, save_surge_data
  - 本脚本仅保留作为参考，不再维护
"""
import json
import urllib.request
import re
import warnings

warnings.warn(
    "scan_cdp.py 已废弃，请使用 cdp_fetch.py 替代。"
    "作为模块导入: from cdp_fetch import get_surge_rate_cdp; "
    "作为脚本运行: python scripts/cdp_fetch.py",
    DeprecationWarning,
    stacklevel=2
)
import websocket
import time
from datetime import datetime

def is_trading_hours():
    """检查当前是否在交易时段内（9:30-11:30, 13:00-15:00）"""
    now = datetime.now()
    weekday = now.weekday()
    # 周末不开市
    if weekday >= 5:
        return False, "周末休市"
    hour = now.hour
    minute = now.minute
    hm = hour * 100 + minute
    # 早盘 9:30-11:30, 午盘 13:00-15:00
    if (930 <= hm <= 1130) or (1300 <= hm <= 1500):
        return True, None
    return False, f"非交易时段 ({hour:02d}:{minute:02d})"

print("=== 5分钟涨速扫描 (Chrome CDP) ===")
print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# 交易时段检查
trading, reason = is_trading_hours()
if not trading:
    print(f"跳过扫描: {reason}")
    print("涨速数据仅在交易时段可用（9:30-11:30, 13:00-15:00）")
    exit(0)

print("Step 1: 连接Chrome CDP...")
try:
    targets = json.loads(urllib.request.urlopen("http://localhost:9222/json/list", timeout=5).read())
except Exception as e:
    print(f"  连接失败: {e}")
    print("  请确保Chrome已启动: open -a 'Google Chrome' --args --remote-debugging-port=9222")
    exit(1)

page_target = None
for t in targets:
    if t.get("type") == "page":
        page_target = t
        break

if not page_target:
    print("  未找到可用页面")
    exit(1)

ws_url = page_target["webSocketDebuggerUrl"]
print(f"  找到页面: {page_target.get('url', '')[:60]}...")

# 连接WebSocket
ws = websocket.create_connection(ws_url, timeout=30)

# Step 2: 先访问东方财富首页建立session（绕过反爬）
print("Step 2: 建立session（访问东方财富首页）...")
ws.send(json.dumps({
    "id": 1,
    "method": "Page.navigate",
    "params": {"url": "https://www.eastmoney.com/"}
}))
time.sleep(2)  # 等待首页加载

# 构建API URL - 沪深A股，按5分钟涨速排序
# pz=200 获取200条数据，过滤后约剩100条
api_url = (
    "https://push2.eastmoney.com/api/qt/clist/get?"
    "np=1&fltt=2&invt=2&"
    "fs=m:0+t:6+f:!2,m:0+t:80+f:!2,m:1+t:2+f:!2,m:1+t:23+f:!2,m:0+t:81+s:262144+f:!2&"
    "fields=f12,f13,f14,f2,f4,f3,f5,f6,f7,f15,f18,f16,f17,f10,f8,f9,f11&"
    "fid=f11&pn=1&pz=200&po=1&dect=1&"
    "ut=fa5fd1943c7b386f172d6893dbfba10b&cb="
)

print("Step 3: 导航到东方财富API...")
ws.send(json.dumps({
    "id": 2,
    "method": "Page.navigate",
    "params": {"url": api_url}
}))

# 等待导航完成
time.sleep(3)

# Step 4: 读取页面内容
print("Step 4: 读取响应数据...")
ws.send(json.dumps({
    "id": 3,
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
    if data.get("id") == 3:
        result = data
        break

ws.close()

# Step 5: 解析结果
print("Step 5: 解析数据...")
value = result.get("result", {}).get("result", {}).get("value", "{}")

try:
    api_data = json.loads(value)
except json.JSONDecodeError as e:
    print(f"  JSON解析失败: {e}")
    print(f"  原始内容: {value[:200]}")
    exit(1)

if not api_data.get("data") or not api_data["data"].get("diff"):
    print(f"  API返回异常: {json.dumps(api_data, ensure_ascii=False)[:200]}")
    exit(1)

stocks = api_data["data"]["diff"]
print(f"  获取到 {len(stocks)} 条数据")

# Step 6: 过滤数据
print("Step 6: 过滤数据...")
filtered = []
for s in stocks:
    code = s.get("f12", "")
    name = s.get("f14", "")
    
    # 过滤ST、退市、新股
    if re.search(r"ST|\*ST|退|N", name or ""):
        continue
    # 过滤创业板(300/301)、科创板(688)、北交所(8/920开头)、B股(900/200开头)
    if re.match(r"^(300|301|688|8|920|900|200)", code):
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

# Step 6: 输出结果
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

# Step 7: 保存到文件
import os
data_dir = "/Users/zhangying/projects/study/maneki-agent/data/signals"
os.makedirs(data_dir, exist_ok=True)

today = datetime.now().strftime("%Y%m%d")
time_str = datetime.now().strftime("%H%M%S")
output = {
    "scan_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "trade_date": today,
    "data_source": "eastmoney_cdp_realtime",
    "data_note": "东方财富实时行情(Chrome CDP导航方式获取)",
    "count": len(top100),
    "total_filtered": len(filtered),
    "stocks": top100
}

out_file = f"{data_dir}/{today}_{time_str}.json"
with open(out_file, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)
print(f"\n已保存: {out_file}")
