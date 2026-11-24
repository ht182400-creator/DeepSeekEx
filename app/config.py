"""
应用配置常量模块
所有魔法数字、路径、配置项集中管理，业务代码不直接写裸值
"""

from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent

# 服务端配置文件路径（存 API Key、token 等敏感信息，不写入代码/文档）
CONFIG_DIR = PROJECT_ROOT / "data"
CONFIG_FILE = CONFIG_DIR / "settings.json"
CHAT_DB_FILE = CONFIG_DIR / "chats.json"

# 服务监听配置
HOST = "127.0.0.1"
PORT = 20000

# 官方 DeepSeek API 配置
OFFICIAL_API_BASE = "https://api.deepseek.com"
OFFICIAL_CHAT_ENDPOINT = f"{OFFICIAL_API_BASE}/chat/completions"
OFFICIAL_MODEL_FLASH = "deepseek-flash"
OFFICIAL_MODEL_PRO = "deepseek-v4-pro"

# 网页端私有接口配置
WEB_API_BASE = "https://chat.deepseek.com"
WEB_CREATE_SESSION_PATH = "/api/v0/chat_session/create"
WEB_POW_CHALLENGE_PATH = "/api/v0/chat/create_pow_challenge"
WEB_COMPLETION_PATH = "/api/v0/chat/completion"
WEB_CURRENT_USER_PATH = "/api/v0/users/current"

# PoW 配置
POW_ALGORITHM = "DeepSeekHashV1"
POW_TARGET_PATH = "/api/v0/chat/completion"
POW_MAX_NONCE = 500000  # nonce 搜索上限，防止死循环(纯 Python 回退用)

# PoW 原生求解器(优先级:Go > Node/WASM > 纯 Python)
# Go 纯算约 13ms(最快),WASM 约 18ms,纯 Python 约 16s
POW_GO_BINARY = PROJECT_ROOT / "pow-go" / "pow-solver.exe"
POW_NODE_SCRIPT = PROJECT_ROOT / "pow-node" / "solve.js"
POW_SUBPROCESS_TIMEOUT = 30  # 子进程超时(秒)

# HTTP 请求配置
HTTP_TIMEOUT = 120  # 长连接流式响应超时（秒）
HTTP_CONNECT_TIMEOUT = 10
HTTP_STATUS_OK = 200             # HTTP 200 OK
HTTP_STATUS_UNAUTHORIZED = 401   # HTTP 401 Unauthorized

# 日志文件
LOG_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOG_DIR / "deepseek_app.log"
LOG_BACKUP_COUNT = 30

# 默认配置（首次启动时写入配置文件）
DEFAULT_SETTINGS = {
    "provider": "official",  # official | web
    "api_key": "",           # 官方 API Key，界面填入（空值占位符，非硬编码口令）
    "web_token": "",         # 网页端 userToken，界面填入
    "model": OFFICIAL_MODEL_FLASH,
    "thinking_enabled": False,
    "search_enabled": False,
    "enhancements": {        # 增强功能开关
        "split_view": True,
        "prompt_library": True,
        "context": True,  # 上下文用量条(统一字段名,旧名 context_meter 已在加载时兼容)
        "export_md": True,
        "focus_mode": True,
    },
}

# 用户代理（模拟浏览器，网页接口必需）
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)
