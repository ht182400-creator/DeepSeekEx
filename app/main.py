"""
DeepSeek Studio - FastAPI 后端主服务

功能:
- 配置管理(API Key / Token 界面填入,存服务端配置文件)
- 双 provider 流式对话(SSE)
- 会话/消息持久化(JSON 文件)
- 静态文件服务(前端 1:1 复刻 UI)
"""

import asyncio
import json
import logging
import logging.handlers
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from config import (
    CHAT_DB_FILE,
    CONFIG_DIR,
    CONFIG_FILE,
    DEFAULT_SETTINGS,
    HOST,
    LOG_BACKUP_COUNT,
    LOG_DIR,
    LOG_FILE,
    OFFICIAL_MODEL_FLASH,
    PORT,
)
from pow_solver import verify_test_vectors
from providers import ProviderError, clear_web_session, create_provider

# ==================== 日志配置 ====================
LOG_FORMAT = "[%(asctime)s.%(msecs)03d] %(levelname)-5s %(name)s:%(lineno)d  %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging() -> None:
    """配置日志:同时输出到控制台和文件,文件按天轮转"""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        # 目录创建失败不阻断启动,后续文件 handler 初始化会再给出告警
        logging.getLogger(__name__).warning("日志目录创建失败: %s", exc)

    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # 控制台
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    # 文件(轮转)
    try:
        file_handler = logging.handlers.TimedRotatingFileHandler(
            LOG_FILE, when="midnight", backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except Exception as exc:
        root.warning("文件日志初始化失败,仅使用控制台: %s", exc)


setup_logging()
logger = logging.getLogger(__name__)

# ==================== 应用初始化 ====================
app = FastAPI(title="HT182400", version="1.0.0")

# 配置文件目录
CONFIG_DIR.mkdir(parents=True, exist_ok=True)


# ==================== 配置存储 ====================
def load_settings() -> dict[str, Any]:
    """加载服务端配置,首次启动写入默认配置"""
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, encoding="utf-8") as f:
                saved = json.load(f)
            # 合并默认值,兼容旧配置缺字段
            merged = {**DEFAULT_SETTINGS, **saved}
            if "enhancements" in saved:
                saved_enh = saved["enhancements"]
                enh = dict(DEFAULT_SETTINGS["enhancements"])
                enh.update(saved_enh)
                # 旧字段名 context_meter 迁移到 context:
                # 需检查"用户保存的配置"而非合并后的 enh,否则默认值 context=True 会遮蔽旧字段,
                # 导致用户原本的 context_meter=False 设置丢失
                if "context" not in saved_enh and "context_meter" in saved_enh:
                    enh["context"] = saved_enh["context_meter"]
                enh.pop("context_meter", None)  # 移除旧字段,避免混存
                merged["enhancements"] = enh
            return merged
        # 首次启动写入默认配置
        save_settings(DEFAULT_SETTINGS)
        return dict(DEFAULT_SETTINGS)
    except Exception as exc:
        logger.error("加载配置失败: %s", exc, exc_info=True)
        return dict(DEFAULT_SETTINGS)


def _atomic_write_json(target: Path, data: Any) -> None:
    """
    原子写 JSON 文件:先写临时文件再 os.replace,避免写入中断导致文件损坏
    @param target 目标文件
    @param data 要写入的数据
    """
    tmp_file = target.with_suffix(target.suffix + ".tmp")
    try:
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_file, target)
    except Exception as exc:
        logger.error("原子写文件失败 %s: %s", target, exc, exc_info=True)
        try:
            if tmp_file.exists():
                tmp_file.unlink()
        except Exception as cleanup_exc:
            logger.warning("清理临时文件失败: %s", cleanup_exc)
        raise


def save_settings(settings: dict[str, Any]) -> None:
    """保存配置到服务端文件(不写入代码/文档)"""
    _atomic_write_json(CONFIG_FILE, settings)
    logger.info("配置已保存")


def load_chats() -> list[dict[str, Any]]:
    """加载会话数据"""
    try:
        if CHAT_DB_FILE.exists():
            with open(CHAT_DB_FILE, encoding="utf-8") as f:
                return json.load(f)
        return []
    except Exception as exc:
        logger.error("加载会话失败: %s", exc, exc_info=True)
        return []


def save_chats(chats: list[dict[str, Any]]) -> None:
    """保存会话数据(原子写,失败抛异常让 API 返回错误而非假成功)"""
    _atomic_write_json(CHAT_DB_FILE, chats)


# ==================== API 路由:配置 ====================
@app.get("/api/settings")
async def get_settings():
    """获取当前配置(敏感字段脱敏返回)"""
    settings = load_settings()
    safe = dict(settings)
    # 脱敏:只显示是否存在,不返回明文
    safe["api_key_set"] = bool(settings.get("api_key"))
    safe["web_token_set"] = bool(settings.get("web_token"))
    safe["api_key"] = ""
    safe["web_token"] = ""  # 脱敏返回固定空值，避免明文外泄
    return safe


@app.post("/api/settings")
async def update_settings(request: Request):
    """更新配置(API Key / Token / provider 等)"""
    try:
        body = await request.json()
        settings = load_settings()

        # 更新允许修改的字段;空字符串视为"不更新",避免误清空已有配置
        for key in ["provider", "api_key", "web_token", "model", "thinking_enabled", "search_enabled"]:
            if key not in body:
                continue
            value = body[key]
            if isinstance(value, str) and not value.strip():
                continue
            settings[key] = value

        if "enhancements" in body:
            settings["enhancements"] = {**settings.get("enhancements", {}), **body["enhancements"]}

        save_settings(settings)
        return {"ok": True, "message": "配置已保存"}
    except Exception as exc:
        logger.error("更新配置异常: %s", exc, exc_info=True)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@app.post("/api/validate")
async def validate_provider(request: Request):
    """验证 provider 凭据是否有效"""
    try:
        body = await request.json()
        provider_type = body.get("provider", "official")
        api_key = body.get("api_key", "")
        web_token = body.get("web_token", "")

        # 请求未带凭据时,使用服务端已保存的配置
        # (设置页输入框为空表示"验证当前生效的配置",不是"用空凭据验证")
        if not api_key or not web_token:
            saved = load_settings()
            if not api_key:
                api_key = saved.get("api_key", "")
            if not web_token:
                web_token = saved.get("web_token", "")

        provider = create_provider(provider_type, api_key, web_token)
        ok, message = await provider.validate()
        return {"ok": ok, "message": message}
    except ProviderError as exc:
        return {"ok": False, "message": str(exc)}
    except Exception as exc:
        logger.error("验证异常: %s", exc, exc_info=True)
        return {"ok": False, "message": f"验证异常: {exc}"}


# ==================== API 路由:会话 ====================
@app.get("/api/chats")
async def get_chats():
    """获取所有会话"""
    return load_chats()


@app.post("/api/chats")
async def create_chat(request: Request):
    """创建新会话"""
    try:
        body = await request.json()
        chats = load_chats()
        chat = {
            "id": str(uuid.uuid4()),
            "title": body.get("title", "新对话"),
            "messages": [],
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "starred": False,
            "tag": "default",
        }
        chats.insert(0, chat)
        save_chats(chats)
        return chat
    except Exception as exc:
        logger.error("创建会话异常: %s", exc, exc_info=True)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.put("/api/chats/{chat_id}")
async def update_chat(chat_id: str, request: Request):
    """更新会话(标题、消息、收藏等)"""
    try:
        body = await request.json()
        chats = load_chats()
        for chat in chats:
            if chat["id"] == chat_id:
                for key in ["title", "messages", "starred", "tag"]:
                    if key in body:
                        chat[key] = body[key]
                chat["updated_at"] = datetime.now().isoformat()
                save_chats(chats)
                return chat
        return JSONResponse({"error": "会话不存在"}, status_code=404)
    except Exception as exc:
        logger.error("更新会话异常: %s", exc, exc_info=True)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.delete("/api/chats/{chat_id}")
async def delete_chat(chat_id: str):
    """删除会话"""
    try:
        chats = load_chats()
        chats = [c for c in chats if c.get("id") != chat_id]
        save_chats(chats)
        clear_web_session(chat_id)
        return {"ok": True}
    except Exception as exc:
        logger.error("删除会话异常: %s", exc, exc_info=True)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


# ==================== API 路由:流式对话 ====================
@app.post("/api/chat/stream")
async def stream_chat(request: Request):
    """
    流式对话接口(SSE)
    根据当前 provider 配置,转发到官方 API 或网页私有接口
    """
    try:
        body = await request.json()
        messages = body.get("messages", [])
        settings = load_settings()

        # 允许请求覆盖 provider 配置
        provider_type = body.get("provider", settings.get("provider", "official"))
        thinking = body.get("thinking", settings.get("thinking_enabled", False))
        search = body.get("search", settings.get("search_enabled", False))
        model = body.get("model", settings.get("model", OFFICIAL_MODEL_FLASH))
        # 网页端多轮上下文依赖 chat_id 复用会话(官方端忽略)
        chat_id = body.get("chat_id", "")

        if not messages:
            return JSONResponse({"error": "消息不能为空"}, status_code=400)

        provider = create_provider(
            provider_type,
            settings.get("api_key", ""),
            settings.get("web_token", ""),
        )

        logger.info(
            "流式对话开始: provider=%s, thinking=%s, search=%s, messages=%d",
            provider_type, thinking, search, len(messages),
        )

        async def event_generator():
            """SSE 事件生成器"""
            try:
                async for event in provider.stream_chat(messages, thinking, search, model, chat_id):
                    # 转发事件为 SSE 格式
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except Exception as exc:
                logger.error("流式生成异常: %s", exc, exc_info=True)
                yield f"data: {json.dumps({'type': 'error', 'text': str(exc)}, ensure_ascii=False)}\n\n"
            finally:
                yield "data: [DONE]\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    except Exception as exc:
        logger.error("流式对话请求异常: %s", exc, exc_info=True)
        return JSONResponse({"error": str(exc)}, status_code=500)


# ==================== 工具接口 ====================
@app.get("/api/health")
async def health():
    """健康检查"""
    return {"status": "ok", "service": "DeepSeek Studio"}


@app.post("/api/pow/verify")
async def pow_verify():
    """验证 PoW 哈希实现是否正确(开发调试用)"""
    ok = await asyncio.to_thread(verify_test_vectors)
    return {"ok": ok}


# ==================== 静态文件服务(前端) ====================
FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"


@app.get("/")
async def index():
    """首页"""
    return FileResponse(FRONTEND_DIR / "index.html")


# 挂载静态资源目录
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


# ==================== 启动入口 ====================
if __name__ == "__main__":
    import uvicorn
    logger.info("DeepSeek Studio 启动: http://%s:%s", HOST, PORT)
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
