# Maneki Agent — A股涨停预测系统

基于五维度评分的A股涨停潜力评估系统。盘中实时扫描涨速异动股，盘后自动复盘+权重AB对比。

```
东财异动扫描(API+代理) → 五维度并行评分 → 加权聚合 → 飞书推送(Top3)
                                    ↘ Top3择优排序(辅助)
收盘后: 复盘引擎 → 命中率/鉴别力/权重AB → 飞书复盘报告
```

## 系统架构

```
cron(每5分钟) → zt_pipeline.py → 五维度评分 → ≥35分Top3推送 → 飞书Bot
                                       ↓
                                  data/analysis/
                                       ↓
                          cron(18:00) → zt_daily_review.py → 复盘报告
```

## 五维度评分

| 维度 | 权重 | 区分度 | 说明 |
|------|:--:|------|------|
| 基本面 | 1.5 | 最强(91%有效) | ROE、扣非净利、营收增速、公告、解禁 |
| 技术面 | 1.0 | 中(73%有效) | 均线排列、MACD/KDJ、量价配合、换手 |
| 资金面 | 0.5 | 弱(30%非零) | 主力净流入、龙虎榜、封板质量、融资 |
| 情绪面 | 1.2 | 强(95%有效) | 涨停基因、连板效应、竞价博弈、人气排名 |
| 短线博弈 | 1.5 | 强(100%有效) | 封板质量、连板动量、开盘博弈、攻击独特性 |

**加权总分** = Σ(维度分 × 权重) / Σ权重（分母=5.7）

### 权重原则

正比于有效区分度——能筛出差别的维度给高权，大量同分的维度给低权（如资金面70%得0分，降为加分项不稀释总分）。

## 置信度与推送

| 等级 | 范围 | 操作 |
|------|------|------|
| 高 | 60-100 | 标红推送 |
| 中高 | 45-59 | 标橙推送 |
| 中等 | 35-44 | 标黄推送 |
| 低 | 0-34 | 不推送，仅存档 |

推送阈值 **≥35分** 取 Top3，无达标则不推送。

## 双跑机制

V2.4 起每次推送同时输出两套排序供对比：

- **加权总分**（默认推送依据）
- **Top3择优**（取三个最高维度均值，捕捉极端信号）

权重变更时启用 **权重AB对比**：同份数据用新旧两套权重分别算分，连续3天新权重优于旧才固化。

## 数据源

| 场景 | 数据源 | 方式 |
|------|--------|------|
| 盘中涨速扫描 | 东方财富 push2 API | Chrome CDP + zdtps动态代理 |
| 实时行情/资金流 | 东方财富 clist API | requests + zdtps动态代理 |
| 历史财务/日线 | Tushare | REST API |
| 涨停列表(盘后) | Tushare limit_list_d | REST API |

> push2.eastmoney.com 被服务器TCP层封禁，必须走 zdtps 代理。代理IP约2-3分钟过期，proxy_utils自动刷新。

## 定时任务

| 任务 | 时间 | 说明 |
|------|------|------|
| 早盘扫描1 | 9:35-9:59 每5分钟 | 开盘异动捕捉 |
| 早盘扫描2 | 10:00-10:55 每5分钟 | 持续监控 |
| 早盘扫描3 | 11:00-11:30 每5分钟 | 午盘前最后一轮 |
| 午盘扫描1 | 13:05-13:55 每5分钟 | 午后开盘 |
| 午盘扫描2 | 14:00-14:55 每5分钟 | 尾盘冲刺 |
| 收盘复盘 | 18:00 | 命中率/鉴别力/权重AB/飞书报告 |

## 目录结构

```
maneki-agent/
├── scripts/
│   ├── zt_pipeline.py        # 主流程: 扫描→评分→推送
│   ├── zt_daily_review.py    # 复盘引擎: 命中率/鉴别力/AB对比
│   ├── score_shortterm.py    # 短线博弈面评分
│   ├── cdp_fetch.py          # Chrome CDP数据抓取
│   ├── proxy_utils.py        # zdtps动态代理
│   └── scan_cdp.py           # CDP扫描(备用)
├── feishu_bot/
│   ├── main.py               # FastAPI飞书回调服务
│   └── handler.py            # 消息处理/评分调用
├── docs/
│   ├── architecture.md       # 架构设计
│   ├── flow.md               # 工作流
│   ├── scoring.md            # 评分体系+权重原则
│   ├── review.md             # 复盘机制+双跑对比
│   ├── agent.md              # 系统说明书
│   ├── agent-sentiment.md    # 情绪面策略
│   ├── agent-fund-flow.md    # 资金面策略
│   ├── agent-technician.md   # 技术面策略
│   ├── agent-fundamental.md  # 基本面策略
│   └── agent-leader.md       # 聚合推送规则
├── tests/
│   ├── test_v24_incremental.py
│   ├── test_daily_review.py
│   ├── test_fundflow_v23.py
│   ├── test_sentiment_v23.py
│   ├── test_fundamental_v15.py
│   └── test_technical_v20.py
├── data/
│   ├── analysis/             # 各时段分析结果
│   ├── pushed/               # 飞书推送记录
│   ├── signals/              # 涨速信号原始数据
│   ├── reports/              # 复盘报告(JSON+MD)
│   └── history/              # 历史回测数据
├── .env                      # 环境变量(权重/Token/代理)
└── requirements.txt
```

## 部署

### 环境要求

- Python 3.10+
- Chrome/Chromium (CDP调试端口9222)
- 2C4G 以上服务器

### 启动

```bash
cd /root/maneki-agent

# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 .env（权重、Tushare Token、飞书凭证、代理）
cp .env.example .env
vim .env

# 3. 启动Chrome CDP（代理模式）
python scripts/proxy_utils.py

# 4. 启动飞书Bot
python -m uvicorn feishu_bot.main:app --host 0.0.0.0 --port 8080 &

# 5. 手动运行一次扫描
python scripts/zt_pipeline.py
```

### 权重配置

在 `.env` 中调整。变更时同步填写 `_PREV` 变量启用AB对比：

```bash
AGENT_WEIGHT_FUNDAMENTAL=1.5
AGENT_WEIGHT_TECHNICAL=1.0
AGENT_WEIGHT_FUND_FLOW=0.5
AGENT_WEIGHT_SENTIMENT=1.2
AGENT_WEIGHT_SHORTTERM=1.5

# 上一版权重（AB对比用，相同时不生效）
AGENT_WEIGHT_FUNDAMENTAL_PREV=1.5
AGENT_WEIGHT_TECHNICAL_PREV=1.0
# ...
```

## 风险提示

- 本系统仅供研究参考，不构成投资建议
- 涨停预测受市场环境影响，历史表现不代表未来
- 权重调整建议需人工确认后生效
- 不得用于实际交易决策

## License

MIT
