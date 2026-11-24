"""
双 Provider 后端模块
- OfficialProvider: 调用 platform.deepseek.com 官方 API(需要 API Key)
- WebProvider: 调用 chat.deepseek.com 网页私有接口(需要 userToken,PoW 求解)

两个 provider 都提供统一的 stream_chat 异步生成器接口,产出 SSE 事件字典
"""

import asyncio
import base64
import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from config import (
    DEFAULT_USER_AGENT,
    HTTP_CONNECT_TIMEOUT,
    HTTP_STATUS_OK,
    HTTP_STATUS_UNAUTHORIZED,
    HTTP_TIMEOUT,
    OFFICIAL_API_BASE,
    OFFICIAL_CHAT_ENDPOINT,
    OFFICIAL_MODEL_FLASH,
    POW_TARGET_PATH,
    WEB_API_BASE,
    WEB_COMPLETION_PATH,
    WEB_CREATE_SESSION_PATH,
    WEB_CURRENT_USER_PATH,
    WEB_POW_CHALLENGE_PATH,
)
from pow_solver import solve_pow

logger = logging.getLogger(__name__)

# SSE patch 原始内容日志预览长度,避免单个事件刷屏
LOG_PATCH_PREVIEW_LEN = 500
# 错误响应体/非 JSON 事件日志截断长度,避免日志过大
LOG_ERROR_PREVIEW_LEN = 200

# 网页端多轮会话存储: chat_id -> {"session_id": str, "last_message_id": int}
# 网页端协议靠 chat_session_id + parent_message_id 串接上下文,每轮新建会话会丢失记忆
# 用字典按前端会话 ID 隔离,进程重启后清空(降级为单轮,不影响可用性)
WEB_SESSION_STORE: dict[str, dict[str, Any]] = {}

# 网页端会话存储单条最大保留轮次(超过后重置,避免无限增长)
WEB_SESSION_MAX_ROUNDS = 200


class ProviderError(Exception):
    """Provider 调用异常"""


class BaseProvider:
    """Provider 基类,定义统一接口"""

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        thinking: bool = False,
        search: bool = False,
        model: str = OFFICIAL_MODEL_FLASH,
        chat_id: str = "",
    ) -> AsyncGenerator[dict[str, Any]]:
        """流式对话,子类必须实现"""
        raise NotImplementedError

    async def validate(self) -> tuple:
        """验证凭据是否有效,返回 (bool, message)"""
        raise NotImplementedError


class OfficialProvider(BaseProvider):
    """官方 DeepSeek API Provider(OpenAI 兼容格式)"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.timeout = httpx.Timeout(HTTP_TIMEOUT, connect=HTTP_CONNECT_TIMEOUT)

    async def validate(self) -> tuple:
        """通过请求模型列表验证 Key"""
        if not self.api_key or not self.api_key.strip():
            return False, "请先填入 API Key 再验证"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    f"{OFFICIAL_API_BASE}/models",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                if resp.status_code == HTTP_STATUS_OK:
                    return True, "官方 API Key 有效"
                if resp.status_code == HTTP_STATUS_UNAUTHORIZED:
                    return False, "API Key 无效或已过期"
                return False, f"验证失败: HTTP {resp.status_code}"
        except Exception as exc:
            logger.error("官方 API 验证异常: %s", exc, exc_info=True)
            return False, f"验证异常: {exc}"

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        thinking: bool = False,
        search: bool = False,
        model: str = OFFICIAL_MODEL_FLASH,
        chat_id: str = "",
    ) -> AsyncGenerator[dict[str, Any]]:
        """
        调用官方 Chat Completions API,解析 SSE 流式响应(chat_id 官方模式忽略)
        产出事件:{"type": "thinking"|"content"|"done"|"error", "text": str}
        """
        if not self.api_key:
            yield {"type": "error", "text": "未配置 API Key,请在设置中填入"}
            return

        # 构造请求体
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        if thinking:
            payload["thinking"] = {"type": "enabled"}
        if search:
            # 官方 API 的联网搜索工具
            payload["tools"] = [{"type": "deepseek_web_search", "name": "deepseek_web_search"}]

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        logger.debug("官方 API 请求: model=%s, thinking=%s, search=%s", model, thinking, search)

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client, client.stream(
                "POST", OFFICIAL_CHAT_ENDPOINT, json=payload, headers=headers
            ) as response:
                if response.status_code != HTTP_STATUS_OK:
                    body = await response.aread()
                    error_msg = self._parse_error(body)
                    logger.error("官方 API 错误: HTTP %s - %s", response.status_code, error_msg)
                    yield {"type": "error", "text": error_msg}
                    return

                # 解析 SSE: data: {...}\n\n
                buffer = ""
                async for chunk in response.aiter_text():
                    buffer += chunk
                    while "\n\n" in buffer:
                        event, buffer = buffer.split("\n\n", 1)
                        parsed = self._parse_sse_event(event)
                        if parsed:
                            yield parsed

                # 处理残留 buffer
                if buffer.strip():
                    parsed = self._parse_sse_event(buffer)
                    if parsed:
                        yield parsed

        except httpx.TimeoutException:
            logger.error("官方 API 请求超时")
            yield {"type": "error", "text": "请求超时,请稍后重试"}
        except Exception as exc:
            logger.error("官方 API 调用异常: %s", exc, exc_info=True)
            yield {"type": "error", "text": f"调用异常: {exc}"}

    def _parse_sse_event(self, event: str) -> dict[str, Any] | None:
        """解析单个 SSE 事件"""
        try:
            data_line = None
            for line in event.split("\n"):
                if line.startswith("data:"):
                    data_line = line[5:].strip()
            if not data_line or data_line == "[DONE]":
                return None

            data = json.loads(data_line)

            # 处理 Anthropic 格式(如果用了 anthropic endpoint)
            if "type" in data and "content_block_delta" in data["type"]:
                delta = data.get("delta", {})
                if delta.get("type") == "thinking_delta":
                    return {"type": "thinking", "text": delta.get("thinking", "")}
                elif delta.get("type") == "text_delta":
                    return {"type": "content", "text": delta.get("text", "")}
                return None

            # OpenAI Chat Completions 格式
            choices = data.get("choices", [])
            if not choices:
                return None
            delta = choices[0].get("delta", {})

            # 思考内容
            reasoning = delta.get("reasoning_content") or delta.get("reasoning")
            if reasoning:
                return {"type": "thinking", "text": reasoning}

            # 正文
            content = delta.get("content")
            if content:
                return {"type": "content", "text": content}

            finish_reason = choices[0].get("finish_reason")
            if finish_reason:
                return {"type": "done"}

            return None
        except json.JSONDecodeError:
            logger.debug("忽略非 JSON SSE 事件: %s", event[:LOG_ERROR_PREVIEW_LEN])
            return None
        except Exception as exc:
            logger.warning("解析 SSE 事件异常: %s", exc)
            return None

    def _parse_error(self, body: bytes) -> str:
        """解析错误响应"""
        try:
            data = json.loads(body.decode("utf-8"))
            return data.get("error", {}).get("message", body.decode("utf-8")[:LOG_ERROR_PREVIEW_LEN])
        except Exception:
            return body.decode("utf-8", errors="replace")[:LOG_ERROR_PREVIEW_LEN]


class WebProvider(BaseProvider):
    """
    网页端私有接口 Provider
    复用已登录的 userToken,无需 API Key,但需处理 PoW 挑战
    """

    def __init__(self, token: str):
        self.token = token
        self.timeout = httpx.Timeout(HTTP_TIMEOUT, connect=HTTP_CONNECT_TIMEOUT)
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": DEFAULT_USER_AGENT,
            "Origin": WEB_API_BASE,
            "Referer": f"{WEB_API_BASE}/",
        }
        # 会话状态:SSE fragment 索引 -> 类型(THINK/RESPONSE)
        self._fragment_types: dict[int, str] = {}
        # 搜索来源是否已下发,避免初始化快照与后续 SET 重复发送
        self._sources_emitted: bool = False

    async def validate(self) -> tuple:
        """通过 /api/v0/users/current 验证 token"""
        # 空 token 不能直接拼 Bearer header(会触发 httpx LocalProtocolError)
        if not self.token or not self.token.strip():
            return False, "请先填入 userToken 再验证"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    f"{WEB_API_BASE}{WEB_CURRENT_USER_PATH}",
                    headers=self.headers,
                )
                if resp.status_code == HTTP_STATUS_OK:
                    # 关键:不能只看 HTTP 200,网页接口在 token 无效时也可能返回 200
                    # 需在响应体中检查 code 字段
                    try:
                        data = resp.json()
                        code = data.get("code")
                        if code is not None and code != 0:
                            msg = data.get("msg", "未知错误")
                            return False, f"Token 无效(code={code}): {msg}"
                        return True, "网页端 Token 有效"
                    except ValueError:
                        return True, "网页端 Token 有效"
                if resp.status_code in (401, 403):
                    return False, "Token 无效或已过期,请重新从浏览器获取"
                return False, f"验证失败: HTTP {resp.status_code}"
        except Exception as exc:
            logger.error("网页 Token 验证异常: %s", exc, exc_info=True)
            return False, f"验证异常: {exc}"

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        thinking: bool = False,
        search: bool = False,
        model: str = OFFICIAL_MODEL_FLASH,
        chat_id: str = "",
    ) -> AsyncGenerator[dict[str, Any]]:
        """
        调用网页端私有接口
        流程:(复用会话) -> 获取 PoW 挑战 -> 求解 -> 发送 completion -> 解析 JSON patch 流
        多轮上下文:按 chat_id 复用 chat_session_id,并用上一轮 AI 的 message_id 作 parent_message_id
        """
        if not self.token:
            yield {"type": "error", "text": "未配置网页 Token,请在设置中填入"}
            return

        # 每次新对话重置 fragment 类型表与来源下发标志
        self._fragment_types = {}
        self._sources_emitted = False

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # 1. 复用已存储的会话,或创建新会话
                # 同一 chat_id 复用 chat_session_id 才能保留多轮上下文
                stored = WEB_SESSION_STORE.get(chat_id) if chat_id else None
                # 超过轮次上限则丢弃旧会话,重新创建(避免服务端会话无限增长)
                if stored and stored.get("rounds", 0) >= WEB_SESSION_MAX_ROUNDS:
                    logger.info("网页端会话达到轮次上限,重置: chat_id=%s", chat_id)
                    WEB_SESSION_STORE.pop(chat_id, None)
                    stored = None
                session_id = stored.get("session_id") if stored else None
                parent_message_id = stored.get("last_message_id") if stored else None

                if not session_id:
                    session_resp = await client.post(
                        f"{WEB_API_BASE}{WEB_CREATE_SESSION_PATH}",
                        json={"agent": "chat"},
                        headers=self.headers,
                    )
                    if session_resp.status_code != HTTP_STATUS_OK:
                        yield {"type": "error", "text": f"创建会话失败: HTTP {session_resp.status_code}"}
                        return
                    session_data = session_resp.json()

                    # 网页接口在 token 无效时返回 code!=0 且 data=null,需先检查
                    resp_code = session_data.get("code")
                    if resp_code is not None and resp_code != 0:
                        msg = session_data.get("msg", "未知错误")
                        logger.error("创建会话失败: code=%s, msg=%s", resp_code, msg)
                        yield {
                            "type": "error",
                            "text": f"Token 无效(code={resp_code}): {msg}。请重新从浏览器获取 userToken",
                        }
                        return

                    data = session_data.get("data") or {}
                    biz_data = data.get("biz_data") or {}
                    # 真实结构:data.biz_data.chat_session.id
                    chat_session = biz_data.get("chat_session") or {}
                    session_id = (
                        chat_session.get("id")
                        or biz_data.get("id")
                        or data.get("id")
                        or session_data.get("session_id")
                    )
                    if not session_id:
                        yield {"type": "error", "text": "创建会话失败: 未返回 session_id"}
                        return
                    logger.info("网页端新建会话: %s", session_id)
                else:
                    logger.info("网页端复用会话: %s, parent=%s", session_id, parent_message_id)

                # 2. 获取 PoW 挑战
                pow_resp = await client.post(
                    f"{WEB_API_BASE}{WEB_POW_CHALLENGE_PATH}",
                    json={"target_path": POW_TARGET_PATH},
                    headers=self.headers,
                )
                if pow_resp.status_code != HTTP_STATUS_OK:
                    yield {"type": "error", "text": f"获取 PoW 挑战失败: HTTP {pow_resp.status_code}"}
                    return
                pow_payload = pow_resp.json() or {}
                pow_data = pow_payload.get("data") or {}
                # 真实结构:data.biz_data.challenge
                pow_biz = pow_data.get("biz_data") or {}
                pow_data = pow_biz.get("challenge") or pow_data.get("challenge") or pow_data
                if not pow_data.get("challenge"):
                    yield {"type": "error", "text": "PoW 挑战数据无效"}
                    return

                # 3. 求解 PoW(CPU 密集,放到线程池避免阻塞事件循环)
                solved = await asyncio.to_thread(solve_pow, pow_data)
                if not solved:
                    yield {"type": "error", "text": "PoW 求解失败,请重试"}
                    return
                pow_header = base64.b64encode(
                    json.dumps(solved).encode("utf-8")
                ).decode("utf-8")

                # 4. 发送消息
                # 网页端只需最新一条 prompt;上下文靠 chat_session_id + parent_message_id 串接
                latest_prompt = ""
                for m in reversed(messages):
                    if m.get("role") == "user":
                        latest_prompt = m.get("content", "")
                        break

                # 完整字段(缺任一会触发 HTTP 422):
                # chat_session_id, parent_message_id, model_type, prompt,
                # ref_file_ids, thinking_enabled, search_enabled, preempt
                payload = {
                    "chat_session_id": session_id,
                    # 首轮为 None;后续轮用上一轮 AI 回复的 message_id 串接上下文
                    "parent_message_id": parent_message_id,
                    "model_type": "default",
                    "prompt": latest_prompt,
                    "ref_file_ids": [],
                    "thinking_enabled": thinking,
                    "search_enabled": search,
                    "preempt": False,
                }
                completion_headers = {**self.headers, "x-ds-pow-response": pow_header}

                logger.debug("网页端发送 completion: session=%s, thinking=%s", session_id, thinking)

                async with client.stream(
                    "POST",
                    f"{WEB_API_BASE}{WEB_COMPLETION_PATH}",
                    json=payload,
                    headers=completion_headers,
                ) as response:
                    if response.status_code != HTTP_STATUS_OK:
                        body = await response.aread()
                        logger.error(
                            "网页端 completion 错误: HTTP %s - %s",
                            response.status_code,
                            body[:LOG_ERROR_PREVIEW_LEN],
                        )
                        yield {"type": "error", "text": f"对话请求失败: HTTP {response.status_code}"}
                        return

                    # 5. 解析 JSON patch 流
                    buffer = ""
                    async for chunk in response.aiter_text():
                        buffer += chunk
                        while "\n\n" in buffer:
                            event, buffer = buffer.split("\n\n", 1)
                            for parsed in self._parse_patch_event(event):
                                if parsed.get("type") == "session_meta":
                                    # 捕获本轮 AI message_id,供下一轮作 parent_message_id
                                    if chat_id:
                                        WEB_SESSION_STORE[chat_id] = {
                                            "session_id": session_id,
                                            "last_message_id": parsed.get("message_id"),
                                            "rounds": (stored.get("rounds", 0) + 1) if stored else 1,
                                        }
                                    continue
                                yield parsed
                    if buffer.strip():
                        for parsed in self._parse_patch_event(buffer):
                            if parsed.get("type") == "session_meta":
                                if chat_id:
                                    WEB_SESSION_STORE[chat_id] = {
                                        "session_id": session_id,
                                        "last_message_id": parsed.get("message_id"),
                                        "rounds": (stored.get("rounds", 0) + 1) if stored else 1,
                                    }
                                continue
                            yield parsed

                yield {"type": "done"}

        except httpx.TimeoutException:
            logger.error("网页端请求超时")
            yield {"type": "error", "text": "请求超时,请重试"}
        except Exception as exc:
            logger.error("网页端调用异常: %s", exc, exc_info=True)
            yield {"type": "error", "text": f"调用异常: {exc}"}

    def _parse_patch_event(self, event: str) -> list[dict[str, Any]]:
        """
        解析网页端 JSON patch 流,返回事件列表(单个 patch 可能产出多个输出事件)

        维护 fragment 索引 -> 类型(THINK/RESPONSE)映射,正确分流思考与正文
        事件格式:
          - 初始化: {"v":{"response":{"fragments":[...]}}}
          - 追加:   {"p":"response/fragments/-1/content","o":"APPEND","v":"..."}
          - 续传:   {"v":"..."}  —— 无 p 字段,追加到当前活动的最后一个 fragment
          - 新片段: {"p":"response/fragments","o":"APPEND","v":[{"type":"RESPONSE",...}]}

        @param event 单个 SSE 事件文本
        @return 解析出的事件列表,无有效内容时返回空列表
        """
        events: list[dict[str, Any]] = []
        try:
            data_line = None
            for line in event.split("\n"):
                if line.startswith("data:"):
                    data_line = line[5:].strip()
            if not data_line or data_line == "[DONE]":
                return events

            # 记录原始 patch,便于用最小流量请求定位截断问题
            logger.debug("收到 patch 事件: %s", data_line[:LOG_PATCH_PREVIEW_LEN])

            patch = json.loads(data_line)

            # 初始化/快照事件: {"v":{"response":{"fragments":[...]}}}
            if "v" in patch and isinstance(patch["v"], dict) and "response" in patch["v"]:
                response = patch["v"]["response"] or {}
                # 真实字段:message_id(AI 回复)用于多轮上下文串接
                message_id = response.get("message_id")
                if isinstance(message_id, (int, str)):
                    events.append({"type": "session_meta", "message_id": message_id})
                # 真实字段:搜索是否被触发(用于展示搜索徽章)
                if response.get("search_triggered") and not self._sources_emitted:
                    events.append({"type": "search_state", "triggered": True})
                fragments = response.get("fragments") or []
                for idx, frag in enumerate(fragments):
                    self._fragment_types[idx] = frag.get("type", "RESPONSE")
                # 快照中每个 fragment 的非空内容都要输出,可能同时含 THINK 与 RESPONSE
                for frag in fragments:
                    content = frag.get("content")
                    if content:
                        ftype = frag.get("type", "RESPONSE")
                        events.append({
                            "type": "thinking" if ftype == "THINK" else "content",
                            "text": str(content),
                        })
                    # 真实字段:思考耗时 elapsed_secs
                    elapsed = frag.get("elapsed_secs")
                    if isinstance(elapsed, (int, float)) and elapsed > 0:
                        events.append({"type": "thinking_elapsed", "seconds": float(elapsed)})
                    # 真实字段:引用来源 references
                    refs = frag.get("references") or []
                    if refs and not self._sources_emitted:
                        self._sources_emitted = True
                        events.append({"type": "sources", "items": self._normalize_references(refs)})
                return events

            path = patch.get("p", "")
            op = patch.get("o", "")
            value = patch.get("v", "")

            # 续传事件: {"v":"..."} —— 无 p 字段,追加到当前活动的最后一个 fragment
            # 这是 DeepSeek 流式响应的主要格式,不处理会导致回复被截断
            # 排除已知状态值,避免把 {"v":"FINISHED"} 当正文输出
            if (not path and "v" in patch and isinstance(value, str)
                    and value not in ("FINISHED", "WIP", "FAILED")):
                last_idx = self._current_fragment_index("response/fragments/-1/content")
                ftype = self._fragment_types.get(last_idx, "RESPONSE")
                events.append({
                    "type": "thinking" if ftype == "THINK" else "content",
                    "text": value,
                })
                return events

            # 思考耗时更新: {"p":"response/fragments/-1/elapsed_secs","o":"SET","v":1.4}
            if path.endswith("/elapsed_secs") and isinstance(value, (int, float)):
                events.append({"type": "thinking_elapsed", "seconds": float(value)})
                return events

            # fragment 整体回传(无 op 的 SET): {"p":"response/fragments","v":[{type,content,elapsed_secs,references}]}
            # 思考结束时会把所有 fragment 完整回传一次,含最终耗时与引用
            if path == "response/fragments" and not op and isinstance(value, list):
                for idx, frag in enumerate(value):
                    self._fragment_types[idx] = frag.get("type", "RESPONSE")
                    elapsed = frag.get("elapsed_secs")
                    if isinstance(elapsed, (int, float)) and elapsed > 0:
                        events.append({"type": "thinking_elapsed", "seconds": float(elapsed)})
                    refs = frag.get("references") or []
                    if refs and not self._sources_emitted:
                        self._sources_emitted = True
                        events.append({"type": "sources", "items": self._normalize_references(refs)})
                return events

            # 追加新 fragment: {"p":"response/fragments","o":"APPEND","v":[{type,content}]}
            if path == "response/fragments" and op == "APPEND" and isinstance(value, list):
                for frag in value:
                    idx = len(self._fragment_types)
                    self._fragment_types[idx] = frag.get("type", "RESPONSE")
                    content = frag.get("content")
                    if content:
                        ftype = frag.get("type", "RESPONSE")
                        events.append({
                            "type": "thinking" if ftype == "THINK" else "content",
                            "text": str(content),
                        })
                return events

            # content 追加: {"p":"response/fragments/-1/content","o":"APPEND","v":"..."}
            if "fragments" in path and path.endswith("/content"):
                idx = self._current_fragment_index(path)
                ftype = self._fragment_types.get(idx, "RESPONSE")
                events.append({
                    "type": "thinking" if ftype == "THINK" else "content",
                    "text": str(value),
                })
                return events

            if path == "response/status" and value == "FINISHED":
                events.append({"type": "done"})
                return events

            return events
        except json.JSONDecodeError:
            return events
        except Exception as exc:
            logger.debug("解析 patch 事件异常: %s", exc)
            return events

    def _normalize_references(self, refs: list[Any]) -> list[dict[str, Any]]:
        """
        规范化引用来源为前端统一结构 {title, url, snippet}
        兼容多种可能的引用字段命名,不做猜测性造假:取不到的字段留空
        @param refs 原始引用列表
        @return 规范化后的来源列表
        """
        normalized: list[dict[str, Any]] = []
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            # 标题:常见字段 title / name / document_title
            title = ref.get("title") or ref.get("name") or ref.get("document_title") or ""
            # 链接:常见字段 url / link / href
            url = ref.get("url") or ref.get("link") or ref.get("href") or ""
            # 摘要:常见字段 snippet / content / summary
            snippet = ref.get("snippet") or ref.get("content") or ref.get("summary") or ""
            normalized.append({
                "title": str(title),
                "url": str(url),
                "snippet": str(snippet),
            })
        return normalized

    def _current_fragment_index(self, path: str) -> int:
        """从路径 response/fragments/-1/content 解析 fragment 索引"""
        try:
            parts = path.split("/")
            idx_str = parts[parts.index("fragments") + 1]
            if idx_str == "-1":
                return max(len(self._fragment_types) - 1, 0)
            return int(idx_str)
        except (ValueError, IndexError):
            return 0


def clear_web_session(chat_id: str) -> None:
    """
    清理指定会话的网页端多轮状态(删除会话时调用)
    @param chat_id 前端会话 ID
    """
    if chat_id:
        WEB_SESSION_STORE.pop(chat_id, None)
        logger.debug("已清理网页端会话状态: %s", chat_id)


def create_provider(provider_type: str, api_key: str = "", web_token: str = "") -> BaseProvider:
    """
    工厂函数:根据配置创建 provider
    @param provider_type "official" 或 "web"
    """
    if provider_type == "official":
        return OfficialProvider(api_key)
    elif provider_type == "web":
        return WebProvider(web_token)
    else:
        raise ProviderError(f"未知的 provider 类型: {provider_type}")
