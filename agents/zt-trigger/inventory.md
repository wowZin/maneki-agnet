# zt-trigger - Inventory

## Role

定时触发器，工作日9:00-15:00每10分钟拉取涨速排名前100股票，下发给zt-team-leader

## Where It Runs

- Host:
- Deployment style: Docker container
- Container name: zt-trigger
- Image:
- Host data dir: /srv/zt-trigger/data
- Container data dir: `/opt/data`
- Compose file: templates/docker/docker-compose.zt-trigger.yml

## Ports

| Host port | Container port | Purpose | Exposure |
|---|---:|---|---|
| TBD | 8642 | Gateway/API | localhost |
| TBD | 9119 | Dashboard | localhost |

## Messaging Integrations

- Feishu webhook:
- Telegram:
- Other:

## Credentials

See `env-map.md`. Do not paste values here.

## Memory & Skills

- Memory: /srv/zt-trigger/data/memory
- Skills: zt-surge-fetcher
- Crons: defined in skills
- Sessions: /srv/zt-trigger/data/sessions

## Allowed Work

- 调用涨速排名API
- 构建任务列表
- 下发给team-leader

## Forbidden Work

- 自行分析股票
- 直接联系子agent
- 发送飞书通知

## Owner

- zhangying
