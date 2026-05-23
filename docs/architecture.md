# 架构设计

## 项目定位 — Agent Room

本项目是一个 **Agent Room**（玩法集合），每个玩法是一个独立的自包含模块，共享同一套基础设施。

```
maneki-agent/
├── plays/                    ← 各玩法（垂直隔离）
│   ├── limit_up/             ← 涨停预测玩法
│   │   ├── pipeline.py       ← 主流程：扫描→评分→推送
│   │   ├── agents/           ← 评分维度（每个维度独立文件）
│   │   ├── review.py         ← 收盘复盘
│   │   ├── optimize.py       ← 权重优化器
│   │   ├── health_patrol.py  ← 健康巡检
│   │   ├── verify.py         ← 评分验证
│   │   └── data/             ← 该玩法全部数据
│   └── xxx/                  ← 其他玩法（未来）
├── feishu_bot/               ← 统一飞书入口（路由到各play）
├── wiki/                     ← 共享知识库
├── scripts/proxy_utils.py    ← 共享基础设施（代理池）
├── docs/                     ← 文档
└── CLAUDE.md                 ← 项目约束
```

## 设计原则

1. **玩法垂直隔离** — 每个 `plays/xxx/` 自包含 pipeline、评分、数据、配置
2. **基础设施共享** — 飞书Bot、代理池、知识库跨玩法复用
3. **统一入口路由** — 飞书Bot 根据消息内容自动路由到对应玩法
4. **文档先行** — 修改前先写文档，审核后再改代码

## 涨停预测 (plays/limit_up) 数据流

```
[东财API(代理)] → scan_surge() → 候选池(≈400只)
                       ↓
             五维度并行评分（ThreadPoolExecutor）
          ┌──────┬──────┬──────┬──────┬──────┐
     基本面  技术面  资金面  情绪面  短线博弈
          └──────┴──────┴──────┴──────┴──────┘
                       ↓
              加权Top3择优 → 总分排序
                       ↓
              阈值≥35 → Top3 推送飞书
```

## 各玩法 vs 共享设施

| 层 | 目录 | 职责 |
|----|------|------|
| 玩法 | `plays/xxx/` | 评分逻辑、pipeline、专属数据 |
| 玩法 | `plays/xxx/agents/` | 各评分维度（独立文件，统一签名 `score_xxx(code)→(int,str)`） |
| 路由 | `feishu_bot/` | 统一飞书入口，根据消息路由到对应玩法 |
| 共享 | `scripts/proxy_utils.py` | 代理池管理（zdtps动态代理） |
| 共享 | `wiki/` | 跨玩法知识库（SCHEMA+concepts+plays/xxx/entities） |

## 玩法内文件约定

每个 `plays/xxx/` 目录：

```
plays/xxx/
├── pipeline.py       ← 主流程（扫描→评分→推送）
├── agents/           ← 评分维度（统一签名）
│   ├── __init__.py
│   ├── fundamental_agent.py
│   ├── technical_agent.py
│   ├── fundflow_agent.py
│   ├── sentiment_agent.py
│   └── shortterm_agent.py
├── review.py         ← 复盘逻辑
├── optimize.py       ← 优化器（可选）
├── health_patrol.py  ← 巡检（可选）
├── verify.py         ← 验证脚本
├── data/             ← 全部数据
│   ├── analysis/     ← 评分结果
│   ├── signals/      ← 原始信号
│   ├── pushed/       ← 推送记录
│   ├── weights/      ← 优化结果
│   ├── reports/      ← 复盘报告
│   └── logs/         ← 运行日志
└── __init__.py
```

## 定时任务调度

| 任务 | 时间 | 调用 |
|------|------|------|
| 盘中扫描 | 周一至五 9:35~14:55 每5分钟 | `plays/limit_up/pipeline.py` |
| 收盘复盘 | 周一至五 18:00 | `plays/limit_up/review.py` |
| 权重优化 | 周一至五 19:00 | `plays/limit_up/optimize.py` |
| Wiki compile | 周一至五 20:00 | `wiki/compile.py` |
| 健康巡检 | 周一至五 10~14点整点 | `plays/limit_up/health_patrol.py` |

## 飞书Bot路由

```
用户发消息 → feishu_bot/handler.py
   ├─ 含股票代码/名称 → plays/limit_up/pipeline.py （个股分析）
   ├─ 追问指标 → get_dim_explanation() / get_rating_explanation()
   ├─ 知识问题 → wiki/ 查询（grep + DeepSeek 合成回答）
   └─ 闲聊 → 能力介绍
```
