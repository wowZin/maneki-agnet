# zt-trigger - Env Map

| Key | Example | Purpose | Location |
|---|---|---|---|
| TUSHARE_TOKEN | Tushare API Token | 数据源鉴权 | .env |
| TZ | Asia/Shanghai | 时区 | .env |

## Rules

- Never commit .env files
- TUSHARE_TOKEN 统一使用项目根目录 .env 中的值
- Rotate API keys on schedule
- Use minimal-scope tokens where possible
