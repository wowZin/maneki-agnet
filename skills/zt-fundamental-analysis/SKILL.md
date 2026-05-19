---
name: zt-fundamental-analysis
description: Use when the zt-fundamental agent needs to perform fundamental analysis on a candidate stock — earnings growth, theme/event catalyst, financial health, shareholder/chip concentration, valuation positioning — and return a 涨停 probability score with core support logic and fundamental risk points.
---

# ZT Fundamental Analysis

Perform fundamental analysis on a candidate stock and return a 涨停 probability score with core support logic and fundamental risk points.

This skill runs on the **zt-fundamental** agent.

## 触发条件

- 接收到 team-leader 下发的个股基本面分析任务（从 inbox 读取）
- 股票代码与名称明确，可正常获取基本面数据
- 股票未处于停牌状态

## 数据源

Tushare Pro MCP (已配置在 Hermes Agent config.yaml)

使用的 MCP 工具:

### 业绩盈利类
- `daily`: 历史日线行情 (close/pct_chg/pre_close，用于计算涨跌幅与价格位置)
- `daily_basic`: 每日指标 (pe_ttm/pb/turnover_rate/eps 等)
- `fina_indicator`: 财务指标 (净利润同比/营收同比/毛利率/净利率/资产负债率/商誉/研发占比等)
- `income`: 利润表 (营业收入/净利润/扣非净利润)
- `forecast`: 业绩预告 (预告类型/预告净利润上下限)

### 题材事件类
- `concept`: 概念板块分类 (所属概念板块列表)
- `news`: 新闻资讯 (个股相关新闻)
- `notice`: 公告信息 (业绩预告/重大事项/增持减持等公告)

### 财务健康类
- `fina_indicator`: 财务指标 (资产负债率/经营现金流/商誉/存货周转率/应收账款周转率)
- `balancesheet`: 资产负债表 (总资产/总负债/商誉/流动资产/流动负债)
- `cashflow`: 现金流量表 (经营活动现金流净额)

### 股东筹码类
- `top10_floating_holders`: 十大流通股东 (机构/社保/北向持仓变动)
- `stk_holdertrade`: 股东交易 (大股东增减持明细)
- `share_float`: 限售解禁 (解禁数量/解禁日期)

### 估值位置类
- `daily_basic`: 每日指标 (pe_ttm/pb/估值分位)
- `stk_factor_pro`: 估值因子 (市盈率/市净率/股息率等)

## Steps

1. **Receive task from team-leader**
   - Read task from inbox: `/srv/agent-bus/zt-fundamental/inbox/`
   - Extract stock code, name, board type, and any provided context.

2. **Fetch fundamental data**
   - 调用 MCP 工具 `daily_basic`，获取最近交易日 pe_ttm、pb、eps、turnover_rate
   - 调用 MCP 工具 `fina_indicator`，获取最近2期财务指标 (净利润同比增速/营收同比增速/毛利率/净利率/资产负债率/商誉)
   - 调用 MCP 工具 `income`，获取最近2期利润表 (营业收入/净利润/扣非净利润)
   - 调用 MCP 工具 `balancesheet`，获取最近1期资产负债表 (商誉/总资产/总负债)
   - 调用 MCP 工具 `cashflow`，获取最近1期现金流量表 (经营活动现金流净额)
   - 调用 MCP 工具 `forecast`，获取业绩预告 (预告类型/预告净利润上下限)
   - 调用 MCP 工具 `concept`，获取个股所属概念板块列表
   - 调用 MCP 工具 `notice`，获取最近30天重大公告 (业绩预告/增持/减持/重组等)
   - 调用 MCP 工具 `top10_floating_holders`，获取最近2期十大流通股东 (机构/社保持仓变动)
   - 调用 MCP 工具 `stk_holdertrade`，获取大股东增减持数据
   - 调用 MCP 工具 `share_float`，获取未来30天解禁计划
   - 调用 MCP 工具 `stk_factor_pro`，获取估值因子 (pe/pb/行业分位)
   - Parse and organize all fundamental data.

3. **Analyze 维度1: 盈利业绩维度（核心爆发因子）**
   - 优先级最高，是涨停最核心的基本面支撑。
   - Check net profit YoY growth (净利润同比增速):
     - > 100% → super high growth, +30
     - 50–100% → high growth, +20
     - 20–50% → moderate growth, +10
     - 0–20% → slight growth, +5
     - negative → declining, -10 to -15
   - Check deducted non-recurring net profit growth (扣非净利润增速):
     - If deducted growth << net profit growth → non-recurring distortion, reduce net profit score by -5 to -10
   - Check revenue growth (营收同比增速):
     - > 30% → +10, 10–30% → +5, < 10% → 0, negative → -5
   - Check earnings forecast (业绩预告):
     - 预增/扭亏 → +15, 预减/首亏 → -15
   - Check gross margin trend (毛利率趋势):
     - Rising → +5, stable → 0, declining → -5
   - Check whether main business dominates revenue (主业营收占比 > 80%):
     - Yes → +5, No → -5 (non-main revenue inflated)
   - Cap earnings sub-score at [-30, +40].

4. **Analyze 维度2: 题材与事件催化维度（短线涨停核心）**
   - 短线涨停几乎均由事件催化驱动。
   - Check concept sector relevance (概念板块):
     - 是否属于当前市场热点/政策风口板块 → +10 to +20
     - 是否属于新兴赛道 (AI/新能源/半导体等) → +5 to +10
   - Check recent announcements (近30天公告):
     - 重大中标/大订单 → +15
     - 资产重组/并购 → +15
     - 定增落地/回购/股权激励 → +10
     - 高送转/分红公告 → +5
     - 无重大利好公告 → 0
   - Check industry supply-demand gap (行业供需缺口):
     - If data indicates supply shortage/price surge → +10
   - Check news sentiment (新闻舆情):
     - Positive catalyst news → +5 to +10
     - Negative news → -5 to -10
   - Cap theme/event sub-score at [-15, +30].

5. **Analyze 维度3: 贡献健康维度（安全性兜底）**
   - 排查财务风险，规避暴雷标的；无财务隐患是潜力标的的基础门槛。
   - Check debt ratio (资产负债率):
     - < 40% → healthy, +5
     - 40–60% → moderate, 0
     - > 60% → risky, -5 to -10
   - Check goodwill (商誉/总资产):
     - Goodwill/total assets < 5% → safe, 0
     - 5–20% → caution, -5
     - > 20% → high risk, -15
   - Check operating cash flow (经营活动现金流净额):
     - Positive and growing → +5
     - Negative → -10 (cash flow problem)
   - Check inventory turnover (存货周转率):
     - Declining rapidly → -5 (inventory buildup)
   - Check accounts receivable turnover (应收账款周转率):
     - Declining → -5 (collection risk)
   - Check main business loss (主业亏损):
     - Main business loss (扣非净利润为负) → -15 (避雷优先规则触发)
   - Cap financial health sub-score at [-30, +10].

6. **Analyze 维度4: 股东与筹码维度（主力进场信号）**
   - 筹码集中、机构进场是涨停启动的重要前置信号。
   - Check top 10 floating holders change (十大流通股东变动):
     - 机构/社保/北向增持 → +10 to +15
     - 机构减持 → -5 to -10
   - Check shareholder count change (股东户数环比):
     - Decreasing (筹码集中) → +10
     - Increasing (筹码分散) → -5
   - Check major shareholder actions (大股东增减持):
     - 大股东增持/回购 → +10
     - 大股东减持 → -10
   - Check share unlock schedule (限售解禁):
     - Near-term (30天内) large unlock > 5% float → -15 (避雷规则触发)
     - Near-term unlock 1–5% float → -5
     - No near-term unlock → 0
   - Cap shareholder/chip sub-score at [-20, +20].

7. **Analyze 维度5: 估值性价比维度（低位启动条件）**
   - 低位低估标的好消息落地后涨停概率远高于高位高估标的。
   - Check PE_TTM position vs industry average:
     - PE < industry average × 0.7 (显著低估) → +15
     - PE ≈ industry average → 0
     - PE > industry average × 1.5 (高估) → -10
   - Check PB position vs industry:
     - PB < 1 → +10 (破净，极端低估)
     - PB < industry avg × 0.7 → +10
     - PB > industry avg × 1.5 → -5
   - Check historical price position (近3年估值区间):
     - At 3-year low zone → +10
     - At 3-year mid zone → 0
     - At 3-year high zone → -10
   - Cap valuation sub-score at [-15, +15].

8. **Apply priority and risk rules**
   - 优先级规则: 业绩爆发逻辑 > 行业题材催化逻辑 > 筹码资金逻辑 > 估值修复逻辑
     - If earnings sub-score >= 30 and at least 2 other dimensions positive → boost composite by +10
   - 避雷优先规则:
     - If financial health sub-score <= -20 → directly downgrade to 涨停潜力等级"低" or "无"
     - If near-term large unlock detected → downgrade by one tier
     - If goodwill/total assets > 20% → downgrade by one tier
     - If main business loss → downgrade to "无"
   - 多维度共振判定:
     - 3+ dimensions with positive sub-scores ≥ 10 each → mark as "多维度共振" → boost composite by +5

9. **Calculate composite fundamental score**
   - Composite = earnings score + theme/event score + financial health score + shareholder/chip score + valuation score
   - Apply priority boost (+10 if earnings dominant + 2+ other positive)
   - Apply resonance boost (+5 if 3+ dimensions ≥ 10 each)
   - Normalize to 0–100 probability scale:
     - raw range approximately [-70, +90] (before boosts)
     - map to 0–100: `probability = max(0, min(100, (composite + 70) / 160 * 100))`
   - Determine 涨停潜力等级:
     - probability ≥ 70 → "高"
     - probability 45–69 → "中"
     - probability 20–44 → "低"
     - probability < 20 → "无"

10. **Return result to team-leader**
   - Write result to outbox: `/srv/agent-bus/zt-fundamental/outbox/{code}-fundamental-{timestamp}.json`
   - Include: stock code, 涨停潜力等级, composite probability, all sub-scores, core support logic, fundamental risk points, timestamp.

## Result Format

```json
{
  "stock_code": "600123",
  "agent": "zt-fundamental",
  "analysis_type": "fundamental",
  "probability_score": 78,
  "zt_potential_level": "高",
  "sub_scores": {
    "earnings_growth": 35,
    "theme_event_catalyst": 20,
    "financial_health": 5,
    "shareholder_chip": 15,
    "valuation_positioning": 10
  },
  "priority_boost": 10,
  "resonance_boost": 5,
  "core_support_logic": [
    "净利润同比增速120%，业绩超预期爆发",
    "扣非净利润增速95%，主业真实高增长",
    "所属AI概念板块为当前市场主线风口",
    "十大流通股东中2家机构新增持仓",
    "PE_TTM显著低于行业平均，估值处于低位启动区间"
  ],
  "fundamental_risks": [
    "资产负债率62%偏高，需关注偿债压力",
    "近30天有小额限售解禁(2%流通股)"
  ],
  "dimension_resonance": true,
  "analyzed_at": "2026-05-18T09:15:00+08:00"
}
```

## 评分规则速览

| 维度 | 分值范围 | 权重优先级 |
|------|---------|-----------|
| 维度1: 盈利业绩 | [-30, +40] | 最高 |
| 维度2: 题材事件催化 | [-15, +30] | 高 |
| 维度3: 贡献健康 | [-30, +10] | 兜底(避雷) |
| 维度4: 股东筹码 | [-20, +20] | 中 |
| 维度5: 估值性价比 | [-15, +15] | 辅助 |

涨停潜力等级判定:
- ≥ 70 → 高
- 45–69 → 中
- 20–44 → 低
- < 20 → 无

避雷优先规则:
- 主业亏损 → 直接判定"无"
- 贡献健康分 ≤ -20 → 降一档
- 近30天大额解禁(>5%流通) → 降一档
- 商誉/总资产 > 20% → 降一档

## Pitfalls

- Do not treat non-recurring profit spikes as genuine growth; always cross-check net profit vs deducted non-recurring net profit (扣非净利润). If deducted growth is far below headline growth, penalize accordingly.
- Single dimension positive is only a minor boost; do not inflate probability based on one strong dimension alone. Multi-dimension resonance is required for "高" level.
- 避雷优先: financial health risks (high goodwill, large unlock, main business loss) must override positive signals in other dimensions. Do not ignore red flags even if earnings look strong.
- Concept/theme analysis must be tied to current market hot topics, not just any concept. A concept that is not currently in market focus provides negligible catalyst value.
- Earnings forecast (业绩预告) data may be preliminary and subject to revision; flag this uncertainty in risk points.
- For stocks with fewer than 2 reporting periods of financial data, fundamental analysis is less reliable; flag these explicitly.
- Do not analyze stocks in trading halt; check halt status before fetching data.
- Shareholder data (十大流通股东) is only updated quarterly; it may lag by up to 3 months. Flag this latency in the result.