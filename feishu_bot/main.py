"""飞书 Bot 回调服务 — FastAPI 入口"""

import asyncio
import logging
import sys
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from feishu_bot.handler import handle_message_event

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("feishu_bot")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🟢 Feishu Bot 服务启动")
    # 代理预热跳过（盘后代理不稳定），首次请求时惰性加载
    yield
    logger.info("🔴 Feishu Bot 服务停止")


app = FastAPI(title="Maneki Feishu Bot", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "maneki-feishu-bot"}


@app.post("/feishu/callback")
async def feishu_callback(request: Request):
    body = await request.json()
    logger.debug(f"回调: {body.get('type') or body.get('header',{}).get('event_type','?')}")

    # url_verification
    if body.get("type") == "url_verification":
        return {"challenge": body["challenge"]}

    # 消息事件
    event_type = body.get("header", {}).get("event_type", "")
    if event_type == "im.message.receive_v1":
        asyncio.create_task(handle_message_event(body.get("event", {})))
        return JSONResponse(content={})

    return JSONResponse(content={})
