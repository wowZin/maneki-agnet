---
name: zt-startup
description: 启动涨停预测 Agent Team — 创建定时 cron 任务、验证 REST API 和飞书连通性、开始盘中扫描。下次说"启动涨停预测"或"启动maneki"即可触发。
version: 2.0.0
---

# ZT Startup — 涨停预测系统启动

一键启动涨停预测 Agent Team，自动创建盘中扫描和收盘复盘的 cron 任务。

## 数据源说明（重要）

| 场景 | 数据源 | 原因 |
|------|--------|------|
| 盘中扫描 | 东方财富 CDP | 实时涨速、分钟级行情 |
| 盘中分析 | 东方财富 CDP | 当日实时数据，Tushare盘中无数据 |
| 收盘复盘 | Tushare REST API | 历史数据完整，收盘后更新 |

**为什么不用 Tushare 盘中分析？**
- Tushare daily/bak_daily/moneyflow 等接口都是 **T+1 更新**，收盘后才入库
- 盘中调用 daily 接口返回的是前一天数据，分析结论会出错
- 例如：5月18日盘中扫描，用 Tushare daily 会返回 5月15日数据

**为什么不用 MCP？**
- Tushare MCP 连接成功但调用工具时报"需要提供token"
- REST API 直接调用稳定可靠

## 前置检查

1. **验证 Tushare REST API**
   ```bash
   curl -s -X POST "http://api.tushare.pro" \
     -H "Content-Type: application/json" \
     -d '{"api_name":"trade_cal","token":"YOUR_TOKEN","params":{"exchange":"SSE","start_date":"20260518","end_date":"20260518"}}' | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['items'][0])"
   ```
   - 应返回 `['SSE', '20260518', 1, '20260515']`（is_open=1 表示交易日）

2. **验证 Chrome CDP**
   - Chrome 需要以 CDP 模式启动：
   ```bash
   /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
     --remote-debugging-port=9222 \
     --remote-allow-origins=* \
     --user-data-dir=/tmp/chrome-cdp-profile
   ```
   - 访问 http://localhost:9222/json/list 应返回页面列表

3. **验证环境变量**
   - 检查 `.env` 文件中 `TUSHARE_TOKEN` 是否有值
   - 检查飞书配置（可选，无则跳过推送）

4. **检查已有 cron 任务**
   - 运行 `hermes cron list`，查看是否已有 zt 相关任务
   - 如果已有，询问用户是否要重建

## 启动步骤

### Step 1: 创建盘中扫描 cron

工作日 9:00-15:00 每10分钟扫描涨速前100股票，分发给4个子Agent分析，聚合后推送飞书。

```
cronjob action='create'
  name: zt-surge-scan
  schedule: "*/10 9-14 * * 1-5"
  deliver: origin
  prompt: |
    涨停预测盘中扫描任务。请执行以下流程：

    **前置检查 - 非交易日直接退出**

    1. 用 Tushare REST API 查询交易日历：
       ```python
       from hermes_tools import terminal
       import json
       token = "ebba208f5d60f9e86a1fcb39cf6dad5dca63c5288e82637ad59c5ac7"
       today = "YYYYMMDD"  # 替换为今天日期
       result = terminal(command=f'''curl -s -X POST "http://api.tushare.pro" -H "Content-Type: application/json" -d '{{"api_name":"trade_cal","token":"{token}","params":{{"exchange":"SSE","start_date":"{today}","end_date":"{today}"}}}}' | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['data']['items'][0][2] if d['data']['items'] else 0)"''')
       is_open = int(result.get("output", "0").strip())
       if is_open != 1:
           print("今日非交易日，跳过扫描")
           return
       ```

    **Step 1: 获取涨速Top100股票（Chrome CDP + 东方财富API）**

    运行 scripts/scan_cdp.py 获取实时涨速数据：
    ```bash
    python3 /Users/zhangying/projects/study/maneki-agent/scripts/scan_cdp.py
    ```

    输出文件：`/Users/zhangying/projects/study/maneki-agent/data/signals/{date}_{time}.json`

    数据字段：代码、名称、涨幅%、5分钟涨速%、最新价、成交额、量比

    **Step 2: 对Top100股票进行多维度分析（并行）**

    用 delegate_task 并行分发给4个子Agent，每个分析5个维度：
    
    ```python
    from hermes_tools import delegate_task
    tasks = [
      {"goal": f"基本面分析: {stock['代码']} {stock['名称']}", "context": f"实时数据: {stock}", "skills": ["zt-fundamental-analysis"]},
      {"goal": f"技术面分析: {stock['代码']} {stock['名称']}", "context": f"实时数据: {stock}", "skills": ["zt-technical-analysis"]},
      {"goal": f"资金面分析: {stock['代码']} {stock['名称']}", "context": f"实时数据: {stock}", "skills": ["zt-fund-flow-analysis"]},
      {"goal": f"情绪面分析: {stock['代码']} {stock['名称']}", "context": f"实时数据: {stock}", "skills": ["zt-sentiment-analysis"]},
    ]
    results = delegate_task(tasks=tasks)  # 并行执行，max_concurrent_children=10
    ```

    注意：分析使用 CDP 实时数据，不依赖 Tushare daily（T+1滞后）

    **Step 3: 聚合评分**

    收集4个维度的评分，按权重加权聚合（默认权重=1）：
    置信度 = Σ(score_i × weight_i) / Σ(weight_i)

    **Step 4: 保存分析结果**

    将分析结果保存到 `/Users/zhangying/projects/study/maneki-agent/data/analysis/{date}_{time}.json`

    字段包括：扫描时间、数据日期（标注为CDP实时）、股票列表、各维度评分、综合置信度、支撑逻辑、风险点

    **Step 5: 推送逻辑**

    - 如果有置信度 > 50% 的股票：推送置信度 > 50% 的股票列表
    - 如果没有置信度 > 50% 的股票：推送置信度排名前10的股票
    - 推送字段：序号、股票名称、参与预测的agent、综合置信分
    - 全量数据已保存到本地文件

  skills:
    - zt-fundamental-analysis
    - zt-technical-analysis
    - zt-fund-flow-analysis
    - zt-sentiment-analysis
  workdir: /Users/zhangying/projects/study/maneki-agent
```

### Step 2: 创建收盘复盘 cron

工作日 16:00 自动复盘，对比预测结果与真实涨停，评估各子Agent准确率。

```
cronjob action='create'
  name: zt-daily-review
  schedule: "0 16 * * 1-5"
  deliver: origin
  prompt: |
    涨停预测收盘复盘任务。请执行以下流程：

    **前置检查 - 非交易日直接退出**

    用 Tushare REST API 查询交易日历，非交易日直接返回。

    **交易日期间执行以下流程：**

    1. 读取今日信号文件：
       - data/signals/{date}_*.json — 扫描数据
       - data/analysis/{date}_*.json — 分析结果

    2. 用 Tushare REST API 获取当日真实涨停数据（收盘后已更新）：
       ```python
       # 获取涨停股票列表
       curl -X POST "http://api.tushare.pro" -d '{
         "api_name": "limit_list_d",
         "token": "YOUR_TOKEN",
         "params": {"trade_date": "YYYYMMDD", "limit_type": "U"}
       }'
       
       # 获取涨跌停价格
       curl -X POST "http://api.tushare.pro" -d '{
         "api_name": "stk_limit",
         "token": "YOUR_TOKEN",
         "params": {"trade_date": "YYYYMMDD"}
       }'
       ```

    3. 对每只预测股票判定结果：
       - 命中涨停：达到涨停价且封住
       - 涨停但炸板：达到涨停价但未封住
       - 接近涨停：涨幅>7%但未达涨停价
       - 未命中：无显著涨幅

    4. 计算各子Agent鉴别力，生成复盘报告
    5. 通过飞书推送复盘报告

  skills:
    - zt-review-engine
  workdir: /Users/zhangying/projects/study/maneki-agent
```

### Step 3: 验证任务已创建

- 运行 `hermes cron list`，确认两个任务都在列
- 手动触发验证：`cronjob action='run' job_id=<zt-surge-scan的ID>`

### Step 4: 告知用户状态

向用户报告：
- ✅/❌ Tushare REST API 连通性
- ✅/❌ Chrome CDP 连通性
- ✅/❌ 飞书配置状态
- ✅/❌ 盘中扫描 cron 已创建
- ✅/❌ 收盘复盘 cron 已创建
- 已优化：非交易日自动跳过，不会空跑

## 数据保存路径

| 类型 | 路径格式 | 示例 |
|------|----------|------|
| 扫描数据 | data/signals/{date}_{time}.json | data/signals/20260518_093000.json |
| 分析结果 | data/analysis/{date}_{time}.json | data/analysis/20260518_093500.json |

## 管理命令

| 操作 | 命令 |
|------|------|
| 查看任务 | `hermes cron list` |
| 手动触发 | `cronjob action='run' job_id=<id>` |
| 暂停 | `cronjob action='pause' job_id=<id>` |
| 恢复 | `cronjob action='resume' job_id=<id>` |
| 删除 | `cronjob action='remove' job_id=<id>` |

## 停止系统

用户说"停止涨停预测"或"停止maneki"时：
1. `cronjob action='pause' job_id=<zt-surge-scan的ID>`
2. `cronjob action='pause' job_id=<zt-daily-review的ID>`
3. 报告已暂停

## Pitfalls

- **Tushare daily 数据 T+1 滞后**：盘中不能用 daily/bak_daily/moneyflow，必须用 CDP 实时数据
- **MCP token 认证失败**：改用 REST API 直接调用
- **Chrome CDP 需要独立 profile**：必须指定 `--user-data-dir=/tmp/chrome-cdp-profile`
- **CDP 需要先打开东方财富页面**：否则 API 请求会 "Failed to fetch"
- **过滤北交所**：正则增加 `8|4|920` 前缀
- **子Agent并行**：用 `tasks` 数组一次传多个任务，不是分开调用
- **数据保存路径区分**：扫描放 signals/，分析放 analysis/
