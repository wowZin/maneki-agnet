#!/usr/bin/env python3
"""东方财富代理IP工具模块

动态代理(zdtps.com): 先调API获取代理IP，再用该IP转发请求。
代理IP有效期约130秒，过期自动刷新。

使用方式:
  from proxy_utils import is_proxy_enabled, get_proxy_ip, get_proxies_dict
  from proxy_utils import get_requests_session_with_proxy, get_urllib_opener_with_proxy

  if is_proxy_enabled():
      session = get_requests_session_with_proxy()
      resp = session.get(API_URL)
"""

import json
import os
import time
import urllib.request
from pathlib import Path

# 加载.env
from dotenv import load_dotenv
SCRIPT_PATH = Path(__file__).resolve().parent.parent
PROJECT_DIR = SCRIPT_PATH if str(SCRIPT_PATH).endswith("maneki-agent") else Path.cwd()
load_dotenv(PROJECT_DIR / ".env")

# === 代理IP服务配置 (从.env读取) ===
PROXY_ENABLED = os.getenv("PROXY_ENABLED", "false").lower() in ("true", "1", "yes")
PROXY_API_URL = os.getenv("PROXY_API_URL", "http://s189.zdtps.com:8080/GetIP/")
PROXY_INST_ID = os.getenv("PROXY_INST_ID", "")
PROXY_AKEY = os.getenv("PROXY_AKEY", "")

# 模拟浏览器UA
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)

# 东方财富首页(用于建立session拿cookies)
EASTMONEY_HOME = "https://www.eastmoney.com/"

# 代理IP缓存: {"ip": str, "port": int, "expires_at": float}
_cached_proxy = None


def is_proxy_enabled():
    """检查代理是否启用(从.env读PROXY_ENABLED)
    Returns: bool
    """
    return PROXY_ENABLED


def get_proxy_ip(force_refresh=False):
    """获取代理IP地址

    缓存未过期则复用，过期或force_refresh=True时调API刷新。

    Returns: str - "ip:port" 格式，失败返回None
    """
    global _cached_proxy

    # 缓存未过期则复用
    if not force_refresh and _cached_proxy:
        if time.time() < _cached_proxy["expires_at"]:
            addr = f"{_cached_proxy['ip']}:{_cached_proxy['port']}"
            print(f"  [代理] 复用缓存代理: {addr} (剩余{int(_cached_proxy['expires_at'] - time.time())}秒)")
            return addr

    # 调API刷新
    print("  [代理] 从API获取新代理IP...")
    params = {
        "inst_id": PROXY_INST_ID,
        "akey": PROXY_AKEY,
        "count": "1",
        "dedup": "1",
        "timespan": "2",
        "type": "2",
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{PROXY_API_URL}?{query}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Python/proxy_utils"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            text = resp.read().decode("utf-8").strip()

        if not text:
            print("  [代理] API返回空内容")
            return None

        data = json.loads(text)
        if data.get("data") and data["data"].get("proxy_list"):
            p = data["data"]["proxy_list"][0]
            ip = p["ip"]
            port = p["port"]
            expired_seconds = p.get("expired_seconds", 130)

            # 提前10秒过期，避免边界问题
            _cached_proxy = {
                "ip": ip,
                "port": port,
                "expires_at": time.time() + expired_seconds - 10,
            }
            addr = f"{ip}:{port}"
            print(f"  [代理] 获取新代理: {addr} (有效期{expired_seconds}秒)")
            return addr

        print("  [代理] API返回无可用代理")
        return None

    except Exception as e:
        print(f"  [代理] 获取代理IP失败: {e}")
        return None


def get_proxies_dict(proxy_addr=None):
    """返回requests/urllib可用的代理dict

    Args:
        proxy_addr: "ip:port"格式，None则自动获取
    Returns: {"http": "http://user:pass@ip:port", "https": "http://user:pass@ip:port"} 或 None
    """
    if not is_proxy_enabled():
        return None

    if proxy_addr is None:
        proxy_addr = get_proxy_ip()
    if proxy_addr is None:
        return None

    proxy_url = f"http://{proxy_addr}"
    return {"http": proxy_url, "https": proxy_url}


def get_requests_session_with_proxy(proxy_addr=None):
    """创建带代理+浏览器UA的requests.Session

    流程: 先访问东方财富首页拿cookies，再返回session供后续API请求使用。

    Args:
        proxy_addr: "ip:port"格式，None则自动获取
    Returns: requests.Session 或 None(代理获取失败时)
    """
    import requests

    if not is_proxy_enabled():
        print("  [代理] 未启用代理，返回普通session")
        sess = requests.Session()
        sess.headers.update({
            "User-Agent": BROWSER_UA,
            "Referer": "https://quote.eastmoney.com/",
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
        })
        return sess

    proxy_addr = proxy_addr or get_proxy_ip()
    if proxy_addr is None:
        print("  [代理] 获取代理IP失败，返回普通session")
        sess = requests.Session()
        sess.headers.update({
            "User-Agent": BROWSER_UA,
            "Referer": "https://quote.eastmoney.com/",
        })
        return sess

    proxy_url = f"http://{proxy_addr}"
    proxies = {"http": proxy_url, "https": proxy_url}

    sess = requests.Session()
    sess.headers.update({
        "User-Agent": BROWSER_UA,
        "Referer": "https://quote.eastmoney.com/",
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
    })
    sess.proxies = proxies

    # 访问首页建立session拿cookies
    print("  [代理] 访问东方财富首页拿cookies...")
    try:
        home_resp = sess.get(EASTMONEY_HOME, timeout=15, verify=True)
        print(f"  [代理] 首页状态码: {home_resp.status_code}, cookies: {list(sess.cookies.keys())}")
    except Exception as e:
        print(f"  [代理] 首页访问异常(继续): {e}")

    return sess


def get_urllib_opener_with_proxy(proxy_addr=None):
    """创建带代理的urllib OpenerDirector

    Args:
        proxy_addr: "ip:port"格式，None则自动获取
    Returns: urllib.request.OpenerDirector 或 None(代理未启用/获取失败)
    """
    if not is_proxy_enabled():
        return None

    proxy_addr = proxy_addr or get_proxy_ip()
    if proxy_addr is None:
        return None

    proxy_handler = urllib.request.ProxyHandler({
        "http": f"http://{proxy_addr}",
        "https": f"http://{proxy_addr}",
    })
    opener = urllib.request.build_opener(proxy_handler)
    opener.addheaders = [
        ("User-Agent", BROWSER_UA),
        ("Referer", "https://quote.eastmoney.com/"),
        ("Accept", "*/*"),
    ]
    return opener


def launch_chromium_with_proxy(proxy_addr, port=9222):
    """启动headless Chromium + --proxy-server(CDP备选方式)

    Args:
        proxy_addr: "ip:port"格式代理地址
        port: CDP调试端口(默认9222)
    Returns: subprocess.Popen 进程对象，失败返回None
    """
    import subprocess
    import glob as glob_mod

    # 查找Playwright Chromium
    chrome_bin = None
    search_patterns = [
        os.path.expanduser("~/Library/Caches/ms-playwright/*/chrome-mac/Chromium.app/Contents/MacOS/Chromium"),
        os.path.expanduser("~/Library/Caches/ms-playwright/*/chrome-mac/Chromium"),
    ]
    for pattern in search_patterns:
        for p in glob_mod.glob(pattern):
            chrome_bin = p
            break
        if chrome_bin:
            break

    if not chrome_bin:
        print("  [CDP代理] 未找到Chromium，尝试安装...")
        subprocess.run(["npx", "playwright", "install", "chromium"], timeout=120)
        for pattern in search_patterns:
            for p in glob_mod.glob(pattern):
                chrome_bin = p
                break
            if chrome_bin:
                break

    if not chrome_bin:
        print("  [CDP代理] 无法找到/安装Chromium")
        return None

    print(f"  [CDP代理] Chromium路径: {chrome_bin}")

    # 关闭现有Chromium进程
    subprocess.run(["pkill", "-f", "Chromium"], capture_output=True)
    subprocess.run(["pkill", "-f", "Google Chrome"], capture_output=True)
    time.sleep(1)

    profile_dir = os.path.expanduser("~/.pw-chromium-proxy-profile")
    os.makedirs(profile_dir, exist_ok=True)

    proc = subprocess.Popen([
        chrome_bin,
        "--headless",
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        f"--proxy-server=http://{proxy_addr}",
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # 等待CDP就绪
    print("  [CDP代理] 等待CDP就绪...")
    cdp_ready = False
    for i in range(20):
        time.sleep(1)
        try:
            resp = urllib.request.urlopen(f"http://localhost:{port}/json/version", timeout=3)
            if b"Browser" in resp.read():
                print(f"  [CDP代理] CDP就绪 ({i+1}秒)")
                cdp_ready = True
                break
        except Exception:
            continue

    if not cdp_ready:
        print("  [CDP代理] CDP端口未就绪")
        proc.terminate()
        proc.wait(timeout=5)
        return None

    return proc


def kill_chromium(proc=None):
    """终止Chromium进程

    Args:
        proc: subprocess.Popen对象，None则pkill所有Chromium
    """
    import subprocess
    if proc:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    else:
        subprocess.run(["pkill", "-f", "Chromium"], capture_output=True)
        subprocess.run(["pkill", "-f", "Google Chrome"], capture_output=True)