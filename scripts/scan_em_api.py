#!/usr/bin/env python3
"""
通过CDP连接Chrome，直接调用东方财富行情API获取涨速数据（集成代理）
不需要拦截请求，直接用Chrome的session发请求即可
"""
import json
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

# 添加scripts目录到sys.path以便导入proxy_utils
sys.path.insert(0, str(Path(__file__).parent))
import proxy_utils

# 东方财富A股实时行情API（公开接口，无需登录）
# 按涨跌幅降序
EASTMONEY_API = "https://push2.eastmoney.com/api/qt/clist/get"

def fetch_em_stocks(page=1, page_size=100, sort_field="f3", sort_order="desc"):
    """
    获取东方财富A股行情数据（支持代理）
    f3=涨跌幅, f2=最新价, f12=代码, f14=名称, f15=最高, f16=最低, f17=今开
    f6=成交额, f5=涨跌幅(幅度), f8=换手率, f10=量比
    """
    params = {
        "pn": page,
        "pz": page_size,
        "po": sort_order,
        "np": 1,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2,
        "invt": 2,
        "fid": sort_field,
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",  # 沪深A股
        "fields": "f2,f3,f4,f5,f6,f7,f8,f10,f12,f14,f15,f16,f17,f18"
    }

    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{EASTMONEY_API}?{query}"

    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer": "https://quote.eastmoney.com/"
    })

    # 代理启用时使用proxy opener，否则直连
    opener = proxy_utils.get_urllib_opener_with_proxy()
    if opener:
        with opener.open(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    else:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))

    return data

print("=== 涨速扫描 (东方财富API) ===")
print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# 获取涨幅前200的股票
print("Step 1: 获取涨幅排名...")
all_stocks = []
for page in range(1, 3):  # 取前2页，每页100
    try:
        data = fetch_em_stocks(page=page, page_size=100, sort_field="f3", sort_order="desc")
        if data.get("data") and data["data"].get("diff"):
            stocks = data["data"]["diff"]
            all_stocks.extend(stocks)
            print(f"  第{page}页: {len(stocks)} 只")
    except Exception as e:
        print(f"  第{page}页失败: {e}")

print(f"  共获取 {len(all_stocks)} 只")
print()

# 过滤和整理
import re
filtered = []
for s in all_stocks:
    code = s.get("f12", "")
    name = s.get("f14", "")
    
    # 排除ST、退市、N
    if re.search(r"ST|\*ST|退|N", name):
        continue
    # 排除创业板(300/301)、科创板(688)
    if re.match(r"^(30|688)", code):
        continue
    
    pct = s.get("f3")
    price = s.get("f2")
    if pct is None or price is None or pct == "-" or price == "-":
        continue
    try:
        pct = float(pct)
        price = float(price)
    except:
        continue
    
    if pct >= 2:
        filtered.append({
            "代码": code,
            "名称": name,
            "最新价": price,
            "涨跌幅%": pct,
            "成交额": s.get("f6"),
            "换手率": s.get("f8"),
            "量比": s.get("f10"),
        })

print(f"Step 2: 过滤后涨幅>=2% (沪深主板): {len(filtered)} 只")
print()

# 显示结果
print("=== 涨幅Top 30 ===")
for i, s in enumerate(filtered[:30]):
    amt = s["成交额"]
    amt_str = f"{amt/1e8:.1f}亿" if amt and amt > 1e8 else f"{amt/1e4:.0f}万" if amt else "-"
    print(f"  {i+1:2d}. {s['代码']} {s['名称']:6s}  涨幅:{s['涨跌幅%']:+6.2f}%  "
          f"价格:{s['最新价']:8.2f}  成交:{amt_str}  量比:{s.get('量比','-')}")

# 保存
data_dir = "/Users/zhangying/projects/study/maneki-agent/data/signals"
os.makedirs(data_dir, exist_ok=True)

today = datetime.now().strftime("%Y%m%d")
output = {
    "scan_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "trade_date": today,
    "source": "eastmoney_push_api",
    "count": len(filtered),
    "top_stocks": filtered[:100]
}

out_file = f"{data_dir}/surge_em_{today}.json"
with open(out_file, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"\n已保存: {out_file}")
