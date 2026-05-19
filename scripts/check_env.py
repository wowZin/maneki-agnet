#!/usr/bin/env python3
import sys
print(sys.executable)
print(sys.version)

modules = ['tushare', 'akshare', 'websocket', 'dotenv', 'requests', 'pandas']
for m in modules:
    try:
        __import__(m)
        print(f"  {m}: OK")
    except ImportError:
        print(f"  {m}: MISSING")
