# 架构设计

## 涨停预测 Agent Room 架构

### 设计原则

1. **分而治之**: 每个子 agent 只负责一个分析维度，独立评估
2. **加权民主**: 通过权重投票机制聚合结论，避免单一视角偏差
3. **闭环复盘**: 每日收盘后自动复盘，根据实际表现调整权重
4. **最小特权**: 子 agent 只能分析，不能决策；只有 team-leader 输出信号

### 数据流

```text
[涨速API] --Top100--> zt-trigger
                        |
                        v
                   zt-team-leader (dispatch)
                   /      |      \\      \\      \\
                  v       v       v      v      v
       zt-technician  zt-fundamental  zt-fund-flow  zt-sentiment  zt-shortterm
          (score)        (score)        (score)      (score)       (score)
                  \\       |       /      /        /
                   v      v      v     v        v
                   zt-team-leader (aggregate)
                        |  ╱ 加权求和
                        |  ╲  Top3择优（V2.4并行）
                        |
              [置信度 > 50%] --> 飞书Webhook
              [16:00 复盘]   --> 飞书Webhook
```

### 控制面 vs 运行时

控制面 (本仓库):

```text
./
  agents/    -- agent 定义和文档
  docs/      -- 架构和流程文档
  shared/    -- 共享配置
  templates/ -- 模板
  skills/    -- 技能定义
```

运行时数据:

```text
/srv/<agent-name>/data
  .env          -- 环境变量
  memory/       -- 持久记忆
  sessions/     -- 会话记录
  logs/         -- 日志
  predictions/  -- 预测存档
  reviews/      -- 复盘存档
```

### 容器拓扑

每个 agent 独立容器运行:

```text
| zt-trigger:       8642/9119
| zt-technician:    8643/9120
| zt-fundamental:   8644/9121
| zt-fund-flow:     8645/9122
| zt-sentiment:     8646/9123
| zt-shortterm:     8647/9124
| zt-team-leader:   8650/9130
```

所有端口仅绑定 localhost，通过 Docker 内部网络互通。

### V2.4 增量改进

| 改进项 | 说明 | 涉及组件 |
|--------|------|---------|
| Top-N 择优排序 | 加权求和之外新增 Top3 均值排序，补捉极端信号 | 聚合层 |
| 攻击独特性因子 | 第5维度新增子因子(20%)，含涨停基因+高开率+弱转强 | score_shortterm |
| 弱转强分支 | 第一层粗筛新增弱转强候选 | zt-trigger |
| 情绪熔断+冰点 | 否决6/7，炸板率>40%+跌停>15家熔断，冰点1/4仓位试探 | zt-sentiment |

### 调度

| 调度项 | Cron 表达式 | 说明 |
|---|---|---|
| 盘中扫描 | `*/10 9-14 * * 1-5` | 工作日9:00-14:50每10分钟 |
| 收盘复盘 | `0 16 * * 1-5` | 工作日16:00 |

注意: 14:50 是最后一次扫描触发(14:50触发，15:00前完成)，确保覆盖到尾盘异动。

### 超时与容错

- 子 agent 单轮分析超时: 5 分钟
- 整轮聚合超时: 8 分钟
- 飞书通知重试: 3 次，间隔 5s
- 超时未返回的子 agent 视为弃权，权重归零
- 所有预测结果持久化到 `/srv/zt-team-leader/data/predictions/`