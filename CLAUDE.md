# 项目约束规则

## Agent 文档同步约束
- 修改主 agent 相关内容后，必须将修改同步到 `./docs/agent.md` 或者确保两份文档保持一致。
- 修改子 agent 相关内容后，必须将修改同步到 `./docs/agent-xxx.md` 或者确保两份文档保持一致
  - [资金面 agent 及策略设计](./docs/agent-fund-flow.md)
  - [情绪面 agent 及策略设计](./docs/agent-sentiment.md)
  - [技术面 agent 及策略设计](./docs/agent-technician.md)
  - [基本面 agent 及策略设计](./docs/agent-fundamental.md)

## 数据源获取约束
- 交易实时数据：
  - 涨速数据优先从 **requests+代理 东方财富API** 获取（push2.eastmoney.com f11字段），CDP+代理为备选，纯CDP为向后兼容方式
  - 其他实时数据（行情/资金流/板块等）优先从 **akshare** 获取，如果访问不通寻找 **tushare** 合适的接口替换
- 非实时数据（如历史行情、财务数据、基本面数据、指数成分等）优先从 **tushare** 获取，如果访问不通寻找 **akshare** 合适的接口替换
- 当优先数据源获取失败时，可降级使用备用数据源，但需在代码注释中标注降级原因
- 数据源获取接口必须编写单元测试，确保数据可以正常获取
- 东方财富API代理IP配置：`.env` 中 `PROXY_ENABLED=true` 启用动态代理(zdtps.com)，代理模块 `scripts/proxy_utils.py`

## Agent 策略文档和实现约束
- 必须校验子 agent 策略文档的逻辑一致性，不能出现重复描述和前后不一致的策略
- 策略的实现必须严格遵守策略文档，不能虚造和遗漏，实现完成必须有单测保证
- 拦截策略过于严格需要给出警告
- 策略优化文档先行原则： 文档先行 -> 策略/因子代码实现 -> 单测