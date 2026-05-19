# zt-technician - Inventory

## Role

专注股票技术面涨停潜力预判的智能分析Agent，基于K线、量价、趋势、盘口、均线、筹码结构数据，筛选资金进攻明确、趋势强势、筹码稳定、处于起爆临界点的技术面涨停标的

## Where It Runs

- Host:
- Deployment style: Docker container
- Container name: zt-technician
- Image:
- Host data dir: /srv/zt-technician/data
- Container data dir: `/opt/data`
- Compose file: templates/docker/docker-compose.zt-technician.yml

## Ports

| Host port | Container port | Purpose | Exposure |
|---|---:|---|---|
| TBD | 8643 | Gateway/API | localhost |
| TBD | 9120 | Dashboard | localhost |

## Messaging Integrations

- Feishu webhook:
- Telegram:
- Other:

## Credentials

See `env-map.md`. Do not paste values here.

## Memory & Skills

- Memory: /srv/zt-technician/data/memory
- Skills: zt-technical-analysis
- Crons: defined in skills
- Sessions: /srv/zt-technician/data/sessions

## Allowed Work

### 五维度量化评分体系 V1.0 (总分100分)

#### 1. 量能结构维度 (40分) - 涨停核心动力
- 量比启动 [±15分]：1.8~4.0区间+15，>6.0异常-10，<1.5无量
- 换手率 [±10/±15分]：3%~12%+10，<1.5%无量-10，>20%暴量-15
- 洗盘-起爆节奏 [±10分]：前两日量比<0.8 + 当日量比≥1.5 = 洗盘起爆+10

#### 2. 趋势与均线维度 (25分) - 趋势基础
- 均线排列 [±15分]：MA5>MA10>MA20多头+15，空头排列-15
- MA60方向 [-10分]：MA60下倾-10
- 回踩企稳 [+10分]：近5日最低价≤MA10*1.01 且 收盘>MA10
- 硬标准 [-5分]：收盘≤MA20弱势

#### 3. 关键位置形态维度 (12分) - 起爆临界点
- 振幅突破 [+8分]：振幅>4% 且 量比>1.5
- 缩量企稳 [+4分]：下影线/实体<0.3

#### 4. 筹码结构维度 (15分) - 筹码稳定
- 布林带宽 [±10分]：<12%集中+10，>25%发散-10
- 筹码锁定 [+5分]：当日带宽≤5日前带宽*1.3

#### 5. 资金与盘口维度 (8分) - 资金确认
- 分时承接 [±3分]：收盘/boll_mid>1.01+3，<0.98-3
- 主力净流入 [+3/+5/-8分]：净流入>2%+3，>5%+5，净流出>5%-8

### 一票否决规则 (评分=0)
- 放量破位：收盘<MA20 且 量比>1.8
- 持续缩量阴跌：连续3日量比<0.5且下跌

### 综合评定
- [高] ≥70分：具备强技术面涨停潜力
- [中] 50~69分：技术面尚可，需结合其他维度
- [低] 30~49分：技术面偏弱
- [无] <30分：无涨停潜力

### 数据来源
- Tushare stk_factor_pro：技术因子(量比/换手/均线/MACD/KDJ/RSI/布林)
- Tushare moneyflow：资金流向(T+1)

优先级：量价异动爆发 > 趋势多头结构 > 筹码锁仓集中 > 关键位置突破 > 分时资金回流

## Forbidden Work

- 情绪面分析（大盘情绪、题材情绪、舆情热点）
- 基本面分析（财报、估值、行业分析）
- 发送飞书通知
- 直接交易
- 忽略避雷规则：放量破位、跌破关键均线、高位巨量滞涨、筹码松动、连续缩量阴跌必须降级

## Owner

- zhangying
