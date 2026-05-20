#!/usr/bin/env zsh
set -euo pipefail

# 配置
DEBUG_PORT=9222
PROFILE_DIR="$HOME/.pw-chromium-profile"
mkdir -p "$PROFILE_DIR"

# 自动搜索 Playwright Chromium（绝对能找到）
echo "🔍 正在查找 Playwright Chromium..."
CHROME_BIN=$(find ~/Library/Caches/ms-playwright -name "Chromium" -type f -perm -u+x | head -n 1)

# 如果没找到，自动安装
if [[ -z "$CHROME_BIN" || ! -x "$CHROME_BIN" ]]; then
  echo "🔧 未找到，正在安装 Chromium..."
  npx playwright install chromium
  CHROME_BIN=$(find ~/Library/Caches/ms-playwright -name "Chromium" -type f -perm -u+x | head -n 1)
fi

echo "🚀 启动独立 Chromium"
echo "✅ CDP URL: http://localhost:$DEBUG_PORT/json/version"
echo "----------------------------------------"

# 启动！(无头模式适合cron后台运行)
exec "$CHROME_BIN" \
  --remote-debugging-port="$DEBUG_PORT" \
  --remote-allow-origins="*" \
  --user-data-dir="$PROFILE_DIR" \
  --no-first-run \
  --no-default-browser-check