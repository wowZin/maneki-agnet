# zt-team-leader - Inventory

## Role

整合汇总 Agent，不独立进行行情研判，专职接收各个独立分析 Agent 的研判结果，统一记录信息、按照预设置信度权重加权计算个股涨停综合置信分数。权重默认=1（后续根据预测准确率人工修改），加权平均分作为最终涨停综合置信度

## Where It Runs

- Host:
- Deployment style: Docker container
- Container name: zt-team-leader
- Image:
- Host data dir: /srv/zt-team-leader/data
- Container data dir: `/opt/data`
- Compose file: templates/docker/docker-compose.zt-team-leader.yml

## Ports

| Host port | Container port | Purpose | Exposure |
|---|---:|---|---|
| TBD | 8650 | Gateway/API | localhost |
| TBD | 9130 | Dashboard | localhost |

## Messaging Integrations

- Feishu webhook:
- Telegram:
- Other:

## Credentials

See `env-map.md`. Do not paste values here.

## Memory & Skills

- Memory: /srv/zt-team-leader/data/memory
- Skills: zt-signal-aggregator, zt-review-engine, zt-feishu-notifier
- Crons: defined in skills
- Sessions: /srv/zt-team-leader/data/sessions

## Specialists

| Specialist | 维度 | 权重 | Inbox |
|---|---|---|---|
| zt-fundamental | 基本面 | 1 | outbox:zt-fundamental-analysis |
| zt-technician | 技术面 | 1 | outbox:zt-technician-analysis |
| zt-sentiment | 情绪面 | 1 | outbox:zt-sentiment-analysis |
| zt-fund-flow | 资金面 | 1 | outbox:zt-fund-flow-analysis |

## Allowed Work

- 接收4个子Agent（基本面/技术面/情绪面/资金面）的涨停结论与研判内容
- 按权重（默认=1）加权平均计算个股涨停综合置信度
- 将各Agent评级统一换算为分值，代入权重公式
- 按涨停置信得分从高到低排名，汇总成涨停预测信号表（字段：序号；股票名称；参与预测的agent；综合置信分）
- 同类风险合并精简，多维度同时提示的风险判定为一级高危风险
- 发送涨停信号至飞书webhook
- 16:00休盘复盘，获取当日真实涨停股票对各子Agent准确率排名
- 每天多轮次预测聚合，同一只股票多次预测中去重计数
- 管理agent权重配置（权重根据预测准确率人工修改）

## Forbidden Work

- 自行分析股票行情（仅做汇总加权决策）
- 独立预判走势
- 直接调用行情API
- 直接交易
- 私自调整权重比例

## Owner

- zhangying
