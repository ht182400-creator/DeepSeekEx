# 后端 API 与 Provider 测试案例库

- 被测模块：`app/main.py`（FastAPI 路由）、`app/providers.py`（Provider 辅助函数与模拟网络调用）
- 测试脚本：
  - `app/tests/test_main.py`（API 集成测试，FastAPI TestClient，配置重定向到临时目录）
  - `app/tests/test_provider_helpers.py`（Provider 纯函数 + mock httpx）
- 运行命令：`cd app && python -m pytest tests/test_main.py tests/test_provider_helpers.py -q`
- 第三方标准：pytest + coverage（见 `tests/第三方质量检查报告.md`）

## 一、main.py API 集成测试（TC-M01 ~ TC-M30）

| 编号 | 功能 | 输入/操作 | 预期结果 | 实测 |
| --- | --- | --- | --- | --- |
| TC-M01 | 健康检查 | GET /api/health | status=ok, HTTP 200 | PASS |
| TC-M02 | 首次加载配置 | GET /api/settings（无文件） | 写入默认配置，api_key/web_token 脱敏为空 | PASS |
| TC-M03 | 凭据脱敏 | 保存 api_key=secret-key 后 GET | api_key_set=true 但 api_key="" | PASS |
| TC-M04 | 旧字段迁移 | 保存 enhancements.context_meter=false 后加载 | context=false，旧字段被移除 | PASS（发现并修复遮蔽 bug） |
| TC-M05 | 配置损坏回退 | 写入非法 JSON 后 GET | 回退默认配置不崩溃 | PASS |
| TC-M06 | 正常更新配置 | POST model=deepseek-v4-pro | 保存成功，字段生效 | PASS |
| TC-M07 | 空字符串跳过 | POST api_key="  ", model="" | 已有值保持不变 | PASS |
| TC-M08 | 增强开关合并 | POST enhancements.focus_mode=false | focus_mode=false，split_view 仍 true | PASS |
| TC-M09 | 配置写失败 | mock save_settings 抛异常 | HTTP 500，ok=false | PASS |
| TC-M10 | 原子写成功 | _atomic_write_json 正常调用 | 文件内容正确，无 .tmp 残留 | PASS |
| TC-M11 | 原子写失败清理 | mock json.dump 抛异常 | 清理 .tmp 并向上抛 OSError | PASS |
| TC-M12 | 创建并列出会话 | POST /api/chats title=测试会话 | 返回完整字段，列表首位 | PASS |
| TC-M13 | 更新会话 | PUT 改 title 与 messages | 字段更新生效 | PASS |
| TC-M14 | 更新不存在会话 | PUT /api/chats/not-exist | HTTP 404 | PASS |
| TC-M15 | 删除会话 | DELETE 会话 id | ok=true，clear_web_session 被调用一次 | PASS |
| TC-M16 | 脏数据删除 | 会话库含无 id 项时删除 | 不崩溃，ok=true | PASS |
| TC-M17 | 会话库损坏 | 写入非法 JSON 后 GET | 返回空列表 | PASS |
| TC-M18 | 创建会话写失败 | mock save_chats 抛异常 | HTTP 500 | PASS |
| TC-M19 | 删除会话写失败 | mock save_chats 抛异常 | HTTP 500 | PASS |
| TC-M20 | 官方凭据验证成功 | mock validate 返回 (True, 有效) | ok=true | PASS |
| TC-M21 | 未知 provider | POST provider=unknown_provider | ok=false，友好提示 | PASS |
| TC-M22 | 验证异常 | mock create_provider 抛 OSError | ok=false，含异常信息 | PASS |
| TC-M23 | 空凭据用已保存配置 | 保存 api_key 后 POST 空 api_key | create_provider 收到 saved-key | PASS |
| TC-M24 | 空消息 | POST messages=[] | HTTP 400 | PASS |
| TC-M25 | 正常 SSE 流 | mock provider 产出两个事件 | 返回 SSE 事件与 [DONE] | PASS |
| TC-M26 | 流式异常 | mock provider 抛异常 | SSE 含 error 事件与 [DONE] | PASS |
| TC-M27 | 创建 provider 失败 | mock 抛 ProviderError | HTTP 500 | PASS |
| TC-M28 | chat_id 透传 | POST 带 chat_id=chat-123 | provider 收到该 chat_id | PASS |
| TC-M29 | PoW 自检 | POST /api/pow/verify | ok=true | PASS |
| TC-M30 | 首页 | GET / | text/html 200 | PASS |

## 二、Provider 单元测试（TC-P01 ~ TC-P30）

| 编号 | 功能 | 输入/操作 | 预期结果 | 实测 |
| --- | --- | --- | --- | --- |
| TC-P01 | 正文增量解析 | OpenAI SSE content delta | {type:content, text:你好} | PASS |
| TC-P02 | 思考内容解析 | reasoning_content 字段 | {type:thinking} | PASS |
| TC-P03 | 思考别名解析 | reasoning 字段 | {type:thinking} | PASS |
| TC-P04 | 结束事件 | finish_reason=stop | {type:done} | PASS |
| TC-P05 | Anthropic 思考 | thinking_delta | {type:thinking} | PASS |
| TC-P06 | Anthropic 正文 | text_delta | {type:content} | PASS |
| TC-P07 | 未知 Anthropic delta | delta.type=unknown | None | PASS |
| TC-P08 | DONE/空事件 | data:[DONE] / 无 data | None | PASS |
| TC-P09 | 无 choices/非法 JSON | 缺字段 / bad json | None | PASS |
| TC-P10 | 解析异常 | delta 非字典 | None 不崩溃 | PASS |
| TC-P11 | 标准错误解析 | error.message 结构 | 返回错误消息 | PASS |
| TC-P12 | 错误缺 message | error={} | 回退原文 | PASS |
| TC-P13 | 非法 UTF-8 错误体 | 0xff 0xfe 字节 | 返回字符串不崩溃 | PASS |
| TC-P14 | 引用字段兼容 | title/name/document_title 等 | 4 条规范化，缺失留空 | PASS |
| TC-P15 | 非字典引用跳过 | 字符串/None/数字 | 仅保留字典项 | PASS |
| TC-P16 | 片段索引解析 | fragments/1、fragments/-1 | 1 / 最大索引 | PASS |
| TC-P17 | 空引用列表 | [] | [] | PASS |
| TC-P18 | 空 Key 验证 | validate("") | ok=false 提示填入 | PASS |
| TC-P19 | 官方验证成功 | mock HTTP 200 | ok=true | PASS |
| TC-P20 | 官方验证 401 | mock HTTP 401 | ok=false 提示无效 | PASS |
| TC-P21 | 官方验证 500 | mock HTTP 500 | ok=false 含状态码 | PASS |
| TC-P22 | 官方验证网络异常 | mock ConnectError | ok=false 含异常信息 | PASS |
| TC-P23 | 流式无 Key | stream_chat("") | error 事件 | PASS |
| TC-P24 | 流式超时 | mock TimeoutException | error 事件含"超时" | PASS |
| TC-P25 | 流式 HTTP 错误 | mock HTTP 500 + error body | error 事件含错误消息 | PASS |
| TC-P26 | 正常流式 | 3 个 SSE chunk | thinking/content/done 三类事件 | PASS |
| TC-P27 | 搜索请求体 | stream_chat(search=True) | payload 含 tools 字段 | PASS |
| TC-P28 | 工厂 official | create_provider("official") | OfficialProvider 实例 | PASS |
| TC-P29 | 工厂 web | create_provider("web") | WebProvider 实例 | PASS |
| TC-P30 | 工厂未知类型 | create_provider("unknown") | 抛 ProviderError | PASS |

## 三、SSE patch 数据驱动案例

见 `测试案例库_SSE解析.md`（TC01 ~ TC11，12 个 subtests）。

## 四、日志与证据

- pytest 日志：控制台输出 + `app/tests/logs/` 下按时间戳的测试日志
- 覆盖率报告：`app/tests/coverage.xml`
- 统一检查报告：`app/tests/第三方质量检查报告.md`
