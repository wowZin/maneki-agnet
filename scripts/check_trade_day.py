#!/usr/bin/env python3
"""检查今天是否为交易日"""
import tushare as ts
import os
import datetime
from dotenv import load_dotenv

load_dotenv('/Users/zhangying/projects/study/maneki-agent/.env')

ts.set_token(os.getenv('TUSHARE_TOKEN'))
pro = ts.pro_api()

today = datetime.date.today().strftime('%Y%m%d')
print(f"检查日期: {today}")

df = pro.trade_cal(exchange='SSE', start_date=today, end_date=today)
print(df)

if not df.empty:
    is_open = df.iloc[0]['is_open']
    print(f"is_open: {is_open}")
    if is_open == 1:
        print("今天是交易日")
    else:
        print("今天不是交易日")
else:
    print("无交易日历数据，假设非交易日")
