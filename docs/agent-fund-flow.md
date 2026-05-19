==================================================
【资金面涨停预判Agent V1.0 量化实盘版】
（与基本面/技术面/情绪面模型完全对齐的统一架构）
> ⚠️ **数据源时效性**：本文档标注的Tushare接口均为T+1数据，仅适用于收盘复盘。盘中分析必须使用CDP实时数据。北向资金实时数据已停止披露，龙虎榜为T+1，盘中需用代理指标。
==================================================

一、角色定位与核心目标
- 定位：专注A股T+1~T+3资金驱动型涨停预判的智能分析Agent。
- 核心目标：筛选主力资金持续净流入、大单抢筹明确、游资/机构合力抱团、抛压极低的标的；剔除主力出货、大单砸盘、资金背离、散户接盘的假突破股。
- 边界纪律：仅依赖真实资金流水、Level2订单流、席位龙虎榜、北向/公募持仓变动、盘口承接数据；严禁引入任何技术指标、基本面财务或情绪题材变量。

二、量化打分模型与权重分配（总分100，四模统一口径）
1. 超大单主力净流入维度    权重 35分（涨停第一驱动力）
2. 龙虎榜机构游资维度      权重 25分（溢价核心）
3. 分时盘口资金抢筹维度    权重 20分（日内起爆信号）
4. 北向与聪明资金维度      权重 12分（持续性兜底）
5. 筹码抛压与资金锁仓维度  权重  8分（安全性过滤）

计分机制：
- 各维度按阈值累加得分，上限为权重分。
- 多资金共振判定：≥3个维度得分≥该维度权重的70%，且未触发一票否决，判定为高潜力。
- 潜力分级（与全系统统一标准）：
  ≥75分：高强度资金驱动涨停（是，隔日/连板潜力）
  55–74分：中等潜力（主力流入明确，结构健康）
  35–54分：低潜力（脉冲式流入，持续性弱）
  <35分 或触发否决：无潜力（剔除）

> ⚠️ 注意：早期版本阈值（70/50/30）已废弃，全系统统一采用75/55/35。

三、避雷一票否决规则（触发任意一条 → 涨停预测：否）
1. 主力持续流出：当日超大单/大单净流出，且近3日主力累计净流出＜-0.5%流通市值
2. 席位大额撤离：龙虎榜机构/知名游资单日净卖出＞净买入2倍（盘后）；盘中：大单持续净流出
3. 分时资金背离：股价拉升＞3%但分时资金净流入持续为负，或15分钟滑动相关系数＜-0.6
4. 纯散户博弈：主力净占比＜10%，无大资金控盘痕迹
5. 尾盘集中兑现：14:45后资金净流出占全天流出比例＞60%，且伴随主动卖单激增
> 注：否决规则优先级最高，触发后直接拦截，不参与后续打分。

四、五大资金维度 → 量化因子 + 硬性阈值（直接可编码回测）

【维度1】超大单主力净流入（35分）
- 规模阈值：当日超大单+大单净流入 ≥ 流通市值的0.3%，得+15分；＜0.1%扣15分
  > 截断规则：FinalScore = max(0, min(15, RawScore))
- 占比健康：主力净占比（超大单+大单）＞30%，得+10分
  > 截断规则：FinalScore = max(0, min(10, RawScore))
- 持续抢筹：近3日主力连续净流入，无单日中断，得+10分
  > 截断规则：FinalScore = max(0, min(10, RawScore))
- 负向过滤：中/小单大幅流入而主力流出（散户接盘特征），扣20分
  > 截断规则：FinalScore = max(0, min(35, RawScore))

【维度2】龙虎榜机构游资（25分）—— 盘中/盘后双方案

> 方案切换逻辑：IF trade_time < 15:00 THEN 盘中方案（大单代理）ELSE 盘后方案（Tushare龙虎榜）。权重不变。

盘后方案（Tushare top_list/top_inst）：
- 资金合力：机构专用+一线游资席位净买入合计＞3000万，得+12分
  > 截断规则：FinalScore = max(0, min(12, RawScore))
- 席位主导：单一知名游资/机构席位净买入占比＞40%，得+8分
  > 截断规则：FinalScore = max(0, min(8, RawScore))
- 结构健康：买入席位集中度高、卖出席位分散（买卖比＞1.5），得+5分
  > 截断规则：FinalScore = max(0, min(5, RawScore))
- 负向过滤：游资/机构集体大额卖出，或买盘极度分散（散户席位主导），扣15分
  > 截断规则：FinalScore = max(0, min(25, RawScore))

盘中方案（龙虎榜T+1不可用，改用大单代理）：
- 大单合力：超大单+大单净买入合计＞3000万，得+12分
  > 截断规则：FinalScore = max(0, min(12, RawScore))
- 资金主导：单一价位大单买入占比＞40%，得+8分
  > 截断规则：FinalScore = max(0, min(8, RawScore))
- 结构健康：买盘集中度高、卖盘分散（买卖比＞1.5），得+5分
  > 截断规则：FinalScore = max(0, min(5, RawScore))
- 负向过滤：大单持续净流出，或买盘极度分散，扣15分
  > 截断规则：FinalScore = max(0, min(25, RawScore))

【维度3】分时盘口资金抢筹（20分）

- 持续净流入：分时资金曲线全程在0轴上方，且14:30前未现深度回撤，得+10分
  > 截断规则：FinalScore = max(0, min(10, RawScore))
- 强承接：股价回调时资金不流出，盘口委买挂单/委卖压单比＞1.5，得+6分
  > 截断规则：FinalScore = max(0, min(6, RawScore))
- 脉冲/尾盘回流：盘中大额扫货（单笔＞流通市值0.05%）或尾盘回流净额＞全天流入30%，得+4分
  > 截断规则：FinalScore = max(0, min(4, RawScore))
- 负向过滤：拉升无量、下跌放量出逃，或盘口大单频繁撤单对倒，扣12分
  > 截断规则：FinalScore = max(0, min(20, RawScore))

【维度4】北向与聪明资金（12分）—— 盘中/盘后双方案

> 方案切换逻辑：IF trade_time < 15:00 THEN 盘中方案（大单代理）ELSE 盘后方案（Tushare hk_hold）。权重不变。

盘后方案（Tushare hk_hold）：
- 持续增持：当日北向净流入>0，且近5日累计增持>0，得+6分
  > 截断规则：FinalScore = max(0, min(6, RawScore))
- 筹码锁定：北向持仓占比稳步提升（Δ>0.05%），得+4分
  > 截断规则：FinalScore = max(0, min(4, RawScore))
- 机构共振：北向与公募/社保/ETF资金同步加仓，得+2分
  > 截断规则：FinalScore = max(0, min(2, RawScore))
- 负向过滤：北向连续2日减持或高频做T无沉淀，扣8分
  > 截断规则：FinalScore = max(0, min(12, RawScore))

盘中方案（北向实时已停，改用大单代理）：
- 大单持续流入：当日大单净流入>0，且近5日累计>0，得+6分
  > 截断规则：FinalScore = max(0, min(6, RawScore))
- 筹码锁定：大单持仓占比稳步提升（Δ>0.05%），得+4分
  > 截断规则：FinalScore = max(0, min(4, RawScore))
- 机构共振：大单与超大单同步加仓，得+2分
  > 截断规则：FinalScore = max(0, min(2, RawScore))
- 负向过滤：大单连续2日净流出，扣8分
  > 截断规则：FinalScore = max(0, min(12, RawScore))

【维度5】筹码抛压与资金锁仓（8分）
- 锁仓度高：主力持仓变动/散户持仓变动＞1.2，且近3日大单卖出占比递减，得+5分
  > 截断规则：FinalScore = max(0, min(5, RawScore))
- 抛压可控：阶段性获利盘兑现温和，无集中砸盘痕迹，得+3分
  > 截断规则：FinalScore = max(0, min(3, RawScore))
- 负向过滤：高位主力集中派发或散户疯狂接盘，扣8分
  > 截断规则：FinalScore = max(0, min(8, RawScore))

五、完整标准化数据字段清单（API对接标准）
【盘中实时数据（CDP）】
- 主力大单类：ul_lg_net_inflow, main_force_ratio, inflow_days_3d, md_sm_net_flow, inflow_to_float_cap_ratio
- 分时盘口类：intraday_fund_curve, support_ratio, pulse_vol, late_stage_flow_ratio, fund_price_divergence_corr
- 抛压锁仓类：main_vs_retail_chg, capital_lockup_index, sell_pressure_decay

【盘后历史数据（Tushare）】
- 主力大单类：ul_lg_net_inflow, main_force_ratio, inflow_days_3d, md_sm_net_flow, inflow_to_float_cap_ratio
- 龙虎榜类：lt_flag, inst_net_buy, hot_money_net_buy, buy_sell_concentration, top_seat_id
- 北向聪明类：northbound_net_buy, northbound_hold_chg_5d, hold_ratio_delta, smart_money_resonance_flag
- 分时盘口类：intraday_fund_curve, support_ratio, pulse_vol, late_stage_flow_ratio, fund_price_divergence_corr
- 抛压锁仓类：main_vs_retail_chg, capital_lockup_index, sell_pressure_decay, wash_trade_filter_flag

注：
- 盘中字段通过CDP实时获取（push2.eastmoney.com）
- 盘后字段通过Tushare moneyflow/top_list/hk_hold 等接口获取
- 所有字段严禁使用T日收盘价反推盘中资金指标


