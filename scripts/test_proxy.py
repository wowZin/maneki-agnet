#!/usr/bin/env python3
"""Test proxy connectivity to East Money"""
import json
import urllib.request
import time

# Test getting a fresh proxy
print("=== Step 1: Get fresh proxy ===")
params = {
    "inst_id": "202605202000581968",
    "akey": "55c5dfc083b81206",
    "count": "1",
    "dedup": "1",
    "timespan": "2",
    "type": "2",
}
query = "&".join(f"{k}={v}" for k, v in params.items())
url = f"http://s189.zdtps.com:8080/GetIP/?{query}"
proxy_addr = None
try:
    req = urllib.request.Request(url, headers={"User-Agent": "Python/proxy_utils"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        text = resp.read().decode("utf-8").strip()
        print(f"  Raw response: {text[:200]}")
        data = json.loads(text)
        if data.get("data") and data["data"].get("proxy_list"):
            p = data["data"]["proxy_list"][0]
            proxy_addr = f"{p['ip']}:{p['port']}"
            print(f"  Got proxy: {proxy_addr}")
        else:
            print(f"  No proxy in response")
except Exception as e:
    print(f"  FAIL: {e}")

# Test the proxy
if proxy_addr:
    print(f"\n=== Step 2: Test proxy {proxy_addr} to eastmoney ===")
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
    
    # Test www.eastmoney.com first
    print("  Test 1: www.eastmoney.com...")
    try:
        resp = opener.open("https://www.eastmoney.com/", timeout=15)
        print(f"    OK: status={resp.status}, length={len(resp.read())}")
    except Exception as e:
        print(f"    FAIL: {type(e).__name__}: {e}")
    
    # Test push2 API
    print("  Test 2: push2.eastmoney.com API...")
    api_url = "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=3&po=1&np=1&fltt=2&invt=2&fid=f11&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23&fields=f12,f14,f3,f2,f11"
    try:
        resp = opener.open(api_url, timeout=15)
        data = json.loads(resp.read().decode('utf-8'))
        diff = data.get('data', {}).get('diff', [])
        print(f"    OK: {len(diff)} stocks")
        for s in diff[:3]:
            print(f"      {s.get('f12')} {s.get('f14')} surge={s.get('f11')}%")
    except Exception as e:
        print(f"    FAIL: {type(e).__name__}: {e}")
