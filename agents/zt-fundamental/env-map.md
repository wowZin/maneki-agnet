# zt-fundamental - Env Map

| Variable | Source | Description |
|---|---|---|
| TUSHARE_TOKEN | .env | Tushare Pro API token |

## Rules

- Never commit .env files
- TUSHARE_TOKEN 统一使用项目根目录 .env 中的值
- Rotate API keys on schedule
- Use minimal-scope tokens where possible