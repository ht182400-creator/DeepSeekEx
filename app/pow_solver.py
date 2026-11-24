"""
DeepSeek PoW (DeepSeekHashV1) 求解器

DeepSeekHashV1 本质:Keccak-f[1600] 跳过 round 0(只执行 rounds 1..23)
参数:rate=136, padding=0x06...0x80, output=32 bytes
已通过官方 WASM 4 个测试向量验证

注:曾尝试扁平化优化但破坏了 pi 置换正确性,已回退到经过验证的实现
"""

import json
import logging
import subprocess  # 仅调用配置中固定的本地 PoW 求解器，非用户可控命令
import time

from config import (
    POW_ALGORITHM,
    POW_GO_BINARY,
    POW_MAX_NONCE,
    POW_NODE_SCRIPT,
    POW_SUBPROCESS_TIMEOUT,
    POW_TARGET_PATH,
)

logger = logging.getLogger(__name__)

# Keccak-f[1600] 轮常数
ROUND_CONSTANTS = [
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A,
    0x8000000080008000, 0x000000000000808B, 0x0000000080000001,
    0x8000000080008081, 0x8000000000008009, 0x000000000000008A,
    0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089,
    0x8000000000008003, 0x8000000000008002, 0x8000000000000080,
    0x000000000000800A, 0x800000008000000A, 0x8000000080008081,
    0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
]

# Keccak rho 旋转偏移 (5x5)
ROTATION_OFFSETS = [
    [0, 36, 3, 41, 18],
    [1, 44, 10, 45, 2],
    [62, 6, 43, 15, 61],
    [28, 55, 25, 21, 56],
    [27, 20, 39, 8, 14],
]

MASK64 = 0xFFFFFFFFFFFFFFFF
# Keccak-f[1600] 轮数(DeepSeekHashV1 跳过 round 0,故从 1 到 23)
KECCAK_ROUNDS = 23
# Keccak 吸收率(字节),rate=136 对应 1088 位容量
KECCAK_RATE = 136
# 输出哈希所需的 lane 数(4 lanes * 8 bytes = 32 bytes)
HASH_OUTPUT_LANES = 4


def _rotl64(value: int, shift: int) -> int:
    """64 位循环左移"""
    shift %= 64
    if shift == 0:
        return value
    return ((value << shift) & MASK64) | (value >> (64 - shift))


def _keccak_f1600(state: list) -> None:
    """
    Keccak-f[1600] 排列,跳过 round 0(DeepSeekHashV1 变体)
    """
    for round_index in range(1, KECCAK_ROUNDS + 1):
        # Theta
        c = [state[x][0] ^ state[x][1] ^ state[x][2] ^ state[x][3] ^ state[x][4] for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rotl64(c[(x + 1) % 5], 1) for x in range(5)]
        for x in range(5):
            for y in range(5):
                state[x][y] ^= d[x]

        # Rho + Pi
        b = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                b[y][(2 * x + 3 * y) % 5] = _rotl64(state[x][y], ROTATION_OFFSETS[x][y])

        # Chi
        for x in range(5):
            for y in range(5):
                state[x][y] = b[x][y] ^ ((~b[(x + 1) % 5][y]) & b[(x + 2) % 5][y])

        # Iota
        state[0][0] ^= ROUND_CONSTANTS[round_index]


def deepseek_hash(message: str) -> str:
    """
    计算 DeepSeekHashV1 哈希
    @param message 输入字符串
    @returns 64 位十六进制哈希
    """
    data = message.encode("utf-8")
    rate = KECCAK_RATE
    pad_len = rate - (len(data) % rate)
    # Keccak pad10*1 规则的两种边界:仅 1 字节时直接 0x86,否则 0x06...0x80
    padded = (
        data + bytes([0x86])
        if pad_len == 1
        else data + bytes([0x06]) + bytes([0x00]) * (pad_len - 2) + bytes([0x80])
    )

    state = [[0] * 5 for _ in range(5)]
    for offset in range(0, len(padded), rate):
        block = padded[offset:offset + rate]
        for i in range(rate // 8):
            lane = int.from_bytes(block[i * 8:(i + 1) * 8], "little")
            x, y = i % 5, i // 5
            state[x][y] ^= lane
        _keccak_f1600(state)

    output = bytearray()
    for i in range(HASH_OUTPUT_LANES):
        x, y = i % 5, i // 5
        output.extend(state[x][y].to_bytes(8, "little"))
    return output[:32].hex()


def solve_pow(challenge_data: dict) -> dict | None:
    """
    求解 PoW 挑战
    优先用 Node.js + 官方 WASM(毫秒级),失败时回退纯 Python(秒级)
    @param challenge_data 服务端返回的 challenge 字典
    @returns 求解后的 response 字典(用于构造 x-ds-pow-response header)
    """
    # 方案一:Go 纯算(最快,约 13ms)
    result = _solve_pow_go(challenge_data)
    if result is not None:
        return result

    # 方案二:Node.js + 官方 WASM(约 18ms)
    result = _solve_pow_wasm(challenge_data)
    if result is not None:
        return result

    # 方案三:纯 Python 回退(约 16s,无外部依赖)
    logger.warning("原生求解器不可用,回退到纯 Python 实现(较慢)")
    return _solve_pow_python(challenge_data)


def _run_subprocess_solver(cmd: list, challenge_data: dict, name: str) -> dict | None:
    """通用子进程求解器调用(Go / Node 共用)"""
    try:
        start = time.time()
        # cmd 来自配置中固定的本地求解器路径，未启用 shell，输入为服务端收到的挑战数据
        proc = subprocess.run(
            cmd,
            input=json.dumps(challenge_data).encode("utf-8"),  # Python subprocess 传纯 UTF-8,无 BOM
            capture_output=True,
            timeout=POW_SUBPROCESS_TIMEOUT,
            check=False,  # 非零返回码由下方 returncode 分支显式处理
        )
        if proc.returncode != 0:
            logger.warning("%s 求解失败: %s", name, proc.stderr.decode("utf-8", errors="replace")[:200])
            return None

        payload = json.loads(proc.stdout.decode("utf-8"))
        elapsed = time.time() - start
        logger.info("PoW %s 求解成功: answer=%s, 耗时 %.3fs", name, payload["answer"], elapsed)

        payload["target_path"] = challenge_data.get("target_path", POW_TARGET_PATH)
        return payload
    except subprocess.TimeoutExpired:
        logger.warning("%s 求解超时", name)
        return None
    except (json.JSONDecodeError, KeyError) as exc:
        logger.warning("%s 求解结果解析失败: %s", name, exc)
        return None
    except FileNotFoundError:
        logger.warning("%s 可执行文件未找到", name)
        return None
    except Exception as exc:
        logger.error("%s 求解异常: %s", name, exc, exc_info=True)
        return None


def _solve_pow_go(challenge_data: dict) -> dict | None:
    """用 Go 纯算求解器(最快,约 13ms)"""
    if not POW_GO_BINARY.exists():
        logger.debug("Go 求解器不存在: %s", POW_GO_BINARY)
        return None
    return _run_subprocess_solver([str(POW_GO_BINARY)], challenge_data, "Go")


def _solve_pow_wasm(challenge_data: dict) -> dict | None:
    """用 Node.js + 官方 WASM 求解(约 18ms)"""
    if not POW_NODE_SCRIPT.exists():
        logger.debug("WASM 求解脚本不存在: %s", POW_NODE_SCRIPT)
        return None
    return _run_subprocess_solver(["node", str(POW_NODE_SCRIPT)], challenge_data, "WASM")


def _solve_pow_python(challenge_data: dict) -> dict | None:
    """纯 Python 求解(回退方案,较慢但无外部依赖)"""
    try:
        algorithm = challenge_data.get("algorithm", POW_ALGORITHM)
        salt = challenge_data["salt"]
        expire_at = challenge_data["expire_at"]
        difficulty = int(challenge_data["difficulty"])
        target = challenge_data["challenge"].lower()
        signature = challenge_data.get("signature", "")
        target_path = challenge_data.get("target_path", POW_TARGET_PATH)

        prefix = f"{salt}_{expire_at}_"
        logger.debug("PoW 纯 Python 求解开始, difficulty=%s", difficulty)
        start = time.time()

        answer = None
        search_limit = min(difficulty, POW_MAX_NONCE)
        for nonce in range(search_limit):
            if deepseek_hash(prefix + str(nonce)) == target:
                answer = nonce
                break

        if answer is None:
            logger.error("PoW 求解失败:在 %s 次尝试内未找到答案", search_limit)
            return None

        elapsed = time.time() - start
        logger.info("PoW 纯 Python 求解成功: answer=%s, 耗时 %.2fs", answer, elapsed)
        return {
            "algorithm": algorithm,
            "challenge": challenge_data["challenge"],
            "salt": salt,
            "answer": answer,
            "signature": signature,
            "target_path": target_path,
        }
    except Exception as exc:
        logger.error("PoW 求解异常: %s", exc, exc_info=True)
        return None


def verify_test_vectors() -> bool:
    """用官方 WASM 测试向量验证哈希实现正确性"""
    vectors = [
        ("", "e594808bc5b7151ac160c6d39a02e0a8e261ed588578403099e3561dc40c26b3"),
        ("testsalt_1700000000_42", "d4a2ea58c89e40887c933484868380c6f803eaa8dc53a3b9df8e431b921a4f09"),
        ("testsalt_1700000000_100000", "abea2f35796b65486e9be1b36f7878c66cab021e96faa473fdf4decd31f9ba30"),
        ("abc123salt_1700000000_12345", "74b3b7452745b70e85eb32ee7f0a9ec0381d42dd5137b695da915e104fc390e1"),
    ]
    all_ok = True
    for msg, expected in vectors:
        actual = deepseek_hash(msg)
        ok = actual == expected
        all_ok = all_ok and ok
        logger.info("测试向量 %s: %s", "PASS" if ok else "FAIL", repr(msg[:30]))
        if not ok:
            logger.error("期望 %s, 实际 %s", expected, actual)
    return all_ok
