#!/bin/bash
# 启动Chrome CDP用于涨速扫描（集成代理支持）
# 用法: ./start-chrome-cdp.sh

# 读取代理配置（从.env）
PROXY_ENABLED=false
if [[ -f "/Users/zhangying/projects/study/maneki-agent/.env" ]]; then
  PROXY_ENABLED=$(grep '^PROXY_ENABLED=' /Users/zhangying/projects/study/maneki-agent/.env | cut -d'=' -f2 | tr -d ' ')
fi

# 杀掉现有Chrome进程
pkill -f "Google Chrome" 2>/dev/null
sleep 2

# 创建临时profile目录
mkdir -p /tmp/chrome-cdp-profile

# 构建启动参数
CHROME_ARGS="--remote-debugging-port=9222 --remote-allow-origins=* --user-data-dir=/tmp/chrome-cdp-profile"

# 代理启用时：获取代理IP
if [[ "$PROXY_ENABLED" == "true" || "$PROXY_ENABLED" == "1" ]]; then
  echo "代理已启用，获取代理IP..."
  PROXY_ADDR=$(python3 -c "
import sys; sys.path.insert(0, '/Users/zhangying/projects/study/maneki-agent/scripts')
from proxy_utils import get_proxy_ip
addr = get_proxy_ip()
print(addr if addr else '')
" 2>/dev/null)
  if [[ -n "$PROXY_ADDR" ]]; then
    echo "代理地址: $PROXY_ADDR"
    CHROME_ARGS="$CHROME_ARGS --proxy-server=http://$PROXY_ADDR"
  else
    echo "警告: 获取代理IP失败，将不带代理启动"
  fi
fi

# 启动Chrome with CDP
open -a 'Google Chrome' --args $CHROME_ARGS

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
