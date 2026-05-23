# Maneki Agent — A股量化玩法集合

基于 Agent Room 架构的 A 股量化策略系统。当前包含 **涨停预测** 玩法，支持多玩法横向扩展。

```
用户 → 飞书Bot(统一入口) → 路由到 plays/xxx/pipeline.py → 评分→推送
```

## 当前玩法

### limit_up — 涨停预测

盘中实时扫描涨速异动股，五维度评分 + 加权 Top3 择优推送，盘后自动复盘。

```
cron(每5分钟) → plays/limit_up/pipeline.py → 五维度评分 → ≥35分 Top3 推送飞书
                                  ↓
                            plays/limit_up/data/
                                  ↓
                 cron(18:00) → plays/limit_up/review.py → 复盘报告
```

### 五维度评分

| 维度 | 权重 | 说明 |
|------|:----:|------|
| 基本面 | 1.5 | ROE、扣非净利、营收增速、公告、解禁 |
| 技术面 | 1.0 | 均线排列、MACD/KDJ、量价配合、换手 |
| 资金面 | 0.5 | 主力净流入、龙虎榜、封板质量、融资 |
| 情绪面 | 1.2 | 涨停基因、连板效应、竞价博弈、人气排名 |
| 短线博弈 | 1.5 | 封板质量、连板动量、开盘博弈、攻击独特性 |

**总分 = 加权Top3择优** — 取加权贡献最高的 3 个维度计算加权均值。

## 系统架构

```
maneki-agent/
├── plays/                           ← 各玩法（垂直隔离）
│   ├── limit_up/                    ← 涨停预测
│   │   ├── pipeline.py              ← 扫描→评分→推送
│   │   ├── agents/                  ← 五维度评分
│   │   │   ├── fundamental_agent.py
│   │   │   ├── technical_agent.py
│   │   │   ├── fundflow_agent.py
│   │   │   ├── sentiment_agent.py
│   │   │   └── shortterm_agent.py
│   │   ├── review.py                ← 收盘复盘
│   │   ├── optimize.py              ← 权重优化器
│   │   ├── health_patrol.py         ← 健康巡检
│   │   ├── verify.py                ← 评分验证
│   │   └── data/                    ← 全部数据
│   │       ├── analysis/ signals/ pushed/
│   │       ├── weights/ reports/ history/
│   │       └── logs/
│   └── xxx/                         ← 新玩法（扩展点）
├── feishu_bot/                      ← 统一飞书入口（路由到各play）
│   ├── main.py                      ← FastAPI 服务
│   ├── handler.py                   ← 消息处理 + 知识库查询 + 路由
│   └── feishu_client.py             ← 飞书API封装
├── wiki/                            ← 共享知识库
│   ├── concepts/                    ← 跨玩法通用知识
│   ├── plays/                       ← 玩法专属知识
│   └── compile.py                   ← 每日编译
├── scripts/proxy_utils.py           ← 共享：zdtps动态代理池
├── docs/
│   ├── architecture.md              ← 架构设计
│   ├── weight-optimizer-v2.md       ← 权重优化设计
│   └── ... 
├── tests/                           ← 单测
├── data/ → plays/limit_up/data/     ← 向后兼容symlink
└── .env                             ← 环境变量
```

## 数据源

| 场景 | 数据源 | 方式 |
|------|--------|------|
| 盘中涨速扫描 | 东方财富 push2 API | requests + zdtps 动态代理 |
| 实时行情/资金流 | 东方财富 clist API | requests + zdtps 动态代理 |
| 历史财务/日线 | Tushare | REST API |
| 涨停列表(盘后) | Tushare limit_list_d | REST API |

> push2.eastmoney.com 被 TCP 层封禁，必须走 zdtps 代理。代理 IP 约 2-3 分钟过期，`scripts/proxy_utils.py` 自动刷新。

## 定时任务

| 任务 | 时间 | 调用 |
|------|------|------|
| 早盘扫描 | 周一至五 9:35~11:30 每5分钟 | `plays/limit_up/pipeline.py` |
| 午盘扫描 | 周一至五 13:05~14:55 每5分钟 | `plays/limit_up/pipeline.py` |
| 收盘复盘 | 周一至五 18:00 | `plays/limit_up/review.py` |
| 权重优化 | 周一至五 19:00 | `plays/limit_up/optimize.py` |
| Wiki 编译 | 周一至五 20:00 | `wiki/compile.py` |
| 健康巡检 | 周一至五 10~14点整点 | `plays/limit_up/health_patrol.py` |

## 扩展新玩法

参见 `CLAUDE.md` 中的扩展规范。新建 `plays/新玩法名/` 即可：

```
plays/新玩法名/
├── pipeline.py       ← 主流程
├── agents/           ← 评分维度
├── review.py         ← 复盘（可选）
└── data/             ← 数据
```

## 部署

### 环境要求
- Python 3.10+
- 2C4G 以上服务器

### 启动

```bash
cd /root/maneki-agent

# 配置 .env（Tushare Token、飞书凭证、代理）
cp .env.example .env

# 启动飞书Bot
python -m uvicorn feishu_bot.main:app --host 0.0.0.0 --port 8080 &

# 手动运行一次扫描
python plays/limit_up/pipeline.py
```

## 风险提示

- 本系统仅供研究参考，不构成投资建议
- 涨停预测受市场环境影响，历史表现不代表未来
- 权重调整建议需人工确认后生效
- 不得用于实际交易决策

## License

MIT
