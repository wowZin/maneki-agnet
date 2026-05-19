#!/usr/bin/env python3
"""测试CDP直接导航到API URL获取数据"""
import json, urllib.request, websocket, time

# 获取CDP target
targets = json.loads(urllib.request.urlopen('http://localhost:9222/json/list', timeout=5).read())
page = None
for t in targets:
    if t.get('type') == 'page':
        page = t
        break

ws_url = page['webSocketDebuggerUrl']
ws = websocket.create_connection(ws_url, timeout=30)

# 直接导航到API URL，读取响应内容
api_url = "https://push2.eastmoney.com/api/qt/clist/get?np=1&fltt=2&invt=2&fs=m:0+t:6+f:!2&fields=f12,f14,f3,f11&fid=f11&pn=1&pz=5&po=1&dect=1&ut=fa5fd1943c7b386f172d6893dbfba10b"

print(f"导航到: {api_url[:80]}...")

# 导航到API URL
ws.send(json.dumps({
    "id": 1,
    "method": "Page.navigate",
    "params": {"url": api_url}
}))
time.sleep(3)

# 获取页面内容
ws.send(json.dumps({
    "id": 2,
    "method": "Runtime.evaluate",
    "params": {"expression": "document.body.innerText", "returnByValue": True}
}))

result = None
while True:
    msg = ws.recv()
    data = json.loads(msg)
    if data.get('id') == 2:
        result = data
        break

ws.close()
value = result.get('result', {}).get('result', {}).get('value', '')
print("=== 页面内容 ===")
print(value[:1000])
