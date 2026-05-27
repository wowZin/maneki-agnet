#!/usr/bin/env python3
"""Test proxy and direct connectivity"""
import requests

# Test tunnel proxy directly
proxy_url = 'http://202605271050581357:5n74lrx3@a216.zdtps.com:21166'
try:
    r = requests.get('https://push2.eastmoney.com/api/qt/clist/get', params={
        'np': '1', 'fltt': '2', 'invt': '2',
        'fs': 'm:0+t:6+f:!2,m:0+t:80+f:!2,m:1+t:2+f:!2,m:1+t:23+f:!2,m:0+t:81+s:262144+f:!2',
        'fields': 'f12,f14,f2,f3,f11',
        'pn': '1', 'pz': '200', 'po': '1', 'dect': '1',
        'ut': 'fa5fd1943c7b386f172d6893dbfba10b', 'fid': 'f3'
    }, timeout=15, proxies={'http': proxy_url, 'https': proxy_url},
       headers={'User-Agent': 'Mozilla/5.0'})
    print(f'PROXY_OK|{r.status_code}|{len(r.text)}')
except Exception as e:
    print(f'PROXY_FAIL|{type(e).__name__}|{e}')

# Direct
try:
    r = requests.get('https://push2.eastmoney.com/api/qt/clist/get', params={
        'np': '1', 'fltt': '2', 'invt': '2',
        'fs': 'm:0+t:6+f:!2,m:0+t:80+f:!2,m:1+t:2+f:!2,m:1+t:23+f:!2,m:0+t:81+s:262144+f:!2',
        'fields': 'f12,f14,f2,f3,f11',
        'pn': '1', 'pz': '200', 'po': '1', 'dect': '1',
        'ut': 'fa5fd1943c7b386f172d6893dbfba10b', 'fid': 'f3'
    }, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
    print(f'DIRECT_OK|{r.status_code}|{len(r.text)}')
except Exception as e:
    print(f'DIRECT_FAIL|{type(e).__name__}|{e}')
