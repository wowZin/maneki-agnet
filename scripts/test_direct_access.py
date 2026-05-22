#!/usr/bin/env python3
"""Test direct access to East Money API and akshare"""
import json
import urllib.request

print("=== Test 1: Direct access to push2.eastmoney.com ===")
url = "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=5&po=1&np=1&fltt=2&invt=2&fid=f11&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23&fields=f12,f14,f3,f2,f11&ut=fa5fd1943c7b386f172d6893dbfba10b"
req = urllib.request.Request(url, headers={
    'User-Agent': 'Mozilla/5.0',
    'Referer': 'https://quote.eastmoney.com/'
})
try:
    resp = urllib.request.urlopen(req, timeout=15)
    data = json.loads(resp.read().decode('utf-8'))
    diff = data.get("data", {}).get("diff", [])
    print(f"  OK: {len(diff)} stocks")
    for s in diff[:3]:
        print(f"    {s.get('f12')} {s.get('f14')} surge={s.get('f11')}% pct={s.get('f3')}%")
except Exception as e:
    print(f"  FAIL: {e}")

print("\n=== Test 2: akshare stock_zh_a_spot_em ===")
try:
    import akshare as ak
    df = ak.stock_zh_a_spot_em()
    print(f"  OK: {len(df)} rows, columns: {list(df.columns[:10])}")
    print(df[['代码','名称','涨跌幅','涨速']].head(5).to_string())
except Exception as e:
    print(f"  FAIL: {e}")
