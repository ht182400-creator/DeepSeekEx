"""
main.py 后端 API 集成测试
覆盖配置管理 / 会话 CRUD / 流式对话 / 工具接口等全部路由与关键分支
测试隔离:导入 main 前将配置与日志路径重定向到临时目录，不触碰真实数据
"""
import json
import logging
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

TEST_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TEST_DIR.parent))

# 临时目录:隔离配置文件、会话库、日志
_TMP_DIR = Path(tempfile.mkdtemp(prefix="deepseek_test_main_"))

import config as app_config  # noqa: E402  # 需先重定向路径再导入 main

app_config.CONFIG_DIR = _TMP_DIR
app_config.CONFIG_FILE = _TMP_DIR / "settings.json"
app_config.CHAT_DB_FILE = _TMP_DIR / "chats.json"
app_config.LOG_DIR = _TMP_DIR / "logs"
app_config.LOG_FILE = _TMP_DIR / "logs" / "test.log"

from fastapi.testclient import TestClient  # noqa: E402

import main as app_main  # noqa: E402  # 依赖上方 config 路径重定向
from providers import ProviderError  # noqa: E402

LOG_FORMAT = "[%(asctime)s.%(msecs)03d] %(levelname)-5s %(name)s:%(lineno)d  %(message)s"
UNKNOWN_PROVIDER = "unknown_provider"


class TestSettingsApi(unittest.TestCase):
    """配置接口测试:脱敏 / 字段合并 / 旧字段迁移 / 异常回退"""

    def setUp(self):
        """每个用例前清空临时配置文件，保证隔离"""
        app_config.CONFIG_FILE.unlink(missing_ok=True)
        self.client = TestClient(app_main.app)

    def test_health(self):
        """TC-M01 健康检查返回 ok"""
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, HTTP_OK)
        self.assertEqual(resp.json()["status"], "ok")

    def test_get_settings_first_run(self):
        """TC-M02 首次加载写入默认配置并脱敏返回"""
        resp = self.client.get("/api/settings")
        self.assertEqual(resp.status_code, HTTP_OK)
        data = resp.json()
        self.assertEqual(data["api_key"], "")
        self.assertEqual(data["web_token"], "")
        self.assertFalse(data["api_key_set"])
        self.assertTrue(app_config.CONFIG_FILE.exists())

    def test_get_settings_masked_with_saved_secret(self):
        """TC-M03 已保存凭据时仅回传布尔标记，不明文"""
        app_main.save_settings({**app_config.DEFAULT_SETTINGS, "api_key": "secret-key", "web_token": "secret-token"})
        data = self.client.get("/api/settings").json()
        self.assertTrue(data["api_key_set"])
        self.assertTrue(data["web_token_set"])
        self.assertEqual(data["api_key"], "")
        self.assertEqual(data["web_token"], "")

    def test_load_settings_legacy_field_migration(self):
        """TC-M04 旧字段 context_meter 迁移到 context 并移除旧字段"""
        saved = dict(app_config.DEFAULT_SETTINGS)
        saved["enhancements"] = {"context_meter": False, "split_view": True}
        app_config.CONFIG_FILE.write_text(json.dumps(saved), encoding="utf-8")
        data = self.client.get("/api/settings").json()
        self.assertFalse(data["enhancements"]["context"])
        self.assertNotIn("context_meter", data["enhancements"])
        self.assertTrue(data["enhancements"]["split_view"])

    def test_load_settings_corrupted_json_fallback(self):
        """TC-M05 配置文件损坏时回退默认配置而非崩溃"""
        app_config.CONFIG_FILE.write_text("{ broken json", encoding="utf-8")
        data = self.client.get("/api/settings").json()
        self.assertEqual(data["provider"], app_config.DEFAULT_SETTINGS["provider"])

    def test_update_settings_normal(self):
        """TC-M06 正常更新配置字段"""
        resp = self.client.post("/api/settings", json={"model": "deepseek-v4-pro", "thinking_enabled": True})
        self.assertEqual(resp.json()["ok"], True)
        saved = json.loads(app_config.CONFIG_FILE.read_text(encoding="utf-8"))
        self.assertEqual(saved["model"], "deepseek-v4-pro")
        self.assertTrue(saved["thinking_enabled"])

    def test_update_settings_empty_string_skipped(self):
        """TC-M07 空字符串不覆盖已有配置（防误清空）"""
        app_main.save_settings({**app_config.DEFAULT_SETTINGS, "api_key": "keep-me"})
        self.client.post("/api/settings", json={"api_key": "   ", "model": ""})
        saved = json.loads(app_config.CONFIG_FILE.read_text(encoding="utf-8"))
        self.assertEqual(saved["api_key"], "keep-me")
        self.assertEqual(saved["model"], app_config.DEFAULT_SETTINGS["model"])

    def test_update_settings_enhancements_merge(self):
        """TC-M08 增强开关按字段合并而非整体替换"""
        self.client.post("/api/settings", json={"enhancements": {"focus_mode": False}})
        saved = json.loads(app_config.CONFIG_FILE.read_text(encoding="utf-8"))
        self.assertFalse(saved["enhancements"]["focus_mode"])
        self.assertTrue(saved["enhancements"]["split_view"])

    def test_update_settings_write_error(self):
        """TC-M09 写入失败时返回 500 而非假成功"""
        with patch.object(app_main, "save_settings", side_effect=OSError("disk full")):
            resp = self.client.post("/api/settings", json={"model": "x"})
        self.assertEqual(resp.status_code, HTTP_SERVER_ERROR)
        self.assertFalse(resp.json()["ok"])


class TestAtomicWrite(unittest.TestCase):
    """原子写测试:正常写入 / 失败清理临时文件 / 异常向上抛出"""

    def setUp(self):
        self.target = _TMP_DIR / "atomic.json"

    def test_atomic_write_ok(self):
        """TC-M10 原子写成功，目标文件内容正确且无临时文件残留"""
        app_main._atomic_write_json(self.target, {"a": 1})
        self.assertEqual(json.loads(self.target.read_text(encoding="utf-8")), {"a": 1})
        self.assertFalse(self.target.with_suffix(".json.tmp").exists())

    def test_atomic_write_failure_cleans_tmp_and_raises(self):
        """TC-M11 写失败时清理临时文件并抛出异常"""
        with patch.object(app_main.json, "dump", side_effect=OSError("write fail")), self.assertRaises(OSError):
            app_main._atomic_write_json(self.target, {"a": 1})
        self.assertFalse(self.target.with_suffix(".json.tmp").exists())


class TestChatApi(unittest.TestCase):
    """会话接口测试:CRUD / 脏数据保护 / 异常分支"""

    def setUp(self):
        app_config.CHAT_DB_FILE.unlink(missing_ok=True)
        self.client = TestClient(app_main.app)

    def test_create_and_list_chats(self):
        """TC-M12 创建会话后出现在列表首位，字段完整"""
        resp = self.client.post("/api/chats", json={"title": "测试会话"})
        self.assertEqual(resp.status_code, HTTP_OK)
        chat = resp.json()
        self.assertEqual(chat["title"], "测试会话")
        self.assertEqual(chat["messages"], [])
        self.assertFalse(chat["starred"])
        listing = self.client.get("/api/chats").json()
        self.assertEqual(len(listing), 1)
        self.assertEqual(listing[0]["id"], chat["id"])

    def test_update_chat_success(self):
        """TC-M13 更新会话标题与消息"""
        chat = self.client.post("/api/chats", json={"title": "old"}).json()
        resp = self.client.put(f"/api/chats/{chat['id']}", json={"title": "new", "messages": [{"role": "user"}]})
        self.assertEqual(resp.status_code, HTTP_OK)
        self.assertEqual(resp.json()["title"], "new")
        self.assertEqual(len(resp.json()["messages"]), 1)

    def test_update_chat_not_found(self):
        """TC-M14 更新不存在的会话返回 404"""
        resp = self.client.put("/api/chats/not-exist", json={"title": "x"})
        self.assertEqual(resp.status_code, HTTP_NOT_FOUND)

    def test_delete_chat_and_clear_web_session(self):
        """TC-M15 删除会话并清理网页端多轮状态"""
        chat = self.client.post("/api/chats", json={"title": "to delete"}).json()
        with patch.object(app_main, "clear_web_session") as mock_clear:
            resp = self.client.delete(f"/api/chats/{chat['id']}")
        self.assertTrue(resp.json()["ok"])
        mock_clear.assert_called_once_with(chat["id"])
        self.assertEqual(self.client.get("/api/chats").json(), [])

    def test_delete_chat_with_dirty_data(self):
        """TC-M16 会话库含缺少 id 的脏数据时不崩溃"""
        app_config.CHAT_DB_FILE.write_text(json.dumps([{"title": "no id"}]), encoding="utf-8")
        resp = self.client.delete("/api/chats/some-id")
        self.assertTrue(resp.json()["ok"])

    def test_load_chats_corrupted_json(self):
        """TC-M17 会话库损坏时返回空列表"""
        app_config.CHAT_DB_FILE.write_text("{ broken", encoding="utf-8")
        self.assertEqual(self.client.get("/api/chats").json(), [])

    def test_create_chat_write_error(self):
        """TC-M18 创建会话写入失败返回 500"""
        with patch.object(app_main, "save_chats", side_effect=OSError("fail")):
            resp = self.client.post("/api/chats", json={"title": "x"})
        self.assertEqual(resp.status_code, HTTP_SERVER_ERROR)

    def test_delete_chat_write_error(self):
        """TC-M19 删除会话写入失败返回 500"""
        app_config.CHAT_DB_FILE.write_text(json.dumps([{"id": "x"}]), encoding="utf-8")
        with patch.object(app_main, "save_chats", side_effect=OSError("fail")):
            resp = self.client.delete("/api/chats/x")
        self.assertEqual(resp.status_code, HTTP_SERVER_ERROR)


class TestValidateApi(unittest.TestCase):
    """凭据验证接口测试:成功 / ProviderError / 未知 provider / 通用异常"""

    def setUp(self):
        self.client = TestClient(app_main.app)

    def test_validate_official_success(self):
        """TC-M20 官方凭据验证成功"""
        mock_provider = MagicMock()
        mock_provider.validate = AsyncMock(return_value=(True, "有效"))
        with patch.object(app_main, "create_provider", return_value=mock_provider):
            resp = self.client.post("/api/validate", json={"provider": "official", "api_key": "k"})
        self.assertTrue(resp.json()["ok"])

    def test_validate_provider_error(self):
        """TC-M21 未知 provider 返回友好错误"""
        resp = self.client.post("/api/validate", json={"provider": UNKNOWN_PROVIDER})
        self.assertFalse(resp.json()["ok"])

    def test_validate_generic_exception(self):
        """TC-M22 验证过程异常返回友好错误"""
        with patch.object(app_main, "create_provider", side_effect=OSError("boom")):
            resp = self.client.post("/api/validate", json={"provider": "official"})
        self.assertFalse(resp.json()["ok"])
        self.assertIn("boom", resp.json()["message"])

    def test_validate_uses_saved_credentials_when_blank(self):
        """TC-M23 请求未带凭据时使用服务端已保存配置"""
        app_main.save_settings({**app_config.DEFAULT_SETTINGS, "api_key": "saved-key"})
        mock_provider = MagicMock()
        mock_provider.validate = AsyncMock(return_value=(True, "ok"))
        with patch.object(app_main, "create_provider", return_value=mock_provider) as mock_create:
            self.client.post("/api/validate", json={"provider": "official", "api_key": ""})
        mock_create.assert_called_once()
        self.assertEqual(mock_create.call_args.args[1], "saved-key")


class TestStreamApi(unittest.TestCase):
    """流式对话接口测试:参数覆盖 / SSE 格式 / provider 异常 / 空消息"""

    def setUp(self):
        self.client = TestClient(app_main.app)

    def test_stream_empty_messages(self):
        """TC-M24 空消息返回 400"""
        resp = self.client.post("/api/chat/stream", json={"messages": []})
        self.assertEqual(resp.status_code, HTTP_BAD_REQUEST)

    def test_stream_success_sse(self):
        """TC-M25 正常流式返回 SSE 事件与 [DONE]"""

        async def fake_stream(*args, **kwargs):
            """模拟 provider 产出两个事件"""
            yield {"type": "content", "text": "你好"}
            yield {"type": "done"}

        mock_provider = MagicMock()
        mock_provider.stream_chat = fake_stream
        with patch.object(app_main, "create_provider", return_value=mock_provider):
            resp = self.client.post("/api/chat/stream", json={"messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(resp.status_code, HTTP_OK)
        self.assertIn('"type": "content"', resp.text)
        self.assertIn("[DONE]", resp.text)

    def test_stream_provider_exception(self):
        """TC-M26 provider 异常时 SSE 返回 error 事件而非崩溃"""

        async def failing_stream(*args, **kwargs):
            """模拟流式过程中抛异常"""
            raise RuntimeError("stream broken")
            yield  # noqa: PIE790  # 使其成为异步生成器

        mock_provider = MagicMock()
        mock_provider.stream_chat = failing_stream
        with patch.object(app_main, "create_provider", return_value=mock_provider):
            resp = self.client.post("/api/chat/stream", json={"messages": [{"role": "user", "content": "hi"}]})
        self.assertIn('"type": "error"', resp.text)
        self.assertIn("stream broken", resp.text)
        self.assertIn("[DONE]", resp.text)

    def test_stream_request_error(self):
        """TC-M27 创建 provider 失败返回 500"""
        with patch.object(app_main, "create_provider", side_effect=ProviderError("bad provider")):
            resp = self.client.post("/api/chat/stream", json={"messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(resp.status_code, HTTP_SERVER_ERROR)

    def test_stream_passes_chat_id_to_provider(self):
        """TC-M28 请求中的 chat_id 透传给 provider，支撑网页端多轮上下文"""
        captured = {}

        async def fake_stream(messages, thinking, search, model, chat_id=""):
            """记录传入的 chat_id"""
            captured["chat_id"] = chat_id
            yield {"type": "content", "text": "ok"}

        mock_provider = MagicMock()
        mock_provider.stream_chat = fake_stream
        with patch.object(app_main, "create_provider", return_value=mock_provider):
            self.client.post(
                "/api/chat/stream",
                json={"messages": [{"role": "user", "content": "hi"}], "chat_id": "chat-123"},
            )
        self.assertEqual(captured["chat_id"], "chat-123")


class TestUtilityApi(unittest.TestCase):
    """工具接口测试:PoW 自检 / 首页静态文件"""

    def setUp(self):
        self.client = TestClient(app_main.app)

    def test_pow_verify(self):
        """TC-M29 PoW 测试向量自检通过"""
        resp = self.client.post("/api/pow/verify")
        self.assertEqual(resp.status_code, HTTP_OK)
        self.assertTrue(resp.json()["ok"])

    def test_index_page(self):
        """TC-M30 首页返回前端 HTML"""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, HTTP_OK)
        self.assertIn("text/html", resp.headers["content-type"])


# HTTP 状态码常量（禁止硬编码）
HTTP_OK = 200
HTTP_BAD_REQUEST = 400
HTTP_NOT_FOUND = 404
HTTP_SERVER_ERROR = 500


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")
    unittest.main(verbosity=2)
