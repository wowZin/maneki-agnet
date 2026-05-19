# 工作流详解

## 盘中扫描流程

### Step 1: 触发 (zt-trigger)

```text
时间: 工作日 9:00 - 14:50，每10分钟一次
动作: 调用涨速排名API
输出: 涨速前100股票列表
```

API 返回字段:
- code: 股票代码
- name: 股票名称
- surge_speed: 涨速 (%)
- current_price: 当前价格
- change_pct: 涨跌幅 (%)
- volume_ratio: 量比
- sector: 所属板块

### Step 2: 分发 (zt-team-leader)

```text
接收: zt-trigger 的 Top100 列表
动作: 并行分发给4个子Agent
格式: 统一任务JSON (见 templates/task-bus/task-template.md)
```

分发策略:
- 全量分发: 每个子Agent收到完整的100只股票列表
- 并行执行: 4个子Agent同时开始分析
- 超时控制: 5分钟内必须返回结果

子Agent列表:
- zt-technician (技术面): K线形态、均线、MACD、量价配合等
- zt-fundamental (基本面): 财报质量、估值、行业景气、公告事件等
- zt-fund-flow (资金面): 主力净流入、大单占比、北向资金、连续性等
- zt-sentiment (情绪面): 涨停基因、连板效应、板块共振、龙头辨识等

### Step 3: 分析 (4个子Agent并行)

每个子Agent对每只股票:
1. 获取该维度的实时数据
2. 运行该维度的分析模型
3. 输出 0-100 的涨停概率评分
4. 附带信号列表和风险提示

评分标准化:
- 所有原始指标映射到 0-100 分
- 评分 = 各子指标加权平均
- 不确定时倾向给出中等偏低分数 (保守原则)

### Step 4: 聚合 (zt-team-leader)

```text
输入: 4个子Agent的评分结果
动作: 加权聚合
公式: 综合置信度 = Σ(score_i × weight_i) / Σ(weight_i)
默认权重: 各子Agent权重均为1
过滤: 置信度 > 50% 纳入信号表
```

信号表字段:
- 序号
- 股票名称
- 参与预测的Agent
- 综合置信分

### Step 5: 推送 (zt-team-leader -> 飞书)

```text
条件: 信号表非空
动作: 构建飞书卡片消息，发送到webhook
格式: 见 templates/feishu-notification-templates.md
```

如果本轮无置信度 > 50% 的股票，静默不发送。

---

## 收盘复盘流程

### Step 1: 获取实际结果 (16:00)

```text
动作: 查询当日所有被预测股票的实际涨跌结果
标记: 涨停 = hit, 未涨停 = miss
```

### Step 2: 计算子Agent鉴别力

```text
鉴别力 = avg_score(命中股票) - avg_score(未命中股票)

鉴别力越高，说明该Agent的评分越能区分涨停与非涨停。
鉴别力 < 0 说明该Agent评分反向，需重点调整。
```

### Step 3: 权重调整建议

```text
规则:
- 鉴别力 > 0.6: 建议提升权重 +0.2
- 鉴别力 0.3~0.6: 维持当前权重
- 鉴别力 < 0.3: 建议降低权重 -0.2
- 鉴别力 < 0: 建议大幅降低权重 -0.5

权重范围: 0.5 ~ 3.0
调整建议需人工确认后方可写入配置生效。
```

### Step 4: 生成复盘报告

```text
内容:
1. 今日统计 (总预测/命中/未命中/准确率)
2. 各子Agent表现 (权重/鉴别力/命中率/调整建议)
3. 权重调整方案
4. 精选案例 (命中最高/误判最严重的股票)
```

### Step 5: 推送复盘报告

```text
动作: 发送到飞书复盘专用webhook
格式: 见 templates/feishu-notification-templates.md
保留: 报告存档到 /srv/zt-team-leader/data/reviews/YYYY-MM-DD.json
```