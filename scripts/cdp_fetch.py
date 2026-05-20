#!/usr/bin/env python3
"""CDP涨速数据获取模块 - 带重试机制 + requests+代理支持

核心改进：
1. 函数化封装（不再用全局exit，可被pipeline直接调用）
2. 连接/导航/解析三层重试
3. 每层独立重试策略（连接重试间隔短，导航重试间隔长）
4. 非交易时段优雅返回空而非exit(0)
5. requests+代理方式获取涨速数据（主方式，CDP备选）

使用方式:
  # requests+代理（默认，推荐）
  from cdp_fetch import get_surge_rate_cdp
  stocks = get_surge_rate_cdp(method="requests")

  # CDP+代理（备选）
  stocks = get_surge_rate_cdp(method="cdp")

  # 纯CDP无代理（向后兼容）
  stocks = get_surge_rate_cdp(method="cdp_no_proxy")

  # 直接用requests函数
  from cdp_fetch import get_surge_rate_requests
  stocks = get_surge_rate_requests()

依赖: websocket-client (pip install websocket-client), requests, python-dotenv
"""
import json
import os
import re
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import proxy_utils

PROJECT_DIR = Path("/Users/zhangying/projects/study/maneki-agent")
DATA_DIR = PROJECT_DIR / "data" / "signals"
CDP_PORT = 9222
CDP_LIST_URL = f"http://localhost:{CDP_PORT}/json/list"
CDP_VERSION_URL = f"http://localhost:{CDP_PORT}/json/version"

# 东方财富push2 API URL - 沪深A股，按5分钟涨速排序
API_URL = (
    "https://push2.eastmoney.com/api/qt/clist/get?"
    "np=1&fltt=2&invt=2&"
    "fs=m:0+t:6+f:!2,m:0+t:80+f:!2,m:1+t:2+f:!2,m:1+t:23+f:!2,m:0+t:81+s:262144+f:!2&"
    "fields=f12,f13,f14,f2,f4,f3,f5,f6,f7,f15,f18,f16,f17,f10,f8,f9,f11&"
    "fid=f11&pn=1&pz=200&po=1&dect=1&"
    "ut=fa5fd1943c7b386f172d6893dbfba10b&cb="
)
EASTMONEY_HOME = "https://www.eastmoney.com/"


def is_trading_hours():
    """检查当前是否在交易时段内（9:30-11:30, 13:00-15:00）
    Returns: (bool, str_or_None) - (是否交易时段, 原因描述)
    """
    now = datetime.now()
    weekday = now.weekday()
    if weekday >= 5:
        return False, "周末休市"
    hour = now.hour
    minute = now.minute
    hm = hour * 100 + minute
    if (930 <= hm <= 1130) or (1300 <= hm <= 1500):
        return True, None
    return False, f"非交易时段 ({hour:02d}:{minute:02d})"


def check_cdp_ready():
    """检查CDP端口是否就绪（验证返回内容含Browser字段）
    Returns: bool
    """
    try:
        resp = urllib.request.urlopen(CDP_VERSION_URL, timeout=3)
        data = resp.read()
        return b"Browser" in data
    except Exception:
        return False


def connect_cdp(max_retries=3, retry_interval=2):
    """连接Chrome CDP获取WebSocket URL
    Args:
        max_retries: 最大重试次数（默认3）
        retry_interval: 重试间隔秒（默认2）
    Returns: (websocket, str) - (WS连接对象, 页面URL) 或 (None, None)
    """
    import websocket as ws_mod

    for attempt in range(1, max_retries + 1):
        try:
            targets = json.loads(
                urllib.request.urlopen(CDP_LIST_URL, timeout=5).read()
            )
            page_target = None
            for t in targets:
                if t.get("type") == "page":
                    page_target = t
                    break

            if not page_target:
                print(f"  [CDP连接] 第{attempt}次: 未找到可用页面, 重试...")
                time.sleep(retry_interval)
                continue

            ws_url = page_target["webSocketDebuggerUrl"]
            page_url = page_target.get("url", "")[:60]
            conn = ws_mod.create_connection(ws_url, timeout=30)
            print(f"  [CDP连接] 第{attempt}次: 成功, 页面={page_url}...")
            return conn, page_url

        except Exception as e:
            print(f"  [CDP连接] 第{attempt}次失败: {e}")
            if attempt < max_retries:
                print(f"    等待{retry_interval}秒后重试...")
                time.sleep(retry_interval)
            else:
                print(f"  [CDP连接] 已达最大重试次数({max_retries}), 放弃")
                return None, None


def navigate_and_fetch(ws, max_retries=2, home_wait=2, api_wait=3):
    """导航到东方财富首页建立session，然后导航到API获取数据
    Args:
        ws: WebSocket连接对象
        max_retries: 导航重试次数（默认2，每次重试重新访问首页）
        home_wait: 首页加载等待秒（默认2）
        api_wait: API响应等待秒（默认3）
    Returns: dict - API返回的原始JSON数据，或None
    """
    msg_id = 0

    for attempt in range(1, max_retries + 1):
        msg_id = 0
        try:
            # Step 1: 访问东方财富首页建立session
            msg_id += 1
            ws.send(json.dumps({
                "id": msg_id,
                "method": "Page.navigate",
                "params": {"url": EASTMONEY_HOME}
            }))
            print(f"  [CDP导航] 第{attempt}次: 访问首页建立session...")
            time.sleep(home_wait)

            # Step 2: 导航到API URL
            msg_id += 1
            ws.send(json.dumps({
                "id": msg_id,
                "method": "Page.navigate",
                "params": {"url": API_URL}
            }))
            print(f"  [CDP导航] 第{attempt}次: 导航到API...")
            time.sleep(api_wait)

            # Step 3: 读取页面内容
            msg_id += 1
            ws.send(json.dumps({
                "id": msg_id,
                "method": "Runtime.evaluate",
                "params": {
                    "expression": "document.body ? document.body.innerText : '{}'",
                    "returnByValue": True
                }
            }))

            result = None
            deadline = time.time() + 10  # 最多等10秒读响应
            while time.time() < deadline:
                try:
                    msg = ws.recv()
                    data = json.loads(msg)
                    if data.get("id") == msg_id:
                        result = data
                        break
                except Exception:
                    continue

            if result is None:
                print(f"  [CDP导航] 第{attempt}次: 未收到响应, 重试...")
                continue

            # 提取页面文本
            value = result.get("result", {}).get("result", {}).get("value", "{}")

            # 解析JSON
            try:
                api_data = json.loads(value)
            except json.JSONDecodeError as e:
                print(f"  [CDP导航] 第{attempt}次: JSON解析失败({e}), 内容={value[:100]}")
                if attempt < max_retries:
                    print(f"    重新访问首页重试...")
                    continue
                return None

            # 验证API数据结构
            if not api_data.get("data") or not api_data["data"].get("diff"):
                print(f"  [CDP导航] 第{attempt}次: API返回空数据, 响应={json.dumps(api_data, ensure_ascii=False)[:200]}")
                if attempt < max_retries:
                    print(f"    可能session失效, 重新访问首页...")
                    continue
                return None

            stocks = api_data["data"]["diff"]
            print(f"  [CDP导航] 第{attempt}次: 成功获取{len(stocks)}条数据")
            return api_data

        except Exception as e:
            print(f"  [CDP导航] 第{attempt}次异常: {e}")
            if attempt < max_retries:
                print(f"    重试...")
                continue
            return None

    return None


def parse_surge_data(api_data):
    """解析CDP返回的原始数据，过滤+排序，返回标准化股票列表
    Args:
        api_data: CDP API返回的完整JSON dict
    Returns: list[dict] - 过滤排序后的股票列表（最多100只）
    """
    if not api_data or not api_data.get("data") or not api_data.get("data", {}).get("diff"):
        return []

    stocks = api_data["data"]["diff"]
    filtered = []

    for s in stocks:
        code = str(s.get("f12", ""))
        name = str(s.get("f14", ""))

        # 过滤ST、退市、新股
        if re.search(r"ST|\*ST|退|N", name):
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
        except (ValueError, TypeError):
            continue

        filtered.append({
            "代码": code,
            "名称": name,
            "涨幅%": pct,
            "5分钟涨速%": f11,
            "最新价": price,
            "成交额": amount,
            "量比": s.get("f10", "-"),
        })

    # 按涨速降序排序
    filtered.sort(key=lambda x: x["5分钟涨速%"], reverse=True)
    return filtered[:100]


def save_surge_data(stocks, total_filtered=None):
    """保存涨速扫描结果到data/signals/目录
    Args:
        stocks: 过滤排序后的股票列表
        total_filtered: 过滤后的总数量（含未取top100的）
    Returns: str - 保存的文件路径
    """
    os.makedirs(DATA_DIR, exist_ok=True)

    today = datetime.now().strftime("%Y%m%d")
    time_str = datetime.now().strftime("%H%M%S")

    output = {
        "scan_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "trade_date": today,
        "data_source": "eastmoney_cdp_realtime",
        "data_note": "东方财富实时行情(Chrome CDP导航方式获取,带重试机制)",
        "count": len(stocks),
        "total_filtered": total_filtered or len(stocks),
        "stocks": stocks,
    }

    out_file = str(DATA_DIR / f"{today}_{time_str}.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"  已保存: {out_file}")
    return out_file


def get_surge_rate_requests(proxies=None, session=None, max_retries=3):
    """requests+代理获取涨速数据（主方式）

    流程:
    1. 创建带代理的requests.Session
    2. 访问东方财富首页拿cookies
    3. 请求push2 API获取涨速数据
    4. 解析+过滤+排序

    Args:
        proxies: 代理dict {"http": ..., "https": ...}，None则自动获取
        session: 自定义requests.Session，None则自动创建
        max_retries: 最大重试次数（默认3）
    Returns: list[dict] - 涨速Top100股票列表，失败返回None
    """
    import requests

    print(f"=== requests+代理涨速扫描 (重试{max_retries}次) ===")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 创建session
    if session is None:
        session = proxy_utils.get_requests_session_with_proxy()
    if proxies and session:
        session.proxies = proxies

    # 请求API（带重试）
    for attempt in range(1, max_retries + 1):
        try:
            # 代理过期时刷新
            if proxy_utils.is_proxy_enabled() and proxy_utils._cached_proxy:
                if time.time() >= proxy_utils._cached_proxy["expires_at"]:
                    new_addr = proxy_utils.get_proxy_ip(force_refresh=True)
                    if new_addr:
                        proxy_url = f"http://{new_addr}"
                        session.proxies = {"http": proxy_url, "https": proxy_url}

            resp = session.get(API_URL, timeout=30, verify=True)
            content = resp.text
            print(f"  [requests] 第{attempt}次: HTTP状态={resp.status_code}, 内容长度={len(content)}")

            # 解析JSON
            content = content.strip()
            if content.startswith('(') and content.endswith(')'):
                content = content[1:-1]
            api_data = json.loads(content)

            # 验证数据结构
            if not api_data.get("data") or not api_data.get("data", {}).get("diff"):
                print(f"  [requests] 第{attempt}次: API返回空数据, 响应={json.dumps(api_data, ensure_ascii=False)[:200]}")
                if attempt < max_retries:
                    print(f"    可能代理IP失效，刷新代理重试...")
                    if proxy_utils.is_proxy_enabled():
                        new_addr = proxy_utils.get_proxy_ip(force_refresh=True)
                        if new_addr:
                            proxy_url = f"http://{new_addr}"
                            session.proxies = {"http": proxy_url, "https": proxy_url}
                    time.sleep(2)
                    continue
                return None

            # 解析成功
            stocks = api_data["data"]["diff"]
            print(f"  [requests] 第{attempt}次: 成功获取{len(stocks)}条数据")
            all_filtered = parse_surge_data(api_data)
            total_count = len(api_data.get("data", {}).get("diff", []))
            print(f"  原始{total_count}条 -> 过滤后{len(all_filtered)}只")

            # 保存
            out_file = save_surge_data(all_filtered, total_filtered=total_count)

            # 打印Top20
            print(f"\n=== 涨速前{min(20, len(all_filtered))}只 ===")
            print(f"{'排名':>4} {'代码':8} {'名称':8} {'5分涨速':>8} {'涨幅%':>7} {'最新价':>8} {'成交额':>10}")
            print("-" * 60)
            for i, s in enumerate(all_filtered[:20]):
                amt = s["成交额"]
                amt_str = f"{amt/1e8:.1f}亿" if amt > 1e8 else f"{amt/1e4:.0f}万"
                print(f"  {i+1:2d}  {s['代码']:8} {s['名称']:8} {s['5分钟涨速%']:+8.2f} {s['涨幅%']:+7.2f} {s['最新价']:8.2f} {amt_str:>10}")

            if len(all_filtered) > 20:
                print(f"  ... (共{len(all_filtered)}只，仅显示前20)")

            return all_filtered

        except requests.exceptions.ProxyError as e:
            print(f"  [requests] 第{attempt}次: 代理连接失败({e})")
            if attempt < max_retries:
                print(f"    刷新代理重试...")
                if proxy_utils.is_proxy_enabled():
                    new_addr = proxy_utils.get_proxy_ip(force_refresh=True)
                    if new_addr:
                        proxy_url = f"http://{new_addr}"
                        session.proxies = {"http": proxy_url, "https": proxy_url}
                time.sleep(2)
                continue
            return None
        except requests.exceptions.ConnectionError as e:
            print(f"  [requests] 第{attempt}次: 连接错误({e})")
            if attempt < max_retries:
                time.sleep(2)
                continue
            return None
        except Exception as e:
            print(f"  [requests] 第{attempt}次异常: {e}")
            if attempt < max_retries:
                time.sleep(2)
                continue
            return None

    return None


def get_surge_rate_cdp(
    connect_retries=3,
    connect_retry_interval=2,
    navigate_retries=2,
    home_wait=2,
    api_wait=3,
    skip_trading_check=False,
    method="requests",
):
    """完整的涨速获取流程（支持requests+代理和CDP两种方式）

    Args:
        connect_retries: CDP连接最大重试次数（默认3）
        connect_retry_interval: 连接重试间隔秒（默认2）
        navigate_retries: 导航重试次数（默认2）
        home_wait: 首页加载等待秒（默认2）
        api_wait: API响应等待秒（默认3）
        skip_trading_check: 是否跳过交易时段检查（默认False）
        method: 获取方式 - "requests"(requests+代理,默认), "cdp"(CDP+代理), "cdp_no_proxy"(纯CDP,向后兼容)
    Returns: list[dict] - 涨速Top100股票列表，失败返回None
    """
    # 1. 交易时段检查
    if not skip_trading_check:
        trading, reason = is_trading_hours()
        if not trading:
            print(f"  跳过扫描: {reason}")
            print(f"  涨速数据仅在交易时段可用（9:30-11:30, 13:00-15:00）")
            return None

    # 根据method选择获取方式
    if method == "requests":
        return get_surge_rate_requests(
            max_retries=connect_retries,
        )
    elif method == "cdp":
        # CDP+代理方式: 启动带代理的Chromium
        proxy_addr = proxy_utils.get_proxy_ip()
        if proxy_addr is None:
            print("  [CDP代理] 获取代理IP失败，降级为纯CDP方式")
            method = "cdp_no_proxy"
        else:
            proc = proxy_utils.launch_chromium_with_proxy(proxy_addr, port=CDP_PORT)
            if proc is None:
                print("  [CDP代理] Chromium启动失败，降级为纯CDP方式")
                method = "cdp_no_proxy"
            else:
                try:
                    # 使用已启动的CDP+代理Chromium获取数据
                    print(f"=== CDP+代理涨速扫描 ===")
                    print(f"  代理: {proxy_addr}")
                    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

                    print("\n[1/3] 连接CDP...")
                    ws, page_url = connect_cdp(
                        max_retries=connect_retries,
                        retry_interval=connect_retry_interval,
                    )
                    if ws is None:
                        print("  CDP连接失败，扫描终止")
                        proxy_utils.kill_chromium(proc)
                        return None

                    try:
                        print("\n[2/3] 导航获取涨速数据...")
                        api_data = navigate_and_fetch(
                            ws,
                            max_retries=navigate_retries,
                            home_wait=home_wait,
                            api_wait=api_wait,
                        )
                    finally:
                        try:
                            ws.close()
                        except Exception:
                            pass

                    if api_data is None:
                        print("  导航获取失败，扫描终止")
                        proxy_utils.kill_chromium(proc)
                        return None

                    print("\n[3/3] 解析过滤数据...")
                    all_filtered = parse_surge_data(api_data)
                    total_count = len(api_data.get("data", {}).get("diff", []))
                    print(f"  原始{total_count}条 -> 过滤后{len(all_filtered)}只")

                    out_file = save_surge_data(all_filtered, total_filtered=total_count)

                    print(f"\n=== 涨速前{min(20, len(all_filtered))}只 ===")
                    print(f"{'排名':>4} {'代码':8} {'名称':8} {'5分涨速':>8} {'涨幅%':>7} {'最新价':>8} {'成交额':>10}")
                    print("-" * 60)
                    for i, s in enumerate(all_filtered[:20]):
                        amt = s["成交额"]
                        amt_str = f"{amt/1e8:.1f}亿" if amt > 1e8 else f"{amt/1e4:.0f}万"
                        print(f"  {i+1:2d}  {s['代码']:8} {s['名称']:8} {s['5分钟涨速%']:+8.2f} {s['涨幅%']:+7.2f} {s['最新价']:8.2f} {amt_str:>10}")

                    if len(all_filtered) > 20:
                        print(f"  ... (共{len(all_filtered)}只，仅显示前20)")

                    proxy_utils.kill_chromium(proc)
                    return all_filtered
                except Exception as e:
                    print(f"  CDP+代理异常: {e}")
                    proxy_utils.kill_chromium(proc)
                    return None

    # method == "cdp_no_proxy": 纯CDP方式(向后兼容)
    print(f"=== CDP涨速扫描 (无代理, 重试: 连接{connect_retries}次/导航{navigate_retries}次) ===")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 1. 交易时段检查
    if not skip_trading_check:
        trading, reason = is_trading_hours()
        if not trading:
            print(f"  跳过扫描: {reason}")
            print(f"  涨速数据仅在交易时段可用（9:30-11:30, 13:00-15:00）")
            return None

    # 2. 连接CDP
    print("\n[1/3] 连接Chrome CDP...")
    ws, page_url = connect_cdp(
        max_retries=connect_retries,
        retry_interval=connect_retry_interval,
    )
    if ws is None:
        print("  CDP连接失败，扫描终止")
        return None

    try:
        # 3. 导航+获取数据
        print("\n[2/3] 导航获取涨速数据...")
        api_data = navigate_and_fetch(
            ws,
            max_retries=navigate_retries,
            home_wait=home_wait,
            api_wait=api_wait,
        )
    finally:
        try:
            ws.close()
        except Exception:
            pass

    if api_data is None:
        print("  导航获取失败，扫描终止")
        return None

    # 4. 解析过滤
    print("\n[3/3] 解析过滤数据...")
    all_filtered = parse_surge_data(api_data)
    # parse_surge_data 返回top100，这里需要总数
    total_count = len(api_data.get("data", {}).get("diff", []))
    print(f"  原始{total_count}条 -> 过滤后{len(all_filtered)}只")

    # 5. 保存
    out_file = save_surge_data(all_filtered, total_filtered=total_count)

    # 6. 打印Top20
    print(f"\n=== 涨速前{min(20, len(all_filtered))}只 ===")
    print(f"{'排名':>4} {'代码':8} {'名称':8} {'5分涨速':>8} {'涨幅%':>7} {'最新价':>8} {'成交额':>10}")
    print("-" * 60)
    for i, s in enumerate(all_filtered[:20]):
        amt = s["成交额"]
        amt_str = f"{amt/1e8:.1f}亿" if amt > 1e8 else f"{amt/1e4:.0f}万"
        print(f"  {i+1:2d}  {s['代码']:8} {s['名称']:8} {s['5分钟涨速%']:+8.2f} {s['涨幅%']:+7.2f} {s['最新价']:8.2f} {amt_str:>10}")

    if len(all_filtered) > 20:
        print(f"  ... (共{len(all_filtered)}只，仅显示前20)")

    return all_filtered


# ===== CLI入口（向后兼容 scan_cdp.py 的独立运行模式）=====
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="涨速数据获取")
    parser.add_argument("--method", choices=["requests", "cdp", "cdp_no_proxy"],
                        default="requests", help="获取方式: requests(默认), cdp, cdp_no_proxy")
    parser.add_argument("--skip-trading-check", action="store_true", help="跳过交易时段检查")
    args = parser.parse_args()

    result = get_surge_rate_cdp(
        method=args.method,
        skip_trading_check=args.skip_trading_check,
    )
    if result is None:
        # 非交易时段或失败，exit 0（兼容cron wrapper）
        exit(0)