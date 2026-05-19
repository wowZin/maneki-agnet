# 数据源说明

## 统一数据源: Tushare Pro MCP

所有 agent 通过 Tushare MCP Server 访问数据，已配置在 Hermes Agent config.yaml 中。

### MCP 配置

已在 `~/.hermes/config.yaml` 中配置:
```yaml
mcp_servers:
  tushareMcp:
    url: https://api.tushare.pro/mcp/token=<TUSHARE_TOKEN>
    enabled: true
    tools:
      enabled: all
```

连接状态: 258 个工具可用

### 各 Agent 使用的 Tushare MCP 工具

| Agent | MCP 工具 | 用途 |
|---|---|---|
| zt-trigger | `rt_k` (实时日线) + `daily_basic` | 涨速排名筛选 |
| zt-trigger | `cls_stock_shock` (财联社个股异动) | 涨停/连板/炸板池数据 |
| zt-technician | `daily` + `stk_factor_pro` | 日K行情、技术面因子(MACD/KDJ/RSI等) |
| zt-technician | `stk_mins` | 分时K线数据 |
| zt-volume-analyst | `daily` + `daily_basic` | 日线行情、换手率、量比 |
| zt-volume-analyst | `limit_list` + `limit_list_d` | 涨跌停统计、封板数据 |
| zt-fund-flow | `moneyflow` + `moneyflow_dc` | 个股资金流向(东财+Tushare) |
| zt-fund-flow | `moneyflow_hsgt` + `hsgt_top10` | 沪深港通资金、十大成交股 |
| zt-sentiment | `limit_step` (连板天梯) | 连板晋级数据 |
| zt-sentiment | `limit_cpt_list` (涨停最强板块) | 板块涨停统计 |
| zt-sentiment | `ths_daily` + `ths_member` | 同花顺板块行情和成分 |
| zt-sentiment | `cls_stock_shock` | 财联社涨停池 |
| zt-team-leader | `stk_limit` + `limit_list` | 盘后验证涨跌停 |

### 核心 Tushare MCP 工具对照

#### 涨速排名 (zt-trigger)
- `rt_k`: 实时日K线行情，支持通配符提取全部股票实时数据
- `cls_stock_shock`: 财联社涨停/连板/炸板/跌停池
- 参数: trade_date, ts_code(可通配)

#### 日线行情 (zt-technician / zt-volume-analyst)
- `daily`: 历史日线行情 (open/high/low/close/vol/amount/pct_chg)
- `daily_basic`: 每日指标 (turnover_rate/volume_ratio/pe_ttm等)
- `stk_factor_pro`: 技术面因子专业版 (MACD/KDJ/RSI/布林带等)

#### 涨跌停数据 (zt-volume-analyst / zt-sentiment / zt-team-leader)
- `stk_limit`: 每日涨跌停价格 (up_limit/down_limit)
- `limit_list`: 每日涨跌停统计 (封板时间/打开次数)
- `limit_list_d`: 涨跌停和炸板数据详细
- `limit_step`: 连板天梯 (连板天数晋级)
- `limit_cpt_list`: 涨停最强板块统计
- `limit_list_ths`: 同花顺涨跌停榜单

#### 资金流向 (zt-fund-flow)
- `moneyflow`: 个股资金流向 (大单小单成交)
- `moneyflow_dc`: 东方财富个股资金流向
- `moneyflow_ths`: 同花顺个股资金流向
- `moneyflow_hsgt`: 沪深港通资金流向
- `hsgt_top10`: 沪深港通十大成交股

#### 板块数据 (zt-sentiment)
- `ths_daily`: 同花顺概念板块行情
- `ths_member`: 同花顺概念板块成分
- `ths_hot`: 同花顺App热榜
- `dc_daily`: 东方财富概念板块行情
- `dc_member`: 东方财富概念板块成分
- `dc_hot`: 东方财富App热榜

#### 实时数据 (盘中使用)
- `rt_k`: 实时日K线
- `rt_min`: 实时分钟数据 (1~60min)
- `stk_auction`: 开盘竞价成交(当日)

### 频率限制

Tushare 按积分等级限制:
- 单次最大返回条数因接口不同 (100~4500)
- 每分钟请求次数有上限
- 建议优先使用批量/实时接口减少调用次数
- 盘中实时接口 (`rt_k`, `rt_min`) 可一次提取全市场数据