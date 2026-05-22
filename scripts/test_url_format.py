#!/usr/bin/env python3
"""Test if the working proxy URL format differs from the cdp_fetch API URL"""
import json
import urllib.request
import time

# Get proxy
params = {
    "inst_id": "202605202000581968",
    "akey": "55c5dfc083b81206",
    "count": "1",
    "dedup": "1",
    "timespan": "2",
    "type": "2",
}
query = "&".join(f"{k}={v}" for k, v in params.items())
proxy_url_resp = f"http://s189.zdtps.com:8080/GetIP/?{query}"
proxy_addr = None
req = urllib.request.Request(proxy_url_resp, headers={"User-Agent": "Python/proxy_utils"})
with urllib.request.urlopen(req, timeout=10) as resp:
    data = json.loads(resp.read().decode("utf-8").strip())
    p = data["data"]["proxy_list"][0]
    proxy_addr = f"{p['ip']}:{p['port']}"
    print(f"Got proxy: {proxy_addr} (expired in {p.get('expired_seconds', '?')}s)")

proxy_url = f"http://{proxy_addr}"
proxy_handler = urllib.request.ProxyHandler({
    "http": proxy_url,
    "https": proxy_url,
})
opener = urllib.request.build_opener(proxy_handler)
opener.addheaders = [
    ("User-Agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"),
    ("Referer", "https://quote.eastmoney.com/"),
]

# Test 1: Simple URL format (worked in prior test)
url_simple = "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=3&po=1&np=1&fltt=2&invt=2&fid=f11&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23&fields=f12,f14,f3,f2,f11"
print(f"\nTest 1: Simple URL format")
try:
    resp = opener.open(url_simple, timeout=15)
    data = json.loads(resp.read().decode('utf-8'))
    diff = data.get('data', {}).get('diff', [])
    print(f"  OK: {len(diff)} stocks")
except Exception as e:
    print(f"  FAIL: {type(e).__name__}: {str(e)[:100]}")

# Test 2: Complex URL (same as cdp_fetch API_URL but smaller pz)
url_complex = "https://push2.eastmoney.com/api/qt/clist/get?np=1&fltt=2&invt=2&fs=m:0+t:6+f:!2,m:0+t:80+f:!2,m:1+t:2+f:!2,m:1+t:23+f:!2,m:0+t:81+s:262144+f:!2&fields=f12,f13,f14,f2,f4,f3,f5,f6,f7,f15,f18,f16,f17,f10,f8,f9,f11&fid=f11&pn=1&pz=5&po=1&dect=1&ut=fa5fd1943c7b386f172d6893dbfba10b&cb="
print(f"\nTest 2: Complex URL format (same as cdp_fetch)")
try:
    resp = opener.open(url_complex, timeout=15)
    data = json.loads(resp.read().decode('utf-8'))
    diff = data.get('data', {}).get('diff', [])
    print(f"  OK: {len(diff)} stocks")
except Exception as e:
    print(f"  FAIL: {type(e).__name__}: {str(e)[:100]}")
