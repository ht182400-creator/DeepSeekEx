"""
WebProvider SSE patch 解析回归测试
数据驱动:案例定义见 test_patch_cases.json
测试日志:运行时生成到 tests/logs/test_YYYYMMDD_HHMMSS.log
"""
import json
import logging
import sys
import unittest
from datetime import datetime
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TEST_DIR.parent))

from providers import WebProvider  # noqa: E402  # sys.path 注入必须在导入前完成

# 测试常量:案例文件、日志目录、测试用 token、日志格式
CASES_FILE = TEST_DIR / "test_patch_cases.json"
LOG_DIR = TEST_DIR / "logs"
LOG_FORMAT = "[%(asctime)s.%(msecs)03d] %(levelname)-5s %(name)s:%(lineno)d  %(message)s"
TEST_TOKEN = "test-token"


class _ColorFormatter(logging.Formatter):
    """控制台日志着色:ERROR 红色、WARNING 黄色,便于一眼识别未通过用例"""

    RED = "\033[91m"
    YELLOW = "\033[93m"
    RESET = "\033[0m"

    def format(self, record):
        text = super().format(record)
        if record.levelno >= logging.ERROR:
            return f"{self.RED}{text}{self.RESET}"
        if record.levelno >= logging.WARNING:
            return f"{self.YELLOW}{text}{self.RESET}"
        return text


def setup_logger():
    """
    配置测试日志:同时输出到控制台与带时间戳的文件
    文件日志失败不影响测试主流程
    """
    log = logging.getLogger("patch_test")
    log.setLevel(logging.DEBUG)
    log.handlers.clear()
    fmt = logging.Formatter(LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_file = LOG_DIR / f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        log.addHandler(fh)
        log.info("测试日志文件: %s", log_file)
    except Exception as exc:
        log.warning("文件日志初始化失败,仅输出到控制台: %s", exc)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(_ColorFormatter(LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S"))
    log.addHandler(ch)
    return log


test_logger = setup_logger()


class TestParsePatchEvent(unittest.TestCase):
    """_parse_patch_event 解析回归测试(数据驱动)"""

    def setUp(self):
        """每个用例独立实例化 provider,避免 fragment 状态相互污染"""
        self.provider = WebProvider(TEST_TOKEN)

    def load_cases(self):
        """加载 JSON 测试案例"""
        try:
            with open(CASES_FILE, encoding="utf-8") as f:
                return json.load(f)["cases"]
        except Exception as exc:
            self.fail(f"加载案例文件失败: {exc}")

    def test_all_cases(self):
        """逐案例喂入事件序列,验证解析输出的事件列表"""
        for case in self.load_cases():
            with self.subTest(case=case["id"]):
                # 连续流案例需要在单个用例内累积 fragment 状态,先重置
                self.provider._fragment_types = {}
                self.provider._sources_emitted = False
                actual = []
                for event in case["events"]:
                    actual.extend(self.provider._parse_patch_event(event))
                if actual != case["expected"]:
                    test_logger.error(
                        "[FAIL] %s %s 期望=%s 实际=%s",
                        case["id"], case["name"], case["expected"], actual,
                    )
                else:
                    test_logger.info("[PASS] %s %s", case["id"], case["name"])
                self.assertEqual(actual, case["expected"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
