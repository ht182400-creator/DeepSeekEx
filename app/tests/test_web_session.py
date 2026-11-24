"""
网页端多轮会话状态管理测试
验证 WEB_SESSION_STORE 的复用、更新、清理逻辑(不消耗真实流量)
"""
import unittest

from providers import WEB_SESSION_STORE, clear_web_session


class TestWebSessionStore(unittest.TestCase):
    """网页端多轮会话存储管理测试"""

    def setUp(self):
        """每个用例清空存储,避免互相污染"""
        WEB_SESSION_STORE.clear()

    def test_store_reuse(self):
        """同一 chat_id 可复用已存的 session_id 与 message_id"""
        WEB_SESSION_STORE["chat-1"] = {
            "session_id": "sess-abc", "last_message_id": 5, "rounds": 2,
        }
        stored = WEB_SESSION_STORE.get("chat-1")
        self.assertEqual(stored["session_id"], "sess-abc")
        self.assertEqual(stored["last_message_id"], 5)

    def test_store_update_after_round(self):
        """一轮对话后更新 message_id 与轮次"""
        WEB_SESSION_STORE["chat-1"] = {
            "session_id": "sess-abc", "last_message_id": 5, "rounds": 1,
        }
        stored = WEB_SESSION_STORE.get("chat-1")
        # 模拟下一轮更新
        WEB_SESSION_STORE["chat-1"] = {
            "session_id": stored["session_id"],
            "last_message_id": 7,
            "rounds": stored["rounds"] + 1,
        }
        updated = WEB_SESSION_STORE["chat-1"]
        self.assertEqual(updated["last_message_id"], 7)
        self.assertEqual(updated["rounds"], 2)

    def test_clear_session(self):
        """删除会话时清理状态"""
        WEB_SESSION_STORE["chat-1"] = {"session_id": "s", "last_message_id": 1, "rounds": 1}
        clear_web_session("chat-1")
        self.assertNotIn("chat-1", WEB_SESSION_STORE)

    def test_clear_empty_id(self):
        """空 chat_id 清理不报错(防御性)"""
        clear_web_session("")
        self.assertEqual(len(WEB_SESSION_STORE), 0)

    def test_isolation_between_chats(self):
        """不同会话之间状态隔离"""
        WEB_SESSION_STORE["chat-1"] = {"session_id": "s1", "last_message_id": 1, "rounds": 1}
        WEB_SESSION_STORE["chat-2"] = {"session_id": "s2", "last_message_id": 9, "rounds": 3}
        clear_web_session("chat-1")
        self.assertNotIn("chat-1", WEB_SESSION_STORE)
        self.assertEqual(WEB_SESSION_STORE["chat-2"]["last_message_id"], 9)


if __name__ == "__main__":
    unittest.main()
