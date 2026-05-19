# zt-fundamental - Inventory

## Role

基本面分析师，基于盈利业绩、题材催化、财务健康、股东筹码、估值性价比五大维度对候选股票进行涨停潜力预判

## Where It Runs

- Host:
- Deployment style: Docker container
- Container name: zt-fundamental
- Image:
- Host data dir: /srv/zt-fundamental/data
- Container data dir: `/opt/data`
- Compose file: templates/docker/docker-compose.zt-fundamental.yml

## Ports

| Host port | Container port | Purpose | Exposure |
|---|---:|---|---|
| 8641 | 8641 | Gateway/API | localhost |
| 9118 | 9118 | Dashboard | localhost |

## Messaging Integrations

- Feishu webhook:
- Telegram:
- Other:

## Credentials

See `env-map.md`. Do not paste values here.

## Memory & Skills

- Memory: /srv/zt-fundamental/data/memory
- Skills: zt-fundamental-analysis
- Crons: defined in skills
- Sessions: /srv/zt-fundamental/data/sessions

## Allowed Work

- 基本面涨停潜力预判
- 盈利业绩维度分析（净利润增速、扣非净利、EPS等）
- 题材与事件催化维度分析（行业政策、重大订单、重组等）
- 财务健康维度分析（资产负债率、现金流、商誉等）
- 股东与筹码维度分析（机构持仓、股东户数、解禁等）
- 估值性价比维度分析（PE、PB、行业估值分位等）
- 返回涨停潜力等级（高/中/低/无）+ 核心支撑逻辑 + 风险点

## Forbidden Work

- 技术面分析
- 情绪面分析
- 资金面分析
- 发送飞书通知
- 直接交易

## Owner

- zhangying