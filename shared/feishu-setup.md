# 飞书 Webhook 配置

## 创建飞书机器人

1. 打开飞书群聊 -> 设置 -> 群机器人 -> 添加机器人 -> 自定义机器人
2. 复制 Webhook URL
3. (可选) 设置签名密钥，启用签名验证

## 环境变量

| 变量 | 说明 | 示例 |
|---|---|---|
| FEISHU_WEBHOOK_URL | 涨停信号推送地址 | https://open.feishu.cn/open-apis/bot/v2/hook/xxx |
| FEISHU_REVIEW_WEBHOOK_URL | 复盘报告推送地址 | https://open.feishu.cn/open-apis/bot/v2/hook/yyy |
| FEISHU_SIGN_SECRET | 签名密钥(可选) | sec_xxx |

注意: 信号和复盘可以用同一个webhook，也可以分开到不同的群。

## 消息格式

飞书机器人支持以下消息类型:
- text: 纯文本
- post: 富文本
- interactive: 交互卡片 (推荐)

本系统使用 **interactive 交互卡片** 格式，支持:
- 彩色 Header
- Markdown 表格
- 操作按钮

详见: templates/feishu-notification-templates.md

## 测试 Webhook

```bash
curl -X POST "$FEISHU_WEBHOOK_URL" \
  -H "Content-Type: application/json" \
  -d '{
    "msg_type": "text",
    "content": {
      "text": "涨停预测系统测试消息"
    }
  }'
```

## 签名验证 (可选)

如果启用了签名密钥:

```python
import time
import hmac
import hashlib
import base64

def gen_sign(secret):
    timestamp = str(int(time.time()))
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256
    ).digest()
    sign = base64.b64encode(hmac_code).decode("utf-8")
    return timestamp, sign
```

在请求体中添加:

```json
{
  "timestamp": "<timestamp>",
  "sign": "<sign>",
  "msg_type": "...",
  "content": {...}
}
```

## 通知策略

| 场景 | Webhook | 频率 |
|---|---|---|
| 盘中涨停信号 | FEISHU_WEBHOOK_URL | 每10分钟(有信号时) |
| 收盘复盘报告 | FEISHU_REVIEW_WEBHOOK_URL | 每日15:30 |
| 系统异常告警 | FEISHU_WEBHOOK_URL | 异常发生时 |

## 故障处理

- 发送失败: 重试3次，间隔5秒
- 全部失败: 记录到本地日志 /srv/zt-team-leader/data/logs/notification-failures.log
- Webhook失效: 需人工重新配置