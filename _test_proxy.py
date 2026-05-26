#!/usr/bin/env python3
"""Test proxy connectivity"""
import sys
sys.path.insert(0, '.')
from scripts.proxy_utils import get_proxy_ip, is_proxy_enabled, get_requests_session_with_proxy

print(f'代理启用: {is_proxy_enabled()}')

# 强制刷新获取新代理
addr = get_proxy_ip(force_refresh=True)
print(f'新代理: {addr}')

if addr:
    session = get_requests_session_with_proxy(addr)
    if session:
        try:
            resp = session.get(
                'https://push2.eastmoney.com/api/qt/clist/get?np=1&fltt=2&invt=2'
                '&fs=m:0+t:6+f:!2,m:0+t:80+f:!2,m:1+t:2+f:!2,m:1+t:23+f:!2,'
                'm:0+t:81+s:262144+f:!2&fields=f12,f14,f2,f3,f11&pn=1&pz=5&po=1'
                '&dect=1&ut=fa5fd1943c7b386f172d6893dbfba10b&fid=f3',
                timeout=15
            )
            print(f'状态码: {resp.status_code}')
            print(f'响应前200字符: {resp.text[:200]}')
        except Exception as e:
            print(f'请求失败: {e}')
    else:
        print('session创建失败')
