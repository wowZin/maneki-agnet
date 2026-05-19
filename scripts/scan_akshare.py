#!/usr/bin/env python3
"""涨停预测 - 盘中扫描脚本 (akshare实时数据 + CDP涨速)
数据源分工：
- 涨速: Chrome CDP 东方财富API (f11字段)
- 其他实时数据: akshare (行情/资金流/板块)
- 交易日历: Tushare trade_cal (仅判断交易日)
- 基本面/历史: Tushare REST API (T+1)

akshare安装: pip install akshare
"""
import json
import os
import re
from datetime import datetime, timedelta
import urllib.request

# Tushare用于交易日判断（仅需token）
TUSHARE_TOKEN = "ebba208f5d60f9e86a1fcb39cf6dad5dca63c5288e82637ad59c5ac7"

def tushare_api(api_name, params=None):
    """调用 Tushare REST API（仅用于交易日历等非实时数据）"""
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

def get_surge_rate_cdp():
    """通过 Chrome CDP 请求东方财富API获取5分钟涨速
    返回: [{code, name, surge_rate_5min, pct_change, ...}]
    """
    import json
    url = ("https://push2.eastmoney.com/api/qt/clist/get?"
           "pn=1&pz=500&po=1&np=1&fltt=2&invt=2&fid=f11&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23&"
           "fields=f12,f14,f3,f2,f11,f5,f6,f8,f15,f16,f17")
    
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://quote.eastmoney.com/"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        
        diff = data.get("data", {}).get("diff", [])
        result = []
        for item in diff:
            code = str(item.get("f12", ""))
            name = str(item.get("f14", ""))
            surge = item.get("f11", 0)  # 5分钟涨速
            pct = item.get("f3", 0)     # 涨幅%
            price = item.get("f2", 0)   # 最新价
            vol = item.get("f5", 0)     # 成交量(手)
            amount = item.get("f6", 0)  # 成交额
            turnover = item.get("f8", 0) # 换手率
            
            if surge is None or pct is None:
                continue
            try:
                surge = float(surge)
                pct = float(pct)
            except:
                continue
            
            result.append({
                "code": code,
                "name": name,
                "surge_rate_5min": surge,
                "pct_change": pct,
                "price": price,
                "volume": vol,
                "amount": amount,
                "turnover_rate": turnover,
            })
        return result
    except Exception as e:
        print(f"CDP获取涨速失败: {e}")
        return None

def get_realtime_quotes_akshare():
    """通过 akshare 获取实时行情（东方财富数据源）"""
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        result = []
        for _, row in df.iterrows():
            result.append({
                "code": row.get("代码", ""),
                "name": row.get("名称", ""),
                "price": row.get("最新价", 0),
                "pct_change": row.get("涨跌幅", 0),
                "volume": row.get("成交量", 0),
                "amount": row.get("成交额", 0),
                "turnover_rate": row.get("换手率", 0),
                "volume_ratio": row.get("量比", 0),
                "high": row.get("最高", 0),
                "low": row.get("最低", 0),
                "open": row.get("今开", 0),
                "pre_close": row.get("昨收", 0),
            })
        return result
    except Exception as e:
        print(f"akshare获取实时行情失败: {e}")
        return None

def get_fund_flow_akshare(code, market='auto'):
    """通过 akshare 获取个股资金流向"""
    try:
        import akshare as ak
        if market == 'auto':
            market = 'sh' if code.startswith('6') else 'sz'
        df = ak.stock_individual_fund_flow(stock=code, market=market)
        if df is None or len(df) == 0:
            return None
        latest = df.iloc[-1]
        return {
            "main_net_inflow": latest.get("主力净流入-净额", 0),
            "main_net_inflow_pct": latest.get("主力净流入-净占比", 0),
            "super_net_inflow": latest.get("超大单净流入-净额", 0),
            "big_net_inflow": latest.get("大单净流入-净额", 0),
            "mid_net_inflow": latest.get("中单净流入-净额", 0),
            "small_net_inflow": latest.get("小单净流入-净额", 0),
        }
    except Exception as e:
        return None

def get_concept_boards_akshare():
    """通过 akshare 获取概念板块列表及涨停统计"""
    try:
        import akshare as ak
        df = ak.stock_board_concept_name_em()
        result = []
        for _, row in df.iterrows():
            result.append({
                "name": row.get("板块名称", ""),
                "code": row.get("板块代码", ""),
                "pct_change": row.get("涨跌幅", 0),
                "limit_up_count": row.get("涨停家数", 0),
                "total_count": row.get("总家数", 0),
            })
        return result
    except Exception as e:
        print(f"akshare获取概念板块失败: {e}")
        return None

def filter_stocks(stocks):
    """过滤: 排除ST/退市/新股/创业板/科创板/北交所"""
    filtered = []
    for s in stocks:
        code = s.get("code", "")
        name = s.get("name", "")
        
        # 排除ST、退市、N开头
        if re.search(r"ST|\*ST|退|N", name or ""):
            continue
        # 排除创业板(300/301)、科创板(688)、北交所(8开头/4开头)
        if re.match(r"^(300|301|688|8|4)", code):
            continue
        
        filtered.append(s)
    return filtered

# ========== 主流程 ==========
print("=" * 60)
print("涨停预测 - 盘中扫描")
print(f"扫描时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 60)

# Step 0: 检查交易日
print("\nStep 0: 检查交易日...")
today = datetime.now().strftime("%Y%m%d")
try:
    cal = tushare_api("trade_cal", {"exchange": "SSE", "start_date": today, "end_date": today})
    if cal and cal[0].get("is_open") == 1:
        print(f"  ✅ {today} 是交易日，继续扫描")
    else:
        print(f"  ⏭️ {today} 非交易日，跳过扫描")
        exit(0)
except Exception as e:
    print(f"  ⚠️ 检查交易日失败: {e}，继续执行")

# Step 1: 获取涨速 (CDP东方财富)
print("\nStep 1: 获取5分钟涨速 (CDP东方财富API)...")
surge_stocks = get_surge_rate_cdp()
if surge_stocks:
    surge_filtered = filter_stocks(surge_stocks)
    surge_filtered.sort(key=lambda x: x.get("surge_rate_5min", 0), reverse=True)
    print(f"  ✅ 获取到 {len(surge_stocks)} 只，过滤后 {len(surge_filtered)} 只")
    print("\n涨速Top 10:")
    for i, s in enumerate(surge_filtered[:10]):
        print(f"    {i+1:2d}. {s['code']} {s['name']:8s} 5分钟涨速:{s['surge_rate_5min']:+5.2f}% 涨幅:{s['pct_change']:+6.2f}%")
else:
    print("  ❌ CDP获取涨速失败")
    surge_filtered = []

# Step 2: 获取实时行情 (akshare)
print("\nStep 2: 获取实时行情 (akshare)...")
ak_stocks = get_realtime_quotes_akshare()
if ak_stocks:
    ak_filtered = filter_stocks(ak_stocks)
    # 取涨幅>=3%
    ak_above3 = [s for s in ak_filtered if float(s.get("pct_change", 0)) >= 3]
    print(f"  ✅ 获取到 {len(ak_stocks)} 只，涨幅>=3%: {len(ak_above3)} 只")
else:
    print("  ❌ akshare获取行情失败")
    ak_above3 = []

# Step 3: 获取概念板块 (akshare)
print("\nStep 3: 获取概念板块 (akshare)...")
boards = get_concept_boards_akshare()
if boards:
    # 按涨停家数排序
    boards.sort(key=lambda x: x.get("limit_up_count", 0), reverse=True)
    print(f"  ✅ 获取到 {len(boards)} 个概念板块")
    print("  涨停数Top 5:")
    for i, b in enumerate(boards[:5]):
        print(f"    {i+1}. {b['name']} 涨停:{b.get('limit_up_count',0)}家 涨幅:{b.get('pct_change',0):+.2f}%")
else:
    print("  ❌ 获取概念板块失败")

# Step 4: 保存结果
data_dir = "/Users/zhangying/projects/study/maneki-agent/data/signals"
os.makedirs(data_dir, exist_ok=True)

now_str = datetime.now().strftime("%H%M")
output_file = f"{data_dir}/{today}_{now_str}.json"
result = {
    "scan_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "trade_date": today,
    "data_source": {
        "surge_rate": "CDP_eastmoney",
        "realtime_quotes": "akshare",
        "fund_flow": "akshare",
        "concept_boards": "akshare",
        "trade_calendar": "tushare"
    },
    "surge_top100": surge_filtered[:100],
    "pct_above3": ak_above3[:100],
    "concept_boards_top": boards[:30] if boards else [],
}

with open(output_file, 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print("\n" + "=" * 60)
print(f"结果已保存: {output_file}")
print(f"统计: 涨速Top {len(surge_filtered[:100])} | 涨幅>=3% {len(ak_above3)} | 概念板块 {len(boards) if boards else 0}")
print("=" * 60)
