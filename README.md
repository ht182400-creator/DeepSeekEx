# DeepSeek Studio — 1:1 复刻 + 增强的真实可用产品

本项目是连接真实 DeepSeek 后端的网页端产品：以 DeepSeek 网页端 1:1 复刻 UI 为基础，叠加可开关的增强功能，通过 FastAPI 后端调用真实 DeepSeek 接口。

## 一、交付物

| 路径 | 内容 |
|------|------|
| `app/` | **主产品**：FastAPI 后端 + 1:1 复刻前端 + 增强层 + Go PoW 求解器 |
| `docs/01_DeepSeek产品分析报告.md` | 功能拆解 + 产品功能结构图 |
| `docs/02_优化版设计说明.md` | 增强层设计（含实际落地状态） |
| `docs/03_PoW方案讨论与定稿.md` | PoW 技术详解（原理/历史/DeepSeekHashV1/优缺点）+ 方案调研、失败尝试、定稿与验证 |
| `docs/04_上传仓库说明.md` | GitHub/Forgejo 上传范围、安全边界、双平台推送步骤 |
| 早期静态原型 `replica/`、`enhanced/` | 已被 `app/` 取代，不随仓库分发 |

## 二、核心特性

### 真实后端（非 offline 假数据）
- **双 Provider，可切换**：
  - 官方 DeepSeek API（`https://api.deepseek.com`，需 API Key，按量计费）
  - 网页登录态接口（`chat.deepseek.com` 私有接口，需 userToken，免费）
- **SSE 流式对话**：真实 token 级输出，支持思考模式与联网搜索
- **会话持久化**：服务端 JSON 存储
- **Go PoW 求解器**：DeepSeekHashV1 纯算实现，约 13ms（含网络端到端对话约 1.26s）

### 1:1 复刻 UI
鲸鱼 Logo、侧边栏时间分组、居中标语、输入框双芯片、思考面板、引用角标、来源卡、操作栏 — 均来自登录态实测截图。

### 增强层（设置中可开关）
提示词库、Markdown 导出、专注模式、上下文用量显示、模型选择、深色主题。

## 三、上传后首次准备

本仓库只含**源码与文档**，不含真实凭据、预编译二进制、依赖目录（见 `.gitignore`）。首次使用按以下步骤：

```bash
# 1. 后端 Python 依赖
pip install fastapi uvicorn httpx

# 2.（可选）Node/WASM PoW 回退：仅源码随仓库分发，需本地安装 npm 依赖
cd app/pow-node && npm install && cd ../..

# 3.（可选）Go PoW 求解器：预编译 exe 不上传，需本地 Go 工具链编译
cd app/pow-go && go build -o pow-solver.exe main.go && .\pow-solver.exe --selftest && cd ../..

# 4. 生成真实配置文件（模板不含凭据）
copy app\data\settings.example.json app\data\settings.json
```

> 不装 Go/Node 也能运行：PoW 会自动回退纯 Python（较慢，约 16s）。装了 Go 求解器约 13ms。

## 四、启动

### 一键启动（推荐）
双击根目录 `start-servers.bat`（GBK 编码，勿改为 UTF-8）。它会 kill 旧进程后启动服务。

命令行 `start-servers.bat autostart` 可跳过结尾暂停。

访问：`http://127.0.0.1:20000`

### 手动启动
```bash
cd app
python -m uvicorn main:app --host 127.0.0.1 --port 20000
```

## 五、依赖

| 依赖 | 用途 | 缺失影响 |
|------|------|---------|
| Python 3.10+ + fastapi/uvicorn/httpx | 后端必需 | 无法启动 |
| Go 1.25（仅编译 PoW 时） | 本地编译 `pow-solver.exe` | 未编译则回退 Node/WASM 或纯 Python |
| Node.js 18+（可选） | WASM 回退（~18ms） | 未装则回退纯 Python（~16s） |

编译 Go 求解器（需本机安装 Go 工具链，仓库不含 `tools/`）：
```powershell
cd <项目根>/app/pow-go
go build -o pow-solver.exe main.go
.\pow-solver.exe --selftest
```

## 六、首次配置

打开 `http://127.0.0.1:20000` → 右上角**设置**：

1. 选择后端：
   - **官方 API**：填入 API Key（`platform.deepseek.com/api_keys` 申请），点「验证 Key」
   - **网页登录态**：填入 userToken。在已登录的 `chat.deepseek.com` 控制台执行
     `JSON.parse(localStorage.getItem('userToken')).value` 获取
2. 选择模型：`deepseek-flash` / `deepseek-v4-pro`
3. 配置增强功能开关
4. 点「保存设置」

配置存服务端 `app/data/settings.json`（不写入代码/文档），接口对前端脱敏。

## 七、文档索引

- 产品报告：`docs/01_DeepSeek产品分析报告.md`
- 增强设计：`docs/02_优化版设计说明.md`
- **PoW 方案定稿**：`docs/03_PoW方案讨论与定稿.md`（推荐阅读，含完整决策过程）
- SSE 解析测试案例库：`app/tests/测试案例库_SSE解析.md`
- 前端功能测试案例库：`app/tests/测试案例库_前端功能.md`
- 后端 API 与 Provider 测试案例库：`app/tests/测试案例库_后端API与Provider.md`
- 求解器与网页流程测试案例库：`app/tests/测试案例库_求解器与网页流程.md`
- **第三方质量检查报告（完整版）**：`app/tests/第三方质量检查报告.md`（工具选择理由/环境/案例/结果/问题清单/ESLint 引入说明）
- 开发记录：`.codebuddy/memory/2026-11-24.md`

### 回归测试与质量检查

一键第三方质量检查（Ruff + Bandit + 编译 + pytest + 覆盖率 + ESLint + JS 语法，退出码 0 才通过）：

```bat
cd <项目根>/app
run_quality_checks.bat
```

当前基线（2026-11-24）：`Ruff 0 error` / `Bandit 0 告警` / `ESLint 0 error 0 warning` / `120 用例 + 12 子测试全过` / `覆盖率 97%（阈值 90%）`。

按需单项运行：

```powershell
cd <项目根>/app
pip install ruff bandit coverage pytest pytest-subtests   # Python 第三方工具（首次）
cd frontend && npm install                                 # 前端 ESLint（首次）
cd ..
python -m pytest -q
python -m coverage report -m
cd frontend && npm run lint
python tests/verify_e2e.py   # 最小流量端到端验证（仅发 "hi"）
```

> **前端改动后看不到新界面？** 浏览器会强缓存静态 JS。请强制刷新（`Ctrl+F5`），或在地址栏 URL 后加 `?v=任意数字` 再访问。

## 八、数据来源

- UI 实测：ego-lite 继承登录态访问 `chat.deepseek.com`
- API 文档：`api-docs.deepseek.com/zh-cn`
- 官方演示：`github.com/deepseek-ai/chat-demo`
- PoW 方案：`github.com/Kaery40/ds2api`、`deepseek4free` 等开源实现

## 九、说明

- 网页登录态接口属非公开接口，可能变更；官方 API 更稳定合规
- 未配置 Key/Token 时对话返回明确错误，不会假装有回复
- 日志：`app/logs/deepseek_app.log`（按天轮转，保留 30 天）
- 端口：20000（绑定 127.0.0.1，仅本机访问）
