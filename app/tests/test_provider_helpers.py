"""
Provider 纯函数与模拟网络调用单元测试
覆盖 SSE 事件解析 / 错误解析 / 引用规范化 / 片段索引 / 官方接口 validate 与 stream_chat 各分支
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

from providers import (  # noqa: E402  # 依赖 sys.path 注入
    OfficialProvider,
    ProviderError,
    WebProvider,
    create_provider,
)

LOG_FORMAT = "[%(asctime)s.%(msecs)03d] %(levelname)-5s %(name)s:%(lineno)d  %(message)s"
TEST_API_KEY = "test-api-key"
TEST_TOKEN = "test-token"

HTTP_OK = 200
HTTP_UNAUTHORIZED = 401
HTTP_SERVER_ERROR = 500


class TestParseSseEvent(unittest.TestCase):
    """官方 SSE 事件解析测试:OpenAI 格式 / Anthropic 格式 / 无效输入"""

    def setUp(self):
        self.provider = OfficialProvider(TEST_API_KEY)

    def test_content_delta(self):
        """TC-P01 解析正文增量事件"""
        raw = 'data: {"choices":[{"delta":{"content":"你好"}}]}\n\n'
        self.assertEqual(self.provider._parse_sse_event(raw), {"type": "content", "text": "你好"})

    def test_reasoning_content(self):
        """TC-P02 解析 reasoning_content 思考事件"""
        raw = 'data: {"choices":[{"delta":{"reasoning_content":"思考中"}}]}'
        self.assertEqual(self.provider._parse_sse_event(raw), {"type": "thinking", "text": "思考中"})

    def test_reasoning_alias(self):
        """TC-P03 解析 reasoning 别名思考事件"""
        raw = 'data: {"choices":[{"delta":{"reasoning":"别名思考"}}]}'
        self.assertEqual(self.provider._parse_sse_event(raw), {"type": "thinking", "text": "别名思考"})

    def test_finish_reason(self):
        """TC-P04 解析结束事件"""
        raw = 'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}'
        self.assertEqual(self.provider._parse_sse_event(raw), {"type": "done"})

    def test_anthropic_thinking_delta(self):
        """TC-P05 解析 Anthropic 思考增量"""
        raw = 'data: {"type":"content_block_delta","delta":{"type":"thinking_delta","thinking":"anthropic思考"}}'
        self.assertEqual(self.provider._parse_sse_event(raw), {"type": "thinking", "text": "anthropic思考"})

    def test_anthropic_text_delta(self):
        """TC-P06 解析 Anthropic 文本增量"""
        raw = 'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"anthropic正文"}}'
        self.assertEqual(self.provider._parse_sse_event(raw), {"type": "content", "text": "anthropic正文"})

    def test_anthropic_unknown_delta(self):
        """TC-P07 未知 Anthropic delta 类型返回 None"""
        raw = 'data: {"type":"content_block_delta","delta":{"type":"unknown"}}'
        self.assertIsNone(self.provider._parse_sse_event(raw))

    def test_done_and_empty(self):
        """TC-P08 [DONE] 与空 data 返回 None"""
        self.assertIsNone(self.provider._parse_sse_event("data: [DONE]\n\n"))
        self.assertIsNone(self.provider._parse_sse_event("event: ping\n\n"))

    def test_no_choices_and_invalid_json(self):
        """TC-P09 无 choices 与非法 JSON 返回 None"""
        self.assertIsNone(self.provider._parse_sse_event('data: {"foo":"bar"}'))
        self.assertIsNone(self.provider._parse_sse_event("data: {bad json"))

    def test_exception_in_parse(self):
        """TC-P10 解析中异常返回 None（如 delta 非字典）"""
        raw = 'data: {"choices":[{"delta":"not-a-dict"}]}'
        self.assertIsNone(self.provider._parse_sse_event(raw))


class TestParseError(unittest.TestCase):
    """错误响应解析测试"""

    def setUp(self):
        self.provider = OfficialProvider(TEST_API_KEY)

    def test_standard_error(self):
        """TC-P11 标准 error.message 结构"""
        body = json.dumps({"error": {"message": "invalid api key"}}).encode()
        self.assertEqual(self.provider._parse_error(body), "invalid api key")

    def test_error_without_message(self):
        """TC-P12 error 结构缺少 message 时回退原文"""
        body = json.dumps({"error": {}}).encode()
        self.assertEqual(self.provider._parse_error(body), body.decode())

    def test_invalid_utf8(self):
        """TC-P13 非法 UTF-8 字节不崩溃"""
        body = b"\xff\xfe\xfd"
        result = self.provider._parse_error(body)
        self.assertIsInstance(result, str)


class TestReferenceHelpers(unittest.TestCase):
    """引用规范化与片段索引测试"""

    def setUp(self):
        self.provider = WebProvider(TEST_TOKEN)

    def test_normalize_various_field_names(self):
        """TC-P14 兼容 title/name/document_title 与 url/link/href 等多种字段"""
        refs = [
            {"title": "T1", "url": "http://a", "snippet": "S1"},
            {"name": "T2", "link": "http://b", "content": "S2"},
            {"document_title": "T3", "href": "http://c", "summary": "S3"},
            {"title": "T4"},  # 缺 url/snippet 留空
        ]
        result = self.provider._normalize_references(refs)
        self.assertEqual(len(result), 4)
        self.assertEqual(result[0], {"title": "T1", "url": "http://a", "snippet": "S1"})
        self.assertEqual(result[1]["title"], "T2")
        self.assertEqual(result[2]["url"], "http://c")
        self.assertEqual(result[3]["url"], "")

    def test_normalize_skips_non_dict(self):
        """TC-P15 非字典引用被跳过"""
        result = self.provider._normalize_references(["bad", None, 123, {"title": "ok"}])
        self.assertEqual(len(result), 1)

    def test_current_fragment_index(self):
        """TC-P16 从路径解析片段索引，含 -1 特殊值"""
        self.provider._fragment_types = {"0": "RESPONSE", "1": "THINK", "2": "RESPONSE"}
        self.assertEqual(self.provider._current_fragment_index("response/fragments/1/content"), 1)
        self.assertEqual(self.provider._current_fragment_index("response/fragments/-1/content"), 2)
        self.assertEqual(self.provider._current_fragment_index("invalid/path"), 0)

    def test_normalize_empty_refs(self):
        """TC-P17 空引用列表返回空列表"""
        self.assertEqual(self.provider._normalize_references([]), [])


class TestOfficialValidate(unittest.IsolatedAsyncioTestCase):
    """官方凭据验证测试:模拟 httpx 响应"""

    async def test_validate_empty_key(self):
        """TC-P18 空 Key 直接返回提示，不发请求"""
        ok, msg = await OfficialProvider("").validate()
        self.assertFalse(ok)
        self.assertIn("先填入", msg)

    async def test_validate_success(self):
        """TC-P19 HTTP 200 返回有效"""
        provider = OfficialProvider(TEST_API_KEY)
        mock_resp = MagicMock(status_code=HTTP_OK)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        with patch("providers.httpx.AsyncClient", return_value=mock_client):
            ok, msg = await provider.validate()
        self.assertTrue(ok)

    async def test_validate_unauthorized(self):
        """TC-P20 HTTP 401 返回无效"""
        provider = OfficialProvider(TEST_API_KEY)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=MagicMock(status_code=HTTP_UNAUTHORIZED))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        with patch("providers.httpx.AsyncClient", return_value=mock_client):
            ok, msg = await provider.validate()
        self.assertFalse(ok)
        self.assertIn("无效", msg)

    async def test_validate_other_status(self):
        """TC-P21 其他 HTTP 状态码返回对应错误"""
        provider = OfficialProvider(TEST_API_KEY)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=MagicMock(status_code=HTTP_SERVER_ERROR))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        with patch("providers.httpx.AsyncClient", return_value=mock_client):
            ok, msg = await provider.validate()
        self.assertFalse(ok)
        self.assertIn("500", msg)

    async def test_validate_exception(self):
        """TC-P22 网络异常返回友好错误"""
        provider = OfficialProvider(TEST_API_KEY)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("network down"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        with patch("providers.httpx.AsyncClient", return_value=mock_client):
            ok, msg = await provider.validate()
        self.assertFalse(ok)
        self.assertIn("network down", msg)


class TestOfficialStreamChat(unittest.IsolatedAsyncioTestCase):
    """官方流式对话测试:无 Key / 超时 / HTTP 错误 / 正常流"""

    async def test_no_api_key(self):
        """TC-P23 无 Key 直接返回错误事件"""
        events = [e async for e in OfficialProvider("").stream_chat([{"role": "user", "content": "hi"}])]
        self.assertEqual(events[0]["type"], "error")

    async def test_timeout(self):
        """TC-P24 超时返回友好错误"""
        provider = OfficialProvider(TEST_API_KEY)
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        with patch("providers.httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value = mock_cm
            events = [e async for e in provider.stream_chat([{"role": "user", "content": "hi"}])]
        self.assertTrue(any(e["type"] == "error" and "超时" in e["text"] for e in events))

    async def test_http_error(self):
        """TC-P25 HTTP 错误返回 error 事件"""
        provider = OfficialProvider(TEST_API_KEY)
        mock_resp = MagicMock(status_code=HTTP_SERVER_ERROR)
        mock_resp.aread = AsyncMock(return_value=b'{"error":{"message":"server error"}}')
        stream_cm = MagicMock()
        stream_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        stream_cm.__aexit__ = AsyncMock(return_value=None)
        mock_client = MagicMock()
        mock_client.stream = MagicMock(return_value=stream_cm)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        with patch("providers.httpx.AsyncClient", return_value=mock_client):
            events = [e async for e in provider.stream_chat([{"role": "user", "content": "hi"}])]
        self.assertTrue(any(e["type"] == "error" and "server error" in e["text"] for e in events))

    async def test_normal_stream(self):
        """TC-P26 正常 SSE 流解析出正文与思考"""
        provider = OfficialProvider(TEST_API_KEY)
        chunks = [
            'data: {"choices":[{"delta":{"reasoning_content":"思考"}}]}\n\n',
            'data: {"choices":[{"delta":{"content":"正文"}}]}\n\n',
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n',
        ]

        async def aiter_text():
            """模拟分块到达"""
            for chunk in chunks:
                yield chunk

        mock_resp = MagicMock(status_code=HTTP_OK)
        mock_resp.aiter_text = aiter_text
        stream_cm = MagicMock()
        stream_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        stream_cm.__aexit__ = AsyncMock(return_value=None)
        mock_client = MagicMock()
        mock_client.stream = MagicMock(return_value=stream_cm)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        with patch("providers.httpx.AsyncClient", return_value=mock_client):
            events = [e async for e in provider.stream_chat([{"role": "user", "content": "hi"}], thinking=True)]
        self.assertIn({"type": "thinking", "text": "思考"}, events)
        self.assertIn({"type": "content", "text": "正文"}, events)
        self.assertIn({"type": "done"}, events)

    async def test_search_payload(self):
        """TC-P27 开启搜索时请求体带 tools 字段"""
        provider = OfficialProvider(TEST_API_KEY)
        captured = {}

        async def noop_text():
            """空流"""
            return
            yield  # noqa: PIE790  # 使其成为异步生成器

        mock_resp = MagicMock(status_code=HTTP_OK)
        mock_resp.aiter_text = noop_text
        stream_cm = MagicMock()
        stream_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        stream_cm.__aexit__ = AsyncMock(return_value=None)
        mock_client = MagicMock()
        mock_client.stream = MagicMock(
            side_effect=lambda method, url, json, headers: captured.update(json=json) or stream_cm
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        with patch("providers.httpx.AsyncClient", return_value=mock_client):
            [e async for e in provider.stream_chat([{"role": "user", "content": "hi"}], search=True)]
        self.assertIn("tools", captured["json"])


class TestCreateProvider(unittest.TestCase):
    """工厂函数测试"""

    def test_create_official(self):
        """TC-P28 official 类型返回 OfficialProvider"""
        self.assertIsInstance(create_provider("official", TEST_API_KEY), OfficialProvider)

    def test_create_web(self):
        """TC-P29 web 类型返回 WebProvider"""
        self.assertIsInstance(create_provider("web", "", TEST_TOKEN), WebProvider)

    def test_create_unknown(self):
        """TC-P30 未知类型抛出 ProviderError"""
        with self.assertRaises(ProviderError):
            create_provider("unknown")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")
    unittest.main(verbosity=2)
