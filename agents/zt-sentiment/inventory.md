# zt-sentiment - Inventory

## Role

专注股票市场情绪涨停潜力预判的智能分析Agent，基于全市场情绪、板块情绪、个股人气、资金偏好、市场风口数据，筛选处于市场高情绪风口、人气活跃、资金抱团意愿强的情绪涨停标的

## Where It Runs

- Host:
- Deployment style: Docker container
- Container name: zt-sentiment
- Image:
- Host data dir: /srv/zt-sentiment/data
- Container data dir: `/opt/data`
- Compose file: templates/docker/docker-compose.zt-sentiment.yml

## Ports

| Host port | Container port | Purpose | Exposure |
|---|---:|---|---|
| TBD | 8646 | Gateway/API | localhost |
| TBD | 9123 | Dashboard | localhost |

## Messaging Integrations

- Feishu webhook:
- Telegram:
- Other:

## Credentials

See `env-map.md`. Do not paste values here.

## Memory & Skills

- Memory: /srv/zt-sentiment/data/memory
- Skills: zt-sentiment-analysis
- Crons: defined in skills
- Sessions: /srv/zt-sentiment/data/sessions

## Allowed Work

### 五维度量化评分体系 V1.0（总分100分）

**维度1：大盘整体情绪（30分）**
- 涨停家数：≥35家+10分，≥20家+5分，<10家-10分
- 跌停控制：<5家+8分，>10家-8分
- 连板高度：≥4板+7分，≥3板+5分
- 数据源：Tushare limit_list_d, limit_step

**维度2：主线题材情绪（30分）**
- 概念数量：≥8个+8分，≥4个+5分
- 热门题材：匹配热门关键词+5~10分
- 题材涨停：概念板块涨停≥3只+7分
- 数据源：Tushare concept_detail, limit_list_d

**维度3：板块梯队情绪（20分）**
- 板块涨停：≥5只+10分，≥3只+6分
- 梯队完整：≥2只高板股+4分
- 数据源：Tushare limit_list_d, limit_step

**维度4：个股人气资金情绪（15分）**
- 换手率：10%~25%+5分，>25%-3分
- 龙虎榜：净买入>0+3分
- 涨停记忆：近期涨停≥2次+4分
- 数据源：Tushare daily_basic, top_list, limit_list_d

**维度5：舆情与资金风向（5分）**
- 题材丰富度：≥5个概念+3分
- 数据源：Tushare concept_detail

### 一票否决规则

触发任意一条，直接判定【涨停预测：否】：
1. 市场退潮：涨停<20家
2. 高位杀跌：最高连板高度<3
3. 个股情绪溃散：近5日核按钮（需历史数据验证）

### 评级标准

- ≥70分：[高] 高强度涨停/隔日起爆/连板潜力
- 50-69分：[中] 中等潜力
- 30-49分：[低] 低潜力
- <30分或否决：[无] 无潜力

### 输出格式

`score, "[等级] 原因1; 原因2; ..."`

## Forbidden Work

- 技术面分析（K线形态、均线、筹码、盘口）
- 基本面分析（财报、估值、行业分析）
- 发送飞书通知
- 直接交易
- 忽略情绪退潮信号：大盘转弱、题材退潮、板块溃散、人气骤降、舆情反转必须降级

## Owner

- zhangying
