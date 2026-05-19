#!/bin/bash
# 启动Chrome CDP用于涨速扫描
# 用法: ./start-chrome-cdp.sh

# 杀掉现有Chrome进程
pkill -f "Google Chrome" 2>/dev/null
sleep 2

# 创建临时profile目录
mkdir -p /tmp/chrome-cdp-profile

# 启动Chrome with CDP
open -a 'Google Chrome' --args \
  --remote-debugging-port=9222 \
  --remote-allow-origins=* \
  --user-data-dir=/tmp/chrome-cdp-profile

echo "Chrome CDP started on port 9222"
echo "Profile: /tmp/chrome-cdp-profile"

# 等待CDP就绪
for i in {1..10}; do
  if curl -s http://localhost:9222/json/list > /dev/null 2>&1; then
    echo "CDP is ready"
    exit 0
  fi
  sleep 1
done

echo "Warning: CDP may not be ready yet"
exit 0
