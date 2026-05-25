#!/usr/bin/env python3
"""Send daily scan report to Feishu report group."""
import json
import os
import urllib.request
from dotenv import load_dotenv

load_dotenv('/root/maneki-agent/.env')

APP_ID = os.environ['FEISHU_APP_ID']
APP_SECRET = os.environ['FEISHU_APP_SECRET']
CHAT_ID = os.environ['FEISHU_CHAT_ID_REPORT']

# 1. Get tenant_access_token
data = json.dumps({'app_id': APP_ID, 'app_secret': APP_SECRET}).encode()
req = urllib.request.Request(
    'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
    data=data,
    headers={'Content-Type': 'application/json'}
)
resp = json.loads(urllib.request.urlopen(req).read())
token = resp['tenant_access_token']
print(f"Got token: {token[:10]}...")

# 2. Read the scan summary stats
with open('/root/maneki-agent/wiki/plays/limit-up/entities/20260525-扫描汇总.md') as f:
    content = f.read()

# Extract stats from the markdown
import re

total_stocks = int(re.search(r'扫描股票总数\s*\|\s*(\d+)', content).group(1))
avg_score = float(re.search(r'总分均值\s*\|\s*([\d.]+)', content).group(1))
dims = re.search(r'维度均分\s*\|\s*(.+?)$', content, re.MULTILINE).group(1)

star5 = int(re.search(r'⭐⭐⭐⭐⭐.*?\|\s*(\d+)', content).group(1))
star4 = int(re.search(r'⭐⭐⭐⭐.*?\|\s*(\d+)', content).group(1))
star3 = int(re.search(r'⭐⭐⭐.*?\|\s*(\d+)', content).group(1))
star0 = int(re.search(r'不评级.*?\|\s*(\d+)', content).group(1))

# Top 5
top5_lines = re.findall(r'\|\s*\d+\s*\|\s*(\d{6})\s*\|\s*([^|]+)\s*\|\s*([\d.]+)\s*\|', content)
top5 = top5_lines[:5]

# Push stats
pushed = int(re.search(r'去重推送股票\s*\|\s*(\d+)', content).group(1))
hits = int(re.search(r'实际涨停\s*\|\s*(\d+)', content).group(1))
hit_rate = float(re.search(r'推送命中率\s*\|\s*([\d.]+)%', content).group(1))

# Read the raw report for more data
with open('/root/maneki-agent/wiki/raw/reports/20260525.json') as f:
    report = json.load(f)

assert report['date'] == '20260525'

# Build the card
top5_str = '\n'.join([f'{i+1}. {row[1].strip()} ({row[0]}) — {row[2]}分' for i, row in enumerate(top5)])
hit_names = [d['name'] for d in report['hit_details']]

card_content = (
    f"📊 **涨停预测日报 — 2026-05-25**\n\n"
    f"━━━━━━━━━━━━━━━━━━\n\n"
    f"**📈 扫描概览**\n"
    f"• 扫描股票：**{total_stocks}** 只\n"
    f"• 总分均值：**{avg_score}**\n"
    f"• 维度均分：{dims}\n\n"
    f"**⭐ 星级分布**\n"
    f"• ⭐⭐⭐⭐⭐ (≥55)：{star5} 只 ({round(star5/total_stocks*100,1)}%)\n"
    f"• ⭐⭐⭐⭐ (≥45)：{star4} 只 ({round(star4/total_stocks*100,1)}%)\n"
    f"• ⭐⭐⭐ (≥35)：{star3} 只 ({round(star3/total_stocks*100,1)}%)\n"
    f"• 不评级 (<35)：{star0} 只 ({round(star0/total_stocks*100,1)}%)\n\n"
    f"**🏆 Top 5**\n{top5_str}\n\n"
    f"**🎯 推送表现**\n"
    f"• 推送股票：**{pushed}** 只\n"
    f"• 命中涨停：**{hits}** 只\n"
    f"• 命中率：**{hit_rate:.1f}%**\n\n"
    f"**✅ 命中涨停**\n"
    f"{', '.join(hit_names)}\n\n"
    f"📋 详情见 wiki → [[20260525-扫描汇总]]"
)

# 3. Send card message to report group
# Feishu card message
card_msg = {
    "receive_id": CHAT_ID,
    "msg_type": "interactive",
    "content": json.dumps({
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "📊 涨停预测日报 — 20260525"},
            "template": "blue"
        },
        "elements": [
            {"tag": "markdown", "content": f"**📈 扫描概览**\n• 扫描股票：**{total_stocks}** 只\n• 总分均值：**{avg_score}**\n• 维度均分：{dims}"},
            {"tag": "hr"},
            {"tag": "markdown", "content": f"**⭐ 星级分布**\n• ⭐⭐⭐⭐⭐ (≥55)：{star5} 只 ({round(star5/total_stocks*100,1)}%)\n• ⭐⭐⭐⭐ (≥45)：{star4} 只 ({round(star4/total_stocks*100,1)}%)\n• ⭐⭐⭐ (≥35)：{star3} 只 ({round(star3/total_stocks*100,1)}%)\n• 不评级 (<35)：{star0} 只 ({round(star0/total_stocks*100,1)}%)"},
            {"tag": "hr"},
            {"tag": "markdown", "content": f"**🏆 Top 5**\n{top5_str}"},
            {"tag": "hr"},
            {"tag": "markdown", "content": f"**🎯 推送表现**\n• 推送股票：**{pushed}** 只\n• 命中涨停：**{hits}** 只\n• 命中率：**{hit_rate:.1f}%**\n\n**✅ 命中涨停：** {', '.join(hit_names)}"},
            {"tag": "hr"},
            {"tag": "note", "elements": [{"tag": "plain_text", "content": "🕐 报告生成: 2026-05-25"}]}
        ]
    })
}

body = json.dumps(card_msg).encode('utf-8')
req2 = urllib.request.Request(
    f'https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id',
    data=body,
    headers={
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
)
resp2 = json.loads(urllib.request.urlopen(req2).read())
print(f"Send result: code={resp2.get('code')}, msg={resp2.get('msg')}")
if resp2.get('code') == 0:
    print("✅ Report sent successfully!")
else:
    print(f"❌ Failed: {json.dumps(resp2, indent=2, ensure_ascii=False)}")
