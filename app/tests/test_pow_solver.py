"""
PoW 求解器单元测试:三种求解方案 / 子进程异常分支 / 纯 Python 回退 / 测试向量自检
通过 mock 子进程与配置路径，覆盖真实环境难以触发的失败分支，不消耗真实流量
"""
import json
import logging
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

TEST_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TEST_DIR.parent))

import config as app_config  # noqa: E402  # 依赖 sys.path 注入
import pow_solver as pow  # noqa: E402  # 依赖 sys.path 注入

LOG_FORMAT = "[%(asctime)s.%(msecs)03d] %(levelname)-5s %(name)s:%(lineno)d  %(message)s"

# 测试用挑战数据（字段完整，纯 Python 回退可直接求解）
TEST_CHALLENGE = {
    "algorithm": "DeepSeekHashV1",
    "challenge": "d4a2ea58c89e40887c933484868380c6f803eaa8dc53a3b9df8e431b921a4f09",
    "salt": "testsalt",
    "expire_at": 1700000000,
    "difficulty": 100000,
    "signature": "test-signature",
    "target_path": "/api/v0/chat/completion",
}
# 子进程成功返回的 payload
SUBPROCESS_PAYLOAD = {"answer": 42, "algorithm": "DeepSeekHashV1"}


def _make_proc(returncode=0, stdout=b"", stderr=b"", side_effect=None):
    """构造子进程返回对象或异常副作用（测试辅助函数）"""
    if side_effect is not None:
        return side_effect
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


class TestRunSubprocessSolver(unittest.TestCase):
    """通用子进程求解器测试:成功 / 非零退出 / 超时 / 解析失败 / 文件缺失 / 通用异常"""

    def test_success(self):
        """TC-W01 子进程成功返回 payload 并补 target_path"""
        proc = _make_proc(stdout=json.dumps(SUBPROCESS_PAYLOAD).encode())
        with patch.object(pow.subprocess, "run", return_value=proc):
            result = pow._run_subprocess_solver(["solver"], TEST_CHALLENGE, "Go")
        self.assertEqual(result["answer"], 42)
        self.assertEqual(result["target_path"], TEST_CHALLENGE["target_path"])

    def test_success_uses_default_target_path(self):
        """TC-W02 challenge 缺 target_path 时用默认常量"""
        proc = _make_proc(stdout=json.dumps(SUBPROCESS_PAYLOAD).encode())
        challenge = {k: v for k, v in TEST_CHALLENGE.items() if k != "target_path"}
        with patch.object(pow.subprocess, "run", return_value=proc):
            result = pow._run_subprocess_solver(["solver"], challenge, "Go")
        self.assertEqual(result["target_path"], app_config.POW_TARGET_PATH)

    def test_nonzero_returncode(self):
        """TC-W03 子进程非零退出返回 None"""
        proc = _make_proc(returncode=1, stderr=b"error message")
        with patch.object(pow.subprocess, "run", return_value=proc):
            self.assertIsNone(pow._run_subprocess_solver(["solver"], TEST_CHALLENGE, "Go"))

    def test_timeout(self):
        """TC-W04 子进程超时返回 None"""
        with patch.object(pow.subprocess, "run", side_effect=subprocess.TimeoutExpired("solver", 30)):
            self.assertIsNone(pow._run_subprocess_solver(["solver"], TEST_CHALLENGE, "Go"))

    def test_json_decode_error(self):
        """TC-W05 子进程输出非法 JSON 返回 None"""
        proc = _make_proc(stdout=b"not json")
        with patch.object(pow.subprocess, "run", return_value=proc):
            self.assertIsNone(pow._run_subprocess_solver(["solver"], TEST_CHALLENGE, "Go"))

    def test_key_error(self):
        """TC-W06 子进程输出缺 answer 字段（KeyError）返回 None"""
        proc = _make_proc(stdout=json.dumps({"no_answer": 1}).encode())
        with patch.object(pow.subprocess, "run", return_value=proc):
            self.assertIsNone(pow._run_subprocess_solver(["solver"], TEST_CHALLENGE, "Go"))

    def test_file_not_found(self):
        """TC-W07 可执行文件不存在返回 None"""
        with patch.object(pow.subprocess, "run", side_effect=FileNotFoundError("no binary")):
            self.assertIsNone(pow._run_subprocess_solver(["solver"], TEST_CHALLENGE, "Go"))

    def test_generic_exception(self):
        """TC-W08 其他异常返回 None 不崩溃"""
        with patch.object(pow.subprocess, "run", side_effect=OSError("permission denied")):
            self.assertIsNone(pow._run_subprocess_solver(["solver"], TEST_CHALLENGE, "Go"))


class TestSolverSelection(unittest.TestCase):
    """三方案选择与文件存在性分支测试"""

    def test_go_solver_called_when_binary_exists(self):
        """TC-W10 Go 方案存在时返回求解结果"""
        with patch("pathlib.Path.exists", return_value=True), \
             patch.object(pow, "_run_subprocess_solver", return_value={"answer": 7}) as mock_run:
            result = pow._solve_pow_go(TEST_CHALLENGE)
        self.assertEqual(result, {"answer": 7})
        self.assertEqual(mock_run.call_args.args[2], "Go")

    def test_go_solver_skipped_when_binary_missing(self):
        """TC-W11 Go 二进制不存在时返回 None 不调用子进程"""
        with patch("pathlib.Path.exists", return_value=False), \
             patch.object(pow, "_run_subprocess_solver") as mock_run:
            self.assertIsNone(pow._solve_pow_go(TEST_CHALLENGE))
        mock_run.assert_not_called()

    def test_wasm_solver_called_when_script_exists(self):
        """TC-W12 Node/WASM 脚本存在时返回求解结果"""
        with patch("pathlib.Path.exists", return_value=True), \
             patch.object(pow, "_run_subprocess_solver", return_value={"answer": 8}) as mock_run:
            result = pow._solve_pow_wasm(TEST_CHALLENGE)
        self.assertEqual(result, {"answer": 8})
        self.assertIn("node", mock_run.call_args.args[0])

    def test_wasm_solver_skipped_when_script_missing(self):
        """TC-W13 WASM 脚本不存在时返回 None"""
        with patch("pathlib.Path.exists", return_value=False), \
             patch.object(pow, "_run_subprocess_solver") as mock_run:
            self.assertIsNone(pow._solve_pow_wasm(TEST_CHALLENGE))
        mock_run.assert_not_called()

    def test_solve_pow_prefers_go(self):
        """TC-W14 solve_pow 优先用 Go，成功时不回退"""
        with patch.object(pow, "_solve_pow_go", return_value={"answer": 1}) as go, \
             patch.object(pow, "_solve_pow_wasm") as wasm, \
             patch.object(pow, "_solve_pow_python") as python:
            result = pow.solve_pow(TEST_CHALLENGE)
        self.assertEqual(result, {"answer": 1})
        wasm.assert_not_called()
        python.assert_not_called()
        go.assert_called_once()

    def test_solve_pow_falls_back_to_wasm(self):
        """TC-W15 Go 失败时回退 WASM"""
        with patch.object(pow, "_solve_pow_go", return_value=None), \
             patch.object(pow, "_solve_pow_wasm", return_value={"answer": 2}) as wasm, \
             patch.object(pow, "_solve_pow_python") as python:
            result = pow.solve_pow(TEST_CHALLENGE)
        self.assertEqual(result, {"answer": 2})
        python.assert_not_called()
        wasm.assert_called_once()

    def test_solve_pow_falls_back_to_python(self):
        """TC-W16 Go/WASM 都失败时回退纯 Python"""
        with patch.object(pow, "_solve_pow_go", return_value=None), \
             patch.object(pow, "_solve_pow_wasm", return_value=None), \
             patch.object(pow, "_solve_pow_python", return_value={"answer": 3}) as python:
            result = pow.solve_pow(TEST_CHALLENGE)
        self.assertEqual(result, {"answer": 3})
        python.assert_called_once()


class TestPurePythonSolver(unittest.TestCase):
    """纯 Python 回退求解测试（用真实哈希，不 mock）"""

    def test_solve_success(self):
        """TC-W17 真实求解低难度挑战，返回完整 payload"""
        result = pow._solve_pow_python(TEST_CHALLENGE)
        self.assertIsNotNone(result)
        self.assertEqual(result["answer"], 42)
        self.assertEqual(result["algorithm"], TEST_CHALLENGE["algorithm"])
        self.assertEqual(result["signature"], TEST_CHALLENGE["signature"])

    def test_solve_no_answer_found(self):
        """TC-W18 难度为 0（搜索范围空）返回 None"""
        challenge = {**TEST_CHALLENGE, "difficulty": 0}
        self.assertIsNone(pow._solve_pow_python(challenge))

    def test_solve_missing_salt(self):
        """TC-W19 缺 salt 字段捕获异常返回 None"""
        challenge = {k: v for k, v in TEST_CHALLENGE.items() if k != "salt"}
        self.assertIsNone(pow._solve_pow_python(challenge))

    def test_solve_invalid_difficulty(self):
        """TC-W20 difficulty 非法值捕获异常返回 None"""
        challenge = {**TEST_CHALLENGE, "difficulty": "not-a-number"}
        self.assertIsNone(pow._solve_pow_python(challenge))

    def test_solve_uses_defaults(self):
        """TC-W21 缺 algorithm/signature/target_path 时用默认值"""
        challenge = {
            k: v for k, v in TEST_CHALLENGE.items()
            if k not in ("algorithm", "signature", "target_path")
        }
        result = pow._solve_pow_python(challenge)
        self.assertEqual(result["algorithm"], app_config.POW_ALGORITHM)
        self.assertEqual(result["signature"], "")
        self.assertEqual(result["target_path"], app_config.POW_TARGET_PATH)


class TestVerifyVectors(unittest.TestCase):
    """测试向量自检测试（含失败分支）"""

    def test_all_vectors_pass(self):
        """TC-W22 全部官方测试向量通过"""
        self.assertTrue(pow.verify_test_vectors())

    def test_vector_mismatch_returns_false(self):
        """TC-W23 篡改哈希实现后自检返回 False（覆盖失败日志分支）"""
        original = pow.deepseek_hash
        try:
            pow.deepseek_hash = lambda msg: "wrong-hash-value"
            self.assertFalse(pow.verify_test_vectors())
        finally:
            pow.deepseek_hash = original


class TestDeepseekHash(unittest.TestCase):
    """哈希函数边界测试"""

    def test_known_vectors(self):
        """TC-W24 已知输入哈希值匹配官方向量"""
        self.assertEqual(
            pow.deepseek_hash(""),
            "e594808bc5b7151ac160c6d39a02e0a8e261ed588578403099e3561dc40c26b3",
        )
        self.assertEqual(
            pow.deepseek_hash("testsalt_1700000000_42"),
            "d4a2ea58c89e40887c933484868380c6f803eaa8dc53a3b9df8e431b921a4f09",
        )

    def test_padding_boundary(self):
        """TC-W25 不同长度输入覆盖 Keccak padding 的 1 字节与多字节两种边界"""
        for length in (1, 135, 136, 137, 271, 272, 273):
            """逐长度计算哈希，确认不崩溃且输出 64 位十六进制"""
            msg = "a" * length
            result = pow.deepseek_hash(msg)
            self.assertEqual(len(result), 64)
            self.assertTrue(all(c in "0123456789abcdef" for c in result))

    def test_unicode_input(self):
        """TC-W26 中文输入正确编码为 UTF-8 后哈希"""
        result = pow.deepseek_hash("中文测试")
        self.assertEqual(len(result), 64)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")
    unittest.main(verbosity=2)
