"""
端到端验证:一次极短对话确认 SSE 正文不再截断
仅发送 "hi",流量极小;结果写入带时间戳日志
用法: python verify_e2e.py
"""
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import httpx

# 配置常量:端点、测试消息、超时、日志
BASE_URL = "http://127.0.0.1:20000"
CHAT_ENDPOINT = f"{BASE_URL}/api/chat/stream"
TEST_MESSAGE = "hi"
REQUEST_TIMEOUT = 90
# 正文短于此长度视为疑似截断("我无法"仅 3 字)
MIN_CONTENT_LEN = 6
LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_FORMAT = "[%(asctime)s.%(msecs)03d] %(levelname)-5s %(name)s:%(lineno)d  %(message)s"


def setup_logger():
    """配置验证日志:控制台 + 带时间戳文件,文件初始化失败不影响主流程"""
    log = logging.getLogger("e2e_verify")
    log.setLevel(logging.INFO)
    log.handlers.clear()
    fmt = logging.Formatter(LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_file = LOG_DIR / f"e2e_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        log.addHandler(fh)
    except Exception as exc:
        # 日志文件创建失败不阻断验证,仍保留控制台输出
        log.warning("测试日志文件初始化失败: %s", exc)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    return log


log = setup_logger()


def run_verify():
    """发送一次极短对话,收集 SSE 事件并判定正文是否完整"""
    contents = []
    thinkings = []
    errors = []
    try:
        with httpx.stream(
            "POST",
            CHAT_ENDPOINT,
            json={
                "messages": [{"role": "user", "content": TEST_MESSAGE}],
                "thinking": False,
                "search": False,
            },
            timeout=REQUEST_TIMEOUT,
        ) as resp:
            if resp.status_code != 200:
                log.error("HTTP %s: %s", resp.status_code, resp.read()[:200])
                return False
            for line in resp.iter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    event = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                etype = event.get("type")
                if etype == "content":
                    contents.append(event.get("text", ""))
                elif etype == "thinking":
                    thinkings.append(event.get("text", ""))
                elif etype == "error":
                    errors.append(event.get("text", ""))
                    log.error("收到错误事件: %s", event.get("text"))
    except Exception as exc:
        log.error("端到端验证异常: %s", exc, exc_info=True)
        return False

    full = "".join(contents)
    log.info("正文事件数=%d, 正文长度=%d", len(contents), len(full))
    log.info("思考事件数=%d, 错误事件数=%d", len(thinkings), len(errors))
    log.info("正文内容预览: %s", repr(full[:300]))
    if errors:
        log.error("[FAIL] 收到错误事件")
        return False
    if len(full) < MIN_CONTENT_LEN:
        log.error("[FAIL] 正文过短,疑似仍被截断")
        return False
    log.info("[PASS] 正文完整输出,未出现截断")
    return True


if __name__ == "__main__":
    sys.exit(0 if run_verify() else 1)
