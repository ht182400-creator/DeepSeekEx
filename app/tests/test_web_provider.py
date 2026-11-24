"""
WebProvider 网页端接口流程单元测试
通过 mock httpx / solve_pow 覆盖 validate 与 stream_chat 的全部分支，不消耗真实流量
"""
import json
import logging
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

TEST_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TEST_DIR.parent))

import providers as pv  # noqa: E402  # 依赖 sys.path 注入

LOG_FORMAT = "[%(asctime)s.%(msecs)03d] %(levelname)-5s %(name)s:%(lineno)d  %(message)s"
TEST_TOKEN = "test-token"
TEST_CHAT_ID = "test-chat-id"
TEST_SESSION_ID = "session-123"
HTTP_OK = 200
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_SERVER_ERROR = 500
CHAT_ID_KEY = "chat_id"
DONE_TEXT = "done"


def _make_client(post_responses=None, get_response=None, stream_response=None):
    """构造模拟 httpx.AsyncClient（测试辅助函数）"""
    client = MagicMock()
    if post_responses is not None:
        client.post = AsyncMock(side_effect=post_responses)
    if get_response is not None:
        client.get = AsyncMock(return_value=get_response)
    if stream_response is not None:
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=stream_response)
        cm.__aexit__ = AsyncMock(return_value=None)
        client.stream = MagicMock(return_value=cm)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


def _session_payload(session_id=TEST_SESSION_ID):
    """构造创建会话成功响应（测试辅助函数）"""
    resp = MagicMock(status_code=HTTP_OK)
    resp.json = MagicMock(return_value={
        "code": 0,
        "data": {"biz_data": {"chat_session": {"id": session_id}}},
    })
    return resp


def _pow_payload():
    """构造 PoW 挑战成功响应（测试辅助函数）"""
    resp = MagicMock(status_code=HTTP_OK)
    resp.json = MagicMock(return_value={
        "data": {"biz_data": {"challenge": {
            "challenge": "abc", "salt": "salt", "expire_at": 1, "difficulty": 100,
        }}},
    })
    return resp


def _stream_response(chunks, status_code=HTTP_OK):
    """构造流式响应（测试辅助函数）"""
    resp = MagicMock(status_code=status_code)

    async def aiter_text():
        """模拟分块 SSE 文本"""
        for chunk in chunks:
            yield chunk

    resp.aiter_text = aiter_text
    resp.aread = AsyncMock(return_value=b"error body")
    return resp


def _snapshot_event(message_id, fragments=None, search_triggered=False):
    """
    构造初始化快照 patch 事件（真实格式:{"v":{"response":{...}}}）
    @param message_id AI 回复消息 ID（用于多轮上下文）
    @param fragments 片段列表
    @param search_triggered 是否触发搜索
    @returns SSE data 行文本
    """
    response = {"message_id": message_id}
    if fragments is not None:
        response["fragments"] = fragments
    if search_triggered:
        response["search_triggered"] = True
    return f"data: {json.dumps({'v': {'response': response}})}\n\n"


def _response_fragment(text, ftype="RESPONSE"):
    """构造单个响应片段（测试辅助函数）"""
    return {"type": ftype, "content": text}


class TestWebValidate(unittest.IsolatedAsyncioTestCase):
    """网页 Token 验证测试:空 token / 200+code / 401/403 / 其他状态码 / 异常"""

    async def test_empty_token(self):
        """TC-V01 空 token 返回提示，不发请求"""
        ok, msg = await pv.WebProvider("").validate()
        self.assertFalse(ok)
        self.assertIn("先填入", msg)

    async def test_whitespace_token(self):
        """TC-V02 纯空格 token 返回提示"""
        ok, msg = await pv.WebProvider("   ").validate()
        self.assertFalse(ok)

    async def test_200_code_zero(self):
        """TC-V03 HTTP 200 且 code=0 返回有效"""
        resp = MagicMock(status_code=HTTP_OK)
        resp.json = MagicMock(return_value={"code": 0})
        client = _make_client(get_response=resp)
        with patch("providers.httpx.AsyncClient", return_value=client):
            ok, msg = await pv.WebProvider(TEST_TOKEN).validate()
        self.assertTrue(ok)
        self.assertIn("有效", msg)

    async def test_200_code_error(self):
        """TC-V04 HTTP 200 但 code!=0 返回无效（网页接口特性）"""
        resp = MagicMock(status_code=HTTP_OK)
        resp.json = MagicMock(return_value={"code": 40101, "msg": "token expired"})
        client = _make_client(get_response=resp)
        with patch("providers.httpx.AsyncClient", return_value=client):
            ok, msg = await pv.WebProvider(TEST_TOKEN).validate()
        self.assertFalse(ok)
        self.assertIn("token expired", msg)

    async def test_200_invalid_json(self):
        """TC-V05 HTTP 200 但响应体非 JSON 时按有效处理（兼容异常格式）"""
        resp = MagicMock(status_code=HTTP_OK)
        resp.json = MagicMock(side_effect=ValueError("not json"))
        client = _make_client(get_response=resp)
        with patch("providers.httpx.AsyncClient", return_value=client):
            ok, msg = await pv.WebProvider(TEST_TOKEN).validate()
        self.assertTrue(ok)

    async def test_401_and_403(self):
        """TC-V06 HTTP 401/403 返回无效"""
        for status in (HTTP_UNAUTHORIZED, HTTP_FORBIDDEN):
            client = _make_client(get_response=MagicMock(status_code=status))
            with patch("providers.httpx.AsyncClient", return_value=client):
                ok, msg = await pv.WebProvider(TEST_TOKEN).validate()
            self.assertFalse(ok)
            self.assertIn("无效", msg)

    async def test_other_status(self):
        """TC-V07 其他 HTTP 状态码返回对应错误"""
        client = _make_client(get_response=MagicMock(status_code=HTTP_SERVER_ERROR))
        with patch("providers.httpx.AsyncClient", return_value=client):
            ok, msg = await pv.WebProvider(TEST_TOKEN).validate()
        self.assertFalse(ok)
        self.assertIn("500", msg)

    async def test_exception(self):
        """TC-V08 网络异常返回友好错误"""
        client = _make_client()
        client.get = AsyncMock(side_effect=httpx.ConnectError("network down"))
        with patch("providers.httpx.AsyncClient", return_value=client):
            ok, msg = await pv.WebProvider(TEST_TOKEN).validate()
        self.assertFalse(ok)
        self.assertIn("network down", msg)


class TestWebStreamChat(unittest.IsolatedAsyncioTestCase):
    """网页端流式对话测试:会话创建 / PoW / completion / 多轮上下文 / 各错误分支"""

    def setUp(self):
        """每个用例前清空会话存储，保证隔离"""
        pv.WEB_SESSION_STORE.clear()

    async def _run_stream(
        self, client, *, chat_id="", messages=None, thinking=False, search=False, token=TEST_TOKEN
    ):
        """执行 stream_chat 并收集事件（测试辅助方法）"""
        if messages is None:
            messages = [{"role": "user", "content": "hi"}]
        provider = pv.WebProvider(token)
        solved = {"answer": 1, "target_path": pv.POW_TARGET_PATH}
        with patch("providers.httpx.AsyncClient", return_value=client), \
             patch("providers.solve_pow", return_value=solved):
            events = [
                event async for event in provider.stream_chat(
                    messages, thinking, search, chat_id=chat_id
                )
            ]
        return events

    async def test_empty_token(self):
        """TC-S01 空 token 返回错误事件"""
        events = await self._run_stream(_make_client(), chat_id=TEST_CHAT_ID, token="")
        self.assertEqual(events[0]["type"], "error")
        self.assertIn("Token", events[0]["text"])

    async def test_session_create_http_error(self):
        """TC-S02 创建会话 HTTP 错误返回 error"""
        resp = MagicMock(status_code=HTTP_SERVER_ERROR)
        client = _make_client(post_responses=[resp])
        events = await self._run_stream(client, chat_id=TEST_CHAT_ID)
        self.assertIn("创建会话失败", events[0]["text"])

    async def test_session_create_code_error(self):
        """TC-S03 创建会话 code!=0 返回 Token 无效提示"""
        resp = MagicMock(status_code=HTTP_OK)
        resp.json = MagicMock(return_value={"code": 40101, "msg": "invalid token"})
        client = _make_client(post_responses=[resp])
        events = await self._run_stream(client, chat_id=TEST_CHAT_ID)
        self.assertIn("Token 无效", events[0]["text"])

    async def test_session_create_no_id(self):
        """TC-S04 创建会话响应无 session_id 返回错误"""
        resp = MagicMock(status_code=HTTP_OK)
        resp.json = MagicMock(return_value={"code": 0, "data": {}})
        client = _make_client(post_responses=[resp])
        events = await self._run_stream(client, chat_id=TEST_CHAT_ID)
        self.assertIn("未返回 session_id", events[0]["text"])

    async def test_pow_challenge_http_error(self):
        """TC-S05 获取 PoW 挑战 HTTP 错误返回 error"""
        client = _make_client(post_responses=[_session_payload(), MagicMock(status_code=HTTP_SERVER_ERROR)])
        events = await self._run_stream(client, chat_id=TEST_CHAT_ID)
        self.assertIn("PoW 挑战失败", events[0]["text"])

    async def test_pow_challenge_invalid_data(self):
        """TC-S06 PoW 挑战数据无效返回 error"""
        resp = MagicMock(status_code=HTTP_OK)
        resp.json = MagicMock(return_value={"data": {"challenge": {}}})
        client = _make_client(post_responses=[_session_payload(), resp])
        events = await self._run_stream(client, chat_id=TEST_CHAT_ID)
        self.assertIn("PoW 挑战数据无效", events[0]["text"])

    async def test_pow_solve_failed(self):
        """TC-S07 PoW 求解失败返回 error"""
        client = _make_client(post_responses=[_session_payload(), _pow_payload()])
        provider = pv.WebProvider(TEST_TOKEN)
        with patch("providers.httpx.AsyncClient", return_value=client), \
             patch("providers.solve_pow", return_value=None):
            events = [e async for e in provider.stream_chat(
                [{"role": "user", "content": "hi"}], chat_id=TEST_CHAT_ID
            )]
        self.assertIn("PoW 求解失败", events[0]["text"])

    async def test_completion_http_error(self):
        """TC-S08 completion HTTP 错误返回 error"""
        client = _make_client(
            post_responses=[_session_payload(), _pow_payload()],
            stream_response=_stream_response([], HTTP_SERVER_ERROR),
        )
        events = await self._run_stream(client, chat_id=TEST_CHAT_ID)
        self.assertIn("对话请求失败", events[0]["text"])

    async def test_completion_success(self):
        """TC-S09 完整成功流程返回正文与 done"""
        # SSE patch 事件:初始化快照含 session_meta 与正文片段
        chunks = [_snapshot_event(99, [_response_fragment("你好")])]
        client = _make_client(
            post_responses=[_session_payload(), _pow_payload()],
            stream_response=_stream_response(chunks),
        )
        events = await self._run_stream(client, chat_id=TEST_CHAT_ID)
        types = [e["type"] for e in events]
        self.assertIn("content", types)
        self.assertEqual(types[-1], DONE_TEXT)

    async def test_session_meta_captured_not_forwarded(self):
        """TC-S10 session_meta 被捕获更新存储，不转发前端"""
        client = _make_client(
            post_responses=[_session_payload(), _pow_payload()],
            stream_response=_stream_response([_snapshot_event(123, [_response_fragment("回复")])]),
        )
        events = await self._run_stream(client, chat_id=TEST_CHAT_ID)
        self.assertNotIn("session_meta", [e["type"] for e in events])
        stored = pv.WEB_SESSION_STORE.get(TEST_CHAT_ID)
        self.assertIsNotNone(stored)
        self.assertEqual(stored["last_message_id"], 123)
        self.assertEqual(stored["session_id"], TEST_SESSION_ID)

    async def test_multi_round_reuses_session_and_parent(self):
        """TC-S11 第二轮复用 session_id 并用上一轮 message_id 作 parent_message_id"""
        snapshot = _snapshot_event(456, [_response_fragment("回复")])

        # 第一轮:预置会话存储，直接验证第二轮请求 payload 中带上了 parent
        pv.WEB_SESSION_STORE[TEST_CHAT_ID] = {
            "session_id": TEST_SESSION_ID,
            "last_message_id": 456,
            "rounds": 1,
        }
        captured = {}

        def capturing_stream(method, url, json, headers):
            """捕获 completion payload"""
            captured.update(json)
            return _make_client(stream_response=_stream_response([snapshot])).stream(method, url, json, headers)

        client = _make_client(post_responses=[_pow_payload()])  # 复用会话，只请求 PoW
        cm = MagicMock()
        resp = _stream_response([snapshot])
        cm.__aenter__ = AsyncMock(return_value=resp)
        cm.__aexit__ = AsyncMock(return_value=None)
        client.stream = MagicMock(
            side_effect=lambda *a, **kw: (captured.update(kw.get("json", {})) or cm)
        )

        provider = pv.WebProvider(TEST_TOKEN)
        with patch("providers.httpx.AsyncClient", return_value=client), \
             patch("providers.solve_pow", return_value={"answer": 1, "target_path": pv.POW_TARGET_PATH}):
            [e async for e in provider.stream_chat(
                [{"role": "user", "content": "hi"}], chat_id=TEST_CHAT_ID
            )]

        self.assertEqual(captured["parent_message_id"], 456)
        self.assertEqual(captured["chat_session_id"], TEST_SESSION_ID)

    async def test_round_limit_resets_session(self):
        """TC-S12 达到轮次上限时重置会话（创建新 session）"""
        pv.WEB_SESSION_STORE[TEST_CHAT_ID] = {
            "session_id": "old-session",
            "last_message_id": 1,
            "rounds": pv.WEB_SESSION_MAX_ROUNDS,
        }
        client = _make_client(
            post_responses=[_session_payload(), _pow_payload()],
            stream_response=_stream_response([_snapshot_event(2, [])]),
        )
        events = await self._run_stream(client, chat_id=TEST_CHAT_ID)
        self.assertEqual(events[-1]["type"], DONE_TEXT)
        self.assertEqual(client.post.await_count, 2)  # 重新创建了 session

    async def test_buffer_remainder_parsed(self):
        """TC-S13 残留 buffer（无 \n\n 结尾）也被解析"""
        # 去掉 _snapshot_event 结尾的 \n\n，模拟残留 buffer
        snapshot = _snapshot_event(3, [_response_fragment("残留内容")]).rstrip("\n")
        client = _make_client(
            post_responses=[_session_payload(), _pow_payload()],
            stream_response=_stream_response([snapshot]),
        )
        events = await self._run_stream(client, chat_id=TEST_CHAT_ID)
        texts = [e.get("text") for e in events if e["type"] == "content"]
        self.assertIn("残留内容", texts)

    async def test_timeout(self):
        """TC-S14 请求超时返回 error"""
        client = _make_client()
        client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        events = await self._run_stream(client, chat_id=TEST_CHAT_ID)
        self.assertIn("超时", events[0]["text"])

    async def test_generic_exception(self):
        """TC-S15 通用异常返回 error 事件"""
        client = _make_client()
        client.post = AsyncMock(side_effect=OSError("boom"))
        events = await self._run_stream(client, chat_id=TEST_CHAT_ID)
        self.assertIn("boom", events[0]["text"])

    async def test_no_chat_id_does_not_store_session(self):
        """TC-S16 无 chat_id 时不写入会话存储（官方模式/一次性对话）"""
        client = _make_client(
            post_responses=[_session_payload(), _pow_payload()],
            stream_response=_stream_response([_snapshot_event(5, [])]),
        )
        await self._run_stream(client, chat_id="")
        self.assertEqual(pv.WEB_SESSION_STORE, {})

    async def test_latest_user_prompt_used(self):
        """TC-S17 多条消息时只取最后一条 user prompt（网页端协议）"""
        captured = {}
        snapshot = _snapshot_event(6, [])

        def capturing_stream(method, url, json, headers):
            """捕获 completion payload，并返回正常的 stream 上下文"""
            captured.update(json)
            resp = _stream_response([snapshot])
            cm = MagicMock()
            cm.__aenter__ = AsyncMock(return_value=resp)
            cm.__aexit__ = AsyncMock(return_value=None)
            return cm

        client = _make_client(post_responses=[_session_payload(), _pow_payload()])
        client.stream = MagicMock(side_effect=capturing_stream)
        messages = [
            {"role": "user", "content": "第一条"},
            {"role": "assistant", "content": "回复"},
            {"role": "user", "content": "最后一条"},
        ]
        await self._run_stream(client, chat_id=TEST_CHAT_ID, messages=messages)
        self.assertEqual(captured["prompt"], "最后一条")


class TestParsePatchExtra(unittest.TestCase):
    """_parse_patch_event 剩余分支测试（引用规范化、未知 op、搜索状态）"""

    def setUp(self):
        self.provider = pv.WebProvider(TEST_TOKEN)

    def test_sources_normalized(self):
        """TC-S18 来源引用经规范化后产出 sources 事件（字段 items）"""
        fragment = _response_fragment("正文")
        fragment["references"] = [{"title": "来源1", "url": "http://a", "snippet": "摘要"}]
        event = _snapshot_event(1, [fragment])
        result = self.provider._parse_patch_event(event)
        source_events = [e for e in result if e["type"] == "sources"]
        self.assertTrue(source_events)
        self.assertEqual(source_events[0]["items"][0]["title"], "来源1")

    def test_search_triggered(self):
        """TC-S19 快照中 search_triggered 产出 search_state 事件"""
        response = {"message_id": 1, "search_triggered": True}
        event = f"data: {json.dumps({'v': {'response': response}})}\n\n"
        result = self.provider._parse_patch_event(event)
        self.assertIn({"type": "search_state", "triggered": True}, result)

    def test_unknown_op_ignored(self):
        """TC-S20 未知 op 返回空事件列表"""
        event = json.dumps({"op": "unknown", "path": "/response", "value": {}})
        self.assertEqual(self.provider._parse_patch_event(event), [])

    def test_invalid_json_ignored(self):
        """TC-S21 非法 JSON 返回空列表不崩溃"""
        self.assertEqual(self.provider._parse_patch_event("not json"), [])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")
    unittest.main(verbosity=2)
