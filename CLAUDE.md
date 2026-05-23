# 项目约束规则

## 项目结构

```
maneki-agent/
├── plays/                    ← 各玩法（垂直隔离，自包含）
│   ├── limit_up/             ← 涨停预测（现有玩法）
│   │   ├── pipeline.py       ← 主流程
│   │   ├── agents/           ← 评分维度
│   │   ├── review.py         ← 复盘
│   │   ├── optimize.py       ← 优化器
│   │   ├── health_patrol.py  ← 巡检
│   │   ├── verify.py         ← 验证
│   │   └── data/             ← 全部数据
│   └── xxx/                  ← 新玩法（按此模板扩展）
├── feishu_bot/               ← 统一飞书入口（路由到各play）
│   └── handler.py            ← 消息处理 + wiki查询
├── wiki/                     ← 共享知识库
│   ├── concepts/             ← 跨玩法通用知识
│   ├── plays/xxx/entities/   ← 玩法专属数据
│   └── compile.py            ← 编译脚本
├── scripts/
│   └── proxy_utils.py        ← 共享：代理池（勿改）
├── docs/                     ← 文档
└── CLAUDE.md                 ← 本文件
```

## 新增玩法扩展规范

### 1. 目录结构

新建 `plays/新玩法名/`，必须包含：

```
plays/新玩法名/
├── __init__.py
├── pipeline.py       ← 主流程（必要）
├── agents/           ← 评分维度（必要，至少1个）
│   ├── __init__.py
│   └── xxx_agent.py
├── data/             ← 数据目录（必要）
│   └── (analysis/ signals/ pushed/ 等子目录按需创建)
└── review.py         ← 复盘（可选）
```

### 2. 评分 Agent 签名规范

所有评分函数的输入输出必须统一：

```python
def score_xxx(code: str) -> tuple[int | float, str]:
    """返回 (分数, 理由简述)"""
```

- `code`: 带后缀的股票代码，如 `"000001.SZ"` 或 `"600519.SH"`
- 返回 `(score, reason)`，其中 score 为 0-100 数值，reason 为字符串

### 3. 数据源约束

- 实时数据：优先 **requests+代理 东方财富API**（push2.eastmoney.com）
- 非实时数据：优先 **tushare** 获取
- 代理模块统一使用 `scripts/proxy_utils.py`
- 代理IP配置：`.env` 中 `PROXY_ENABLED=true`

### 4. Pipeline 主流程规范

```python
def main():
    # 1. 扫描获取候选股
    candidates = scan_surge()
    
    # 2. 多维度并行评分
    results = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(score_xxx, code): dim for dim, fn in funcs.items()}
        for future in as_completed(futures):
            results.append(...)
    
    # 3. 聚合排序
    # 4. 推送 / 保存
```

### 5. 飞书Bot路由约束

新增玩法需要在 `feishu_bot/handler.py` 中注册路由：

```python
# 在 parse_stock_codes 和 _query_wiki 之间添加路由逻辑
# 例如：检查消息中是否包含新玩法关键词，路由到对应 pipeline
```

### 6. 知识库同步

- 跨玩法通用知识 → `wiki/concepts/`
- 玩法专属数据 → `wiki/plays/新玩法名/entities/`
- wiki compile 脚本需同步更新以支持新玩法

## 代码修改约束

- **scripts/proxy_utils.py** 是共享基础设施，修改前必须确认不影响其他玩法
- **feishu_bot/handler.py** 是统一入口，修改路由逻辑时确保不破坏现有玩法
- 新增玩法时优先新建 `plays/xxx/` 目录，不修改现有玩法代码

## 数据源获取约束

- 涨速数据优先从 **requests+代理 东方财富API** 获取（push2.eastmoney.com f11字段）
- 其他实时数据（行情/资金流/板块等）优先从 Eastmoney 获取，访问不通找 tushare 替换
- 非实时数据（历史行情、财务数据、基本面数据等）优先从 **tushare** 获取
- 数据源获取接口必须编写单元测试

## 文档先行原则

- 所有改动先更新 `docs/` 或本文件 → 用户审核 → 再改代码
- 新增玩法必须先写该玩法的设计说明文档
- 策略优化：文档先行 → 策略/因子代码实现 → 单测
