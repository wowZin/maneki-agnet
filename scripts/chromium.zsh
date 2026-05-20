#!/usr/bin/env zsh
set -euo pipefail

# 配置
DEBUG_PORT=9222
PROFILE_DIR="$HOME/.pw-chromium-profile"
mkdir -p "$PROFILE_DIR"

# 读取代理配置（从.env）
PROXY_ENABLED=false
if [[ -f "/Users/zhangying/projects/study/maneki-agent/.env" ]]; then
  PROXY_ENABLED=$(grep '^PROXY_ENABLED=' /Users/zhangying/projects/study/maneki-agent/.env | cut -d'=' -f2 | tr -d ' ')
  PROXY_INST_ID=$(grep '^PROXY_INST_ID=' /Users/zhangying/projects/study/maneki-agent/.env | cut -d'=' -f2 | tr -d ' ')
  PROXY_AKEY=$(grep '^PROXY_AKEY=' /Users/zhangying/projects/study/maneki-agent/.env | cut -d'=' -f2 | tr -d ' ')
fi

# 自动搜索 Playwright Chromium（绝对能找到）
echo "正在查找 Playwright Chromium..."
CHROME_BIN=$(find ~/Library/Caches/ms-playwright -name "Chromium" -type f -perm -u+x | head -n 1)

# 如果没找到，自动安装
if [[ -z "$CHROME_BIN" || ! -x "$CHROME_BIN" ]]; then
  echo "未找到，正在安装 Chromium..."
  npx playwright install chromium
  CHROME_BIN=$(find ~/Library/Caches/ms-playwright -name "Chromium" -type f -perm -u+x | head -n 1)
fi

# 构建启动参数
LAUNCH_ARGS=(
  --headless
  --remote-debugging-port="$DEBUG_PORT"
  --remote-allow-origins="*"
  --user-data-dir="$PROFILE_DIR"
  --no-first-run
  --no-default-browser-check
)

# 代理启用时：获取代理IP并添加 --proxy-server
if [[ "$PROXY_ENABLED" == "true" || "$PROXY_ENABLED" == "1" ]]; then
  echo "代理已启用，获取代理IP..."
  # 获取代理IP（通过python脚本）
  PROXY_ADDR=$(python3 -c "
import sys; sys.path.insert(0, '/Users/zhangying/projects/study/maneki-agent/scripts')
from proxy_utils import get_proxy_ip
addr = get_proxy_ip()
print(addr if addr else '')
" 2>/dev/null)
  if [[ -n "$PROXY_ADDR" ]]; then
    echo "代理地址: $PROXY_ADDR"
    LAUNCH_ARGS+=(--proxy-server="http://$PROXY_ADDR")
  else
    echo "警告: 获取代理IP失败，将不带代理启动"
  fi
fi

echo "启动 Chromium"
echo "CDP URL: http://localhost:$DEBUG_PORT/json/version"
echo "----------------------------------------"

# 启动！(无头模式适合cron后台运行)
exec "$CHROME_BIN" $LAUNCH_ARGS