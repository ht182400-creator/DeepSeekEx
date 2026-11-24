# SSE JSON patch 解析测试案例库

被测函数：`app/providers.py` 中 `WebProvider._parse_patch_event(event: str) -> List[Dict[str, Any]]`

- 数据驱动文件：`app/tests/test_patch_cases.json`
- 测试脚本：`app/tests/test_providers.py`
- 测试日志：`app/tests/logs/test_YYYYMMDD_HHMMSS.log`（每次运行新建，ERROR 红色标记未通过用例）
- 运行命令：`cd app && python -m unittest tests.test_providers -v`

## 解析规则说明

网页端 completion 返回的 SSE 事件体为 JSON patch，解析后产出的事件字典类型有三类：

| 输出 type | 含义 | 前端行为 |
| --- | --- | --- |
| `thinking` | 思考片段内容 | 追加到思考面板 |
| `content` | 正文片段内容 | 追加到回复正文 |
| `done` | 完成信号 | 结束渲染 |

分流依据：`_fragment_types[索引]` 记录每个 fragment 是 `THINK` 还是 `RESPONSE`；续传事件 `{"v":"..."}` 无 `p` 字段时追加到最后一个 fragment。

## 案例一览

| 编号 | 名称 | 输入事件数 | 预期输出事件数 |
| --- | --- | --- | --- |
| TC01 | 初始化快照含 THINK 与 RESPONSE 双 fragment | 1 | 2 |
| TC02 | 续传事件无 p 字段默认 RESPONSE | 1 | 1 |
| TC03 | 指定索引 content 追加 | 1 | 1 |
| TC04 | 追加新 fragment 含 content | 1 | 1 |
| TC05 | 完成状态事件 FINISHED | 1 | 1 |
| TC06 | 空事件 | 1 | 0 |
| TC07 | DONE 哨兵 | 1 | 0 |
| TC08 | 非法 JSON | 1 | 0 |
| TC09 | 完整流：思考续传后切换正文续传（截断回归） | 5 | 5 |
| TC10 | 思考耗时 elapsed_secs 更新事件 | 1 | 1 |
| TC11 | 初始化快照透传会话ID/搜索状态/引用来源 | 1 | 6 |
| TC12 | fragment 整体回传（无 op）提取耗时与引用 | 1 | 2 |

> TC10-12 基于真实抓包的字段结构（`elapsed_secs`/`references`/`search_triggered`），用于支撑思考耗时、web pages 徽章、引用来源卡三项 UI，所有数据来自后端真实字段，不造假。

## 案例详情（输入/输出一一对应）

### TC01 初始化快照含 THINK 与 RESPONSE 双 fragment

- 输入：
  ```text
  data: {"v":{"response":{"fragments":[{"type":"THINK","content":"让我思考"},{"type":"RESPONSE","content":"你好"}]}}}
  ```
- 预期输出：
  ```json
  [{"type": "thinking", "text": "让我思考"}, {"type": "content", "text": "你好"}]
  ```
- 说明：修复前只返回第一个非空 fragment，会丢失正文；修复后快照中每个 fragment 均输出。

### TC02 续传事件无 p 字段默认 RESPONSE

- 输入：`data: {"v":"世界"}`
- 预期输出：`[{"type": "content", "text": "世界"}]`
- 说明：DeepSeek 流式输出的主要格式，无 `p` 字段时追加到最后一个 fragment。

### TC03 指定索引 content 追加

- 输入：`data: {"p":"response/fragments/0/content","o":"APPEND","v":"补充内容"}`
- 预期输出：`[{"type": "content", "text": "补充内容"}]`

### TC04 追加新 fragment 含 content

- 输入：`data: {"p":"response/fragments","o":"APPEND","v":[{"type":"RESPONSE","content":"新片段"}]}`
- 预期输出：`[{"type": "content", "text": "新片段"}]`

### TC05 完成状态事件 FINISHED

- 输入：`data: {"p":"response/status","o":"SET","v":"FINISHED"}`
- 预期输出：`[{"type": "done"}]`

### TC06 空事件

- 输入：`""`
- 预期输出：`[]`

### TC07 DONE 哨兵

- 输入：`data: [DONE]`
- 预期输出：`[]`

### TC08 非法 JSON

- 输入：`data: {not json`
- 预期输出：`[]`
- 说明：JSON 解析异常被捕获，返回空列表，不中断流。

### TC09 完整流：思考续传后切换正文续传（截断回归）

- 输入（顺序喂入，fragment 状态累积）：
  ```text
  data: {"v":{"response":{"fragments":[{"type":"THINK","content":"分析"}]}}}
  data: {"v":"过程"}
  data: {"p":"response/fragments","o":"APPEND","v":[{"type":"RESPONSE","content":"我无法"}]}
  data: {"v":"提供此类信息"}
  data: {"v":"，但可以帮助你"}
  ```
- 预期输出：
  ```json
  [
    {"type": "thinking", "text": "分析"},
    {"type": "thinking", "text": "过程"},
    {"type": "content", "text": "我无法"},
    {"type": "content", "text": "提供此类信息"},
    {"type": "content", "text": "，但可以帮助你"}
  ]
  ```
- 说明：模拟用户截图"回复只有我无法"的场景。修复前续传事件被忽略，只留下初始化片段"我无法"；修复后两段续传正文完整输出，且思考与正文分流正确。

### TC10 思考耗时 elapsed_secs 更新事件

- 输入：`data: {"p":"response/fragments/-1/elapsed_secs","o":"SET","v":1.403554815}`
- 预期输出：`[{"type": "thinking_elapsed", "seconds": 1.403554815}]`
- 说明：真实抓包字段，思考面板显示"思考耗时 X.X 秒"的数据来源。

### TC11 初始化快照透传会话ID/搜索状态/引用来源

- 输入：
  ```text
  data: {"v":{"response":{"message_id":2,"search_triggered":true,"fragments":[{"type":"THINK","content":"搜索中","elapsed_secs":2.5,"references":[{"title":"官网","url":"https://example.com","snippet":"示例"}]},{"type":"RESPONSE","content":"答案"}]}}}
  ```
- 预期输出：
  ```json
  [
    {"type": "session_meta", "message_id": 2},
    {"type": "search_state", "triggered": true},
    {"type": "thinking", "text": "搜索中"},
    {"type": "thinking_elapsed", "seconds": 2.5},
    {"type": "sources", "items": [{"title": "官网", "url": "https://example.com", "snippet": "示例"}]},
    {"type": "content", "text": "答案"}
  ]
  ```
- 说明：`message_id`（AI 回复 ID，真实抓包字段）驱动 `session_meta`，用于网页端多轮上下文串接（下一轮作 `parent_message_id`）；`search_triggered` 驱动 web pages 徽章，`references` 驱动引用来源卡。`session_meta` 由 provider 内部捕获，不转发给前端。

### TC12 fragment 整体回传（无 op）提取耗时与引用

- 输入：
  ```text
  data: {"p":"response/fragments","v":[{"type":"THINK","content":"思考完成","elapsed_secs":3.2,"references":[{"title":"来源A","url":"https://a.com"}]},{"type":"RESPONSE","content":"回复"}]}
  ```
- 预期输出：
  ```json
  [
    {"type": "thinking_elapsed", "seconds": 3.2},
    {"type": "sources", "items": [{"title": "来源A", "url": "https://a.com", "snippet": ""}]}
  ]
  ```
- 说明：思考结束时后端会把所有 fragment 完整回传一次（无 `o` 字段），此处只提取耗时与引用，正文内容此前已由续传事件逐个输出，避免重复。`snippet` 缺失时留空，不造假。
