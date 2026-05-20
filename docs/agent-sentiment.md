==================================================
【情绪面涨停预判Agent V1.1 量化落地版】
面向操盘手+量化从业者的纯情绪打分体系
> ⚠️ **数据源时效性**：本文档标注的Tushare接口均为T+1数据，仅适用于收盘复盘。盘中分析必须使用CDP实时数据或akshare实时接口（如stock_fund_flow_individual）。
==================================================

一、角色定位与核心目标
- 定位：专注A股T+1~T+3情绪周期博弈的智能分析Agent。
- 核心目标：筛选处于高情绪风口、主线抱团、资金接力意愿强的标的；剔除退潮期、高位杀跌、跟风杂毛股。
- 边界纪律：仅依赖全市场情绪数据、题材热度、资金流向偏好、舆情热度、龙虎榜/人气榜、集合竞价动能；严禁引入任何技术指标（均线/量价/K线/筹码）与基本面/财务变量。

二、量化打分模型与权重分配（总分100分）
1. 大盘整体情绪维度    权重 30分（大环境根基）
2. 主线题材情绪维度    权重 30分（短线核心）
3. 板块梯队情绪维度    权重 20分（跟风强弱判定）
4. 个股人气资金情绪维度 权重 10分（起爆直接动力）
5. 集合竞价情绪动能维度 权重 15分（开盘前情绪强度）← V1.1新增

计分机制：
- 各维度按阈值累加得分，上限为权重分。
- 多情绪共振判定：≥3个维度得分≥该维度权重的70%，且未触发一票否决，判定为高潜力。
- 潜力分级（与全系统统一标准）：
  ≥75分：高强度涨停/隔日起爆/连板潜力
  55–74分：中等潜力
  35–54分：低潜力
  <35分或触发否决：无潜力

> ⚠️ 注意：早期版本阈值（70/50/30）已废弃，全系统统一采用75/55/35。

三、一票否决规则（情绪面风控底线）
触发任意一条，直接判定【涨停预测：否】，不进入打分：
1. 市场退潮：当日炸板率>45% 或 昨日连板晋级成功率<40%
2. 主线崩塌：核心龙头断板跌停 或 所属题材资金连续2日净流出且涨停数下降>30%
3. 高位杀跌：市场最高连板高度连续2日下降，且高位股（≥3板）平均溢价<-2%
4. 个股情绪溃散：近5日内出现≥1次“核按钮”（收盘跌幅≤-7%且放量）或 龙虎榜知名游资单日净卖出>3000万
5. 纯跟风弱势：所属板块仅该股独涨，无梯队扩散且人气排名跌出全市场前200

四、六大维度因子库与量化阈值（直接可编码）

【维度1】大盘整体情绪（30分）
- 赚钱效应：昨日涨停股今日平均溢价≥1.5%，得+10分；<0%扣10分
  > 截断规则：FinalScore = max(0, min(10, RawScore))
- 涨跌结构：涨停>35家且跌停<5家，涨跌比>1.5，得+8分；涨跌比<0.8扣8分
  > 截断规则：FinalScore = max(0, min(8, RawScore))
- 炸板控制：炸板率<30%，得+7分；>45%触发一票否决
  > 截断规则：FinalScore = max(0, min(7, RawScore))
- 空间高度：最高连板≥4板，得+5分；连续2日下降扣5分
  > 截断规则：FinalScore = max(0, min(5, RawScore))

【维度2】主线题材情绪（30分）
- 题材地位：同花顺/东财概念热度排名第1，得+10分
  > 截断规则：FinalScore = max(0, min(10, RawScore))
- 发酵强度：所属题材当日涨停数≥3，且较前一日递增，得+8分
  > 截断规则：FinalScore = max(0, min(8, RawScore))
- 资金共识：题材主力净流入规模排名前5，得+7分
  > 截断规则：FinalScore = max(0, min(7, RawScore))
- 周期标签：系统判定为"启动/发酵/高潮初期"，得+5分；"退潮/分歧末期"扣20分
  > 截断规则：FinalScore = max(0, min(5, RawScore))
> 量化代理：题材周期 = IF(龙头不断板 & 梯队完整 & 涨停数递增, 发酵, IF(炸板率>40% & 资金流出, 退潮, 震荡))

【维度3】板块梯队情绪（20分）
- 梯队完整：板块内存在明确龙头+2板/3板梯队，得+10分
  > 截断规则：FinalScore = max(0, min(10, RawScore))
- 扩散力度：板块涨停家数≥5只，且非涨停股平均涨幅>0%，得+6分
  > 截断规则：FinalScore = max(0, min(6, RawScore))
- 位置优势：个股处于板块涨幅/资金净流入前30%，得+4分
  > 截断规则：FinalScore = max(0, min(4, RawScore))
- 负面扣分：板块仅孤龙上涨、无跟风梯队，扣10分
  > 截断规则：FinalScore = max(0, min(20, RawScore))

【维度4】个股人气资金情绪（10分）
- 换手活跃度：当日换手率∈[10%, 25%]（衡量情绪资金博弈热度），得+2分；>25%过热扣2分
  > 截断规则：FinalScore = max(0, min(2, RawScore))
- 资金记忆：近20日出现≥2次涨停，得+3分；≥1次得+1分
  > 截断规则：FinalScore = max(0, min(3, RawScore))
- 龙虎榜偏好：近3日游资净买入>0，得+2分
  > 截断规则：FinalScore = max(0, min(2, RawScore))
> 注：龙虎榜T+1披露，**盘中无法获取**。盘中用「当日涨幅+换手率」代理（游资活跃标的通常高换手+高涨幅）。盘后通过Tushare top_inst统计近3日游资净买入。

【维度5】集合竞价情绪动能（15分）← V1.2修订（量纲修正+市场状态适配）
数据来源：Tushare `stk_auction` 接口（开盘竞价成交数据）+ `daily` 接口（昨日成交量）

- OpenGap（开盘跳空）× 市场状态乘数：
  > 市场状态判定规则（基于全市场涨跌家数+成交额）：
  - 牛市态：涨跌比>2.5 且 全市场成交额>20日均额1.2倍 → 乘数=1.3（高开是加速信号，放大加分）
  - 震荡态：涨跌比∈[0.8, 2.5] → 乘数=1.0（中性，原阈值不变）
  - 熊市态：涨跌比<0.8 或 成交额<20日均额0.7倍 → 乘数=0.6（高开是兑现/核按钮起点，缩小加分/放大扣分）
  > 乘数范围限定[0.5, 1.5]，防止极端值
  基础跳空评分（震荡态参考值，实际得分 = 基础分 × 市场乘数）：
  - 高开5-8%：基础+5分 → 牛市+6.5，震荡+5，熊市+3
  - 高开3-5%：基础+3分 → 牛市+3.9，震荡+3，熊市+1.8
  - 高开1-3%：基础+1分 → 牛市+1.3，震荡+1，熊市+0.6
  - 平开(-1~1%)：0分（不受乘数影响）
  - 低开1-3%：基础-2分 → 牛市-2（扣分不变），震荡-2，熊市-3（扣分放大×1.5）
  - 低开>3%：基础-4分 → 牛市-4，震荡-4，熊市-6
  - 高开≥8%：基础+2分 → 牛市+2.6，震荡+2，熊市+1.2（大幅高开仍有冲高回落风险，适度加分）
  > 截断规则：FinalScore = max(0, min(5, round(基础分 × 市场乘数)))

- CallVolRatio（竞价关注度）：竞价成交量/昨日成交量（量纲修正，V1.2）
  > 旧版量纲"竞价成交量/流通股本"已废弃（流通股本量纲下阈值≥5000%逻辑不通，实际值仅0.1~5%范围）
  > 新量纲"竞价量/昨日成交量"反映竞价相对于全天成交的活跃程度，实际值0.3~5.0范围
  - ≥3.0（竞价量达昨日全天3倍以上）：+5分（极高关注度，开盘前资金强力动员）
  - ≥1.5（竞价量达昨日全天1.5倍）：+3分（高关注度）
  - ≥0.5（竞价量达昨日全天半量）：+1分（较高关注度）
  > 截断规则：FinalScore = max(0, min(5, RawScore))

- 量比验证：竞价量比>5得+3分；>3得+1分（确认竞价活跃度非异常）
  > 截断规则：FinalScore = max(0, min(3, RawScore))

- 竞价成交额：竞价成交金额≥500万得+2分；≥100万得+1分（真金白银的参与度）
  > 截断规则：FinalScore = max(0, min(2, RawScore))

> 因子构建标准流程：原始数据 → 去极值(Winsorize 5%/95%) → 横截面分位数 → 信号输出
> 衰减控制：集合竞价因子半衰期<3个交易日，仅对当日开盘情绪有效
> 风险过滤：涨停/跌停股竞价量价失真，需结合开板状态判断；ST/新股/停牌股剔除

五、完整标准化数据字段清单（API对接标准）

【盘中实时数据（CDP/akshare）】
- 市场情绪类：limit_up_cnt, limit_down_cnt, board_break_rate, limit_up_premium_yd, max_continuity, turnover_ratio_mkt, advance_decline_ratio, promotion_rate_yd
- 题材情绪类：theme_heat_rank, theme_heat_idx, theme_cycle_tag, theme_net_inflow, theme_ul_cnt_trend
- 板块梯队类：sector_ul_cnt, sector_leader_height, sector_echelon_flag, sector_avg_ret_nonul, sector_divergence_ratio
- 个股人气类：popularity_rank, hist_ul_cnt_20d, turnover_ratio, intraday_activity_idx
- 集合竞价类：auction_open_gap, auction_call_vol_ratio(竞价量/昨日成交量), auction_volume_ratio, auction_amount, auction_price, auction_pre_close, yesterday_vol ← V1.2量纲修正
- 市场状态类：market_state(牛/震/熊), market_state_multiplier, mkt_advance_decline_ratio, mkt_total_amount, mkt_amount_20d_avg ← V1.2新增

【盘后历史数据（Tushare）】
- 市场情绪类：limit_up_cnt, limit_down_cnt, board_break_rate, limit_up_premium_yd, max_continuity
- 题材情绪类：theme_heat_rank, theme_heat_idx, theme_cycle_tag, theme_net_inflow
- 板块梯队类：sector_ul_cnt, sector_leader_height, sector_echelon_flag
- 个股人气类：popularity_rank, hist_ul_cnt_20d, turnover_ratio, dragon_tiger_net_buy
- 集合竞价类：stk_auction 接口字段 (ts_code, trade_date, vol, price, amount, pre_close, turnover_rate, volume_ratio, float_share) + daily 接口昨日成交量(yesterday_vol) ← V1.2量纲修正

注：
- 盘中字段通过CDP实时获取或akshare stock_fund_flow_individual 代理
- 盘后字段通过Tushare limit_list_d/limit_step/concept_detail/stk_auction 等接口获取
- 所有字段严禁使用未来函数，盘中用14:30/14:45快照
- stk_auction 数据在9:25~9:29分之间可获取当日集合竞价成交数据
