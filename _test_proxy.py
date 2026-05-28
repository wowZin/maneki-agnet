#!/usr/bin/env python3
"""Quick proxy test"""
import sys
sys.path.insert(0, '.')
from scripts.proxy_utils import get_proxy_ip, get_requests_session_with_proxy
proxy_addr = get_proxy_ip(force_refresh=True)
print(f'New proxy: {proxy_addr}')
if proxy_addr:
    import requests
    session = requests.Session()
    session.proxies = {'http': 'http://' + proxy_addr, 'https': 'http://' + proxy_addr}
    session.headers.update({'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36', 'Referer': 'https://quote.eastmoney.com/'})
    try:
        resp = session.get('https://push2.eastmoney.com/api/qt/clist/get?np=1&fltt=2&invt=2&fs=m:0+t:6+f:!2,m:0+t:80+f:!2,m:1+t:2+f:!2,m:1+t:23+f:!2,m:0+t:81+s:262144+f:!2&fields=f12,f14,f2,f3,f11&pn=1&pz=200&po=1&dect=1&ut=fa5fd1943c7b386f172d6893dbfba10b&fid=f11', timeout=15)
        print(f'Status: {resp.status_code}, Content length: {len(resp.text)}, First 300: {resp.text[:300]}')
    except Exception as e:
        print(f'Request failed: {e}')
else:
    print('No proxy obtained')
