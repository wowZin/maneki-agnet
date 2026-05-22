#!/usr/bin/env python3
"""Test requests+proxy directly (no cookie step)"""
import urllib.request
import json
from pathlib import Path
import os, sys
sys.path.insert(0, str(Path(__file__).parent))
import proxy_utils

# Get a fresh proxy
proxy_addr = proxy_utils.get_proxy_ip(force_refresh=True)
print(f"Proxy: {proxy_addr}")

if not proxy_addr:
    print("Failed to get proxy")
    exit(1)

proxy_url = f"http://{proxy_addr}"

# Method 1: urllib opener (worked before)
import urllib.request
proxy_handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
opener = urllib.request.build_opener(proxy_handler)
opener.addheaders = [
    ("User-Agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"),
    ("Referer", "https://quote.eastmoney.com/"),
]
api_url = ("https://push2.eastmoney.com/api/qt/clist/get?"
           "np=1&fltt=2&invt=2&"
           "fs=m:0+t:6+f:!2,m:0+t:80+f:!2,m:1+t:2+f:!2,m:1+t:23+f:!2,m:0+t:81+s:262144+f:!2&"
           "fields=f12,f13,f14,f2,f4,f3,f5,f6,f7,f15,f18,f16,f17,f10,f8,f9,f11&"
           "fid=f11&pn=1&pz=10&po=1&dect=1&"
           "ut=fa5fd1943c7b386f172d6893dbfba10b&cb=")
try:
    resp = opener.open(api_url, timeout=15)
    data = json.loads(resp.read().decode('utf-8'))
    diff = data.get('data', {}).get('diff', [])
    print(f"\nurllib OK: {len(diff)} stocks")
    for s in diff[:5]:
        print(f"  {s.get('f12')} {s.get('f14')} surge={s.get('f11')}% pct={s.get('f3')}%")
except Exception as e:
    print(f"\nurllib FAIL: {type(e).__name__}: {str(e)[:200]}")

# Method 2: requests session with proxy but NO cookie step
import requests
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
})
session.proxies = {"http": proxy_url, "https": proxy_url}
try:
    resp = session.get(api_url, timeout=15, verify=False)
    data = resp.json()
    diff = data.get('data', {}).get('diff', [])
    print(f"\nrequests (no cookies) OK: {len(diff)} stocks")
    for s in diff[:5]:
        print(f"  {s.get('f12')} {s.get('f14')} surge={s.get('f11')}% pct={s.get('f3')}%")
except Exception as e:
    print(f"\nrequests FAIL: {type(e).__name__}: {str(e)[:200]}")

# Method 3: requests session with cookie step (exactly what cdp_fetch does)
session2 = proxy_utils.get_requests_session_with_proxy(proxy_addr)
try:
    resp = session2.get(api_url, timeout=15, verify=False)
    data = resp.json()
    diff = data.get('data', {}).get('diff', [])
    print(f"\nrequests (with cookies) OK: {len(diff)} stocks")
    for s in diff[:5]:
        print(f"  {s.get('f12')} {s.get('f14')} surge={s.get('f11')}% pct={s.get('f3')}%")
except Exception as e:
    print(f"\nrequests (with cookies) FAIL: {type(e).__name__}: {str(e)[:200]}")
