#!/usr/bin/env python3
"""测试requests获取东方财富API"""
import requests

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://quote.eastmoney.com/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
})

url = "https://push2.eastmoney.com/api/qt/clist/get"
params = {
    "np": 1, "fltt": 2, "invt": 2,
    "fs": "m:0+t:6+f:!2",
    "fields": "f12,f14,f3,f11",
    "fid": "f11",
    "pn": 1, "pz": 5, "po": 1, "dect": 1,
    "ut": "fa5fd1943c7b386f172d6893dbfba10b"
}

try:
    resp = session.get(url, params=params, timeout=15)
    print(f"HTTP状态: {resp.status_code}")
    print(f"响应长度: {len(resp.text)}")
    print(f"内容前500字符:\n{resp.text[:500]}")
except Exception as e:
    print(f"错误: {e}")
