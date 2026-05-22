#!/usr/bin/env python3
"""Test data source connectivity"""
import json
import urllib.request
import ssl

print("=== Test: Direct push2.eastmoney.com (no proxy) ===")
url = "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=3&po=1&np=1&fltt=2&invt=2&fid=f11&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23&fields=f12,f14,f3,f2,f11&ut=fa5fd1943c7b386f172d6893dbfba10b"
req = urllib.request.Request(url, headers={
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://quote.eastmoney.com/'
})
try:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    resp = urllib.request.urlopen(req, timeout=15, context=ctx)
    data = json.loads(resp.read().decode('utf-8'))
    diff = data.get('data', {}).get('diff', [])
    print(f"  Direct OK: {len(diff)} stocks")
    for s in diff[:3]:
        print(f"    {s.get('f12')} {s.get('f14')} surge={s.get('f11')}% pct={s.get('f3')}%")
except Exception as e:
    print(f"  Direct FAIL: {type(e).__name__}: {e}")

print("\n=== Test: akshare stock_zh_a_spot_em ===")
try:
    import akshare as ak
    df = ak.stock_zh_a_spot_em()
    print(f"  akshare OK: {len(df)} rows")
    print(df[['代码','名称','涨跌幅','涨速']].head(5).to_string())
except Exception as e:
    print(f"  akshare FAIL: {type(e).__name__}: {e}")

print("\n=== Test: Tushare trade_cal ===")
try:
    import requests
    payload = {
        "api_name": "trade_cal",
        "token": open('/root/maneki-agent/.env').read().split('TUSHARE_TOKEN=')[1].split('\n')[0].strip().strip('"').strip("'"),
        "params": {"exchange": "SSE", "start_date": "20260521", "end_date": "20260521"}
    }
    resp = requests.post("https://api.tushare.pro", json=payload, timeout=10)
    print(f"  Tushare OK: {resp.json()}")
except Exception as e:
    print(f"  Tushare FAIL: {type(e).__name__}: {e}")
