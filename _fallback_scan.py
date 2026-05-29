#!/usr/bin/env python3
"""HTTP fallback scanner for Eastmoney push2 when HTTPS+proxy fails."""
import requests, json, re, time, os

headers = {'User-Agent': 'Mozilla/5.0'}
url = ('http://push2.eastmoney.com/api/qt/clist/get?np=1&fltt=2&invt=2'
       '&fs=m:0+t:6+f:!2,m:0+t:80+f:!2,m:1+t:2+f:!2,m:1+t:23+f:!2,m:0+t:81+s:262144+f:!2'
       '&fields=f12,f14,f2,f3,f11&pn=1&pz=200&po=1&dect=1'
       '&ut=fa5fd1943c7b386f172d6893dbfba10b&fid=f3')

candidates = []
for attempt in range(5):
    try:
        resp = requests.get(url, timeout=15, headers=headers)
        data = resp.json()
        items = data.get('data', {}).get('diff', [])
        for s in items:
            code, name = s.get('f12',''), s.get('f14','')
            if re.search(r'ST|\*ST|退|N', name or ''): continue
            if re.match(r'^(300|301|688|8|4|920)', str(code)): continue
            pct = float(s.get('f3',0) or 0)
            if pct < 2 or pct > 9.5: continue
            if '.' not in str(code):
                code = f'{code}.SH' if str(code).startswith('6') else f'{code}.SZ'
            candidates.append({'code': code, 'name': name, 'pct_chg': pct})
        if candidates:
            print(f'OK: {len(candidates)} candidates (attempt {attempt+1})')
            break
        else:
            print(f'Empty response, retry {attempt+1}')
            time.sleep(2**attempt)
    except Exception as e:
        print(f'Retry {attempt+1}: {str(e)[:80]}')
        time.sleep(2**attempt)

if candidates:
    ts = time.strftime('%Y%m%d_%H%M')
    outpath = f'data/signals/surge_{ts}.json'
    os.makedirs('data/signals', exist_ok=True)
    with open(outpath, 'w') as f:
        json.dump(candidates, f, ensure_ascii=False, indent=2)
    print(f'Saved {len(candidates)} candidates to {outpath}')
    print(json.dumps(candidates[:3], ensure_ascii=False, indent=2))
else:
    print('No candidates after 5 retries')
