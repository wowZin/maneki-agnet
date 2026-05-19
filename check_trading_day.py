#!/usr/bin/env python3
import tushare as ts
import os
import datetime
from dotenv import load_dotenv

load_dotenv()
ts.set_token(os.getenv('TUSHARE_TOKEN'))
pro = ts.pro_api()
today = datetime.date.today().strftime('%Y%m%d')
df = pro.trade_cal(exchange='SSE', start_date=today, end_date=today)
print(df)
if not df.empty and df.iloc[0]['is_open'] == 1:
    print(f'TRADING_DAY: {today}')
else:
    print('NOT_TRADING_DAY')
