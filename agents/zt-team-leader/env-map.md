# zt-team-leader - Env Map

| Key | Example | Purpose | Location |
|---|---|---|---|
| TUSHARE_TOKEN | Tushare API Token | 盘后验证数据源 | .env |
| FEISHU_WEBHOOK_URL | https://open.feishu.cn/... | 涨停信号推送 | .env |
| FEISHU_REVIEW_WEBHOOK_URL | https://open.feishu.cn/... | 复盘报告推送 | .env |
| FEISHU_SIGN_SECRET | (可选) | 飞书签名密钥 | .env |
| TZ | Asia/Shanghai | 时区 | .env |

## Rules

- Never commit .env files
- TUSHARE_TOKEN 统一使用项目根目录 .env 中的值
- Rotate API keys on schedule
- Use minimal-scope tokens where possible
