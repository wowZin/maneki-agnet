import tushare as ts
import os
from dotenv import load_dotenv

load_dotenv('/Users/zhangying/projects/study/maneki-agent/.env')
TOKEN = os.getenv('TUSHARE_TOKEN')
ts.set_token(TOKEN)
pro = ts.pro_api()

df = pro.stk_factor_pro(ts_code='002971.SZ', start_date='20250501', end_date='20260518')
print("字段列表:", df.columns.tolist() if df is not None else "None")
print("\n数据行数:", len(df) if df is not None else 0)
if df is not None and len(df) > 0:
    df = df.sort_values('trade_date', ascending=False)
    row = df.iloc[0]
    print("\n最新一行所有字段:")
    for col in df.columns:
        val = row[col]
        print(f"  {col}: {val}")
