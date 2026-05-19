#!/usr/bin/env python3
"""Install required packages into the hermes venv"""
import subprocess
import sys

packages = ['tushare', 'akshare', 'websocket-client', 'python-dotenv', 'pandas', 'requests']
result = subprocess.run([sys.executable, '-m', 'pip', 'install'] + packages, capture_output=True, text=True)
print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr)
print("Return code:", result.returncode)
