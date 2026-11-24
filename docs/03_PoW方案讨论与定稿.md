# PoW 技术详解与求解方案定稿

> 日期：2026-11-23
> 背景：网页登录态 Provider 每次对话前需求解 DeepSeekHashV1 PoW 挑战，纯 Python 实现耗时约 16 秒，严重拖慢体验
> 结论：采用 **Go 纯算**（约 13ms），Node/WASM 与纯 Python 作为回退

---

## 一、PoW（工作量证明）技术详解

### 1.1 什么是 PoW

**PoW（Proof of Work，工作量证明）** 是一种"证明者提交了足够计算工作"的机制：服务端出一个**题目**，客户端必须消耗**真实算力**找到一个**答案**，服务端能极快地验证答案正确性，但客户端求解需要付出成本。

核心特征（也是它区别于其他机制的关键）：

| 特性 | 含义 |
|------|------|
| **求解难、验证易** | 找到答案需要大量尝试；验证只需一次哈希 |
| **成本不对称** | 请求方付出 CPU 时间，服务方几乎零成本 |
| **可公开验证** | 答案附带完整参数，任何人可复算确认 |

### 1.2 历史渊源

- **1997 Hashcash**：Adam Back 提出，用 PoW 抵御垃圾邮件——每封邮件附带一个"邮资"哈希，发信要算，收信秒验
- **2008 Bitcoin**：中本聪把 PoW 用作共识机制，"挖矿"就是寻找满足前导零数量的 nonce
- **近年反爬场景**：Cloudflare Turnstile、 various API 用轻量级 PoW 作为"无感验证"，替代 CAPTCHA

### 1.3 通用数学模型

```
服务端：随机选 target，难度 D
客户端：找 nonce ∈ [0, D)，使 H(challenge || nonce) 满足目标条件
验证端：计算一次 H(challenge || nonce)，比对即可
```

- 哈希函数 H 需**抗碰撞、快速、确定性**
- 难度 D 控制期望计算量：D 越大，平均要试 D/2 次
- 答案不可复用：challenge 带时间戳/签名，过期作废

### 1.4 DeepSeek 的具体实现：DeepSeekHashV1

DeepSeek 网页端把 PoW 用作**反自动化**手段。协议流程：

```
1. POST /api/v0/chat/create_pow_challenge
   ← {algorithm:"DeepSeekHashV1", challenge, salt, signature,
      difficulty:144000, expire_at, target_path}

2. 客户端求解：
   prefix = f"{salt}_{expire_at}_"
   找 answer ∈ [0, difficulty)，使
   DeepSeekHashV1(prefix + str(answer)) == challenge

3. 构造 x-ds-pow-response 请求头：
   base64(json({algorithm, challenge, salt, answer, signature, target_path}))

4. POST /api/v0/chat/completion（带该 header）
```

**DeepSeekHashV1 算法本质**：
- = SHA3-256 但 **Keccak-f[1600] 跳过 round 0**（只执行 rounds 1..23）
- rate=136 字节，padding `0x06...0x80`，输出 32 字节
- 把哈希算法编译进 WASM 字节码（官方前端），增加逆向门槛

**三层设计意图**（业界分析）：
| 目标 | 机制 |
|------|------|
| 防脚本批量请求 | 每次请求要真实算力，暴力调用成本剧增 |
| 防重放 | signature 签名 + expire_at（5 分钟）过期 |
| 防逆向 | 哈希算法藏于 WASM，非明文 JS |

### 1.5 PoW 的优缺点

#### 优点

| 优点 | 说明 | 在 DeepSeek 场景的体现 |
|------|------|----------------------|
| **提高滥用成本** | 每个请求都要付出计算量，批量刷接口成本线性上升 | 防止脚本海量调用免费网页接口 |
| **验证极廉价** | 服务端一次哈希即可验真 | 不增加服务端显著负担 |
| **无需用户交互** | 不同于 CAPTCHA，用户无感知 | 正常网页用户无感，体验好 |
| **抗女巫攻击** | 身份可伪造，算力难伪造 | 限制单 IP 批量注册账号刷量 |
| **实现简单** | 协议清晰、库支持广 | 官方用 WASM 封装，客户端调用即可 |
| **难度可调** | 改 difficulty 即可调节防护强度 | 可按负载动态调整 |

#### 缺点

| 缺点 | 说明 | 在 DeepSeek 场景的体现 |
|------|------|----------------------|
| **能耗浪费** | 求解本身不产生业务价值，纯耗电 | 每次对话额外耗 CPU；这也是比特币被诟病的点 |
| **客户端性能差异大** | 弱设备/低端机求解慢 | 纯 JS 实现在手机上明显卡顿（官方用 WASM 缓解） |
| **不能真正阻止确定攻击者** | 只是提高成本，非绝对防护 | 有决心者可用 GPU/集群碾压，开源求解器众多 |
| **增加延迟** | 求解时间叠加到请求链路 | 本项目的核心痛点：纯 Python 求解 16 秒 |
| **逆向后防护失效** | 算法公开后可本地高速求解 | 本文用 Go 13ms 求解即为例证 |
| **公平性问题** | 强设备用户反而占优 | 移动端用户体验差于 PC |
| **无法防御凭证泄露** | PoW 不验证身份真伪 | token 泄露后攻击者照样能求解 |

#### 客观评价

PoW 在 DeepSeek 场景中是**合理的"成本围栏"而非安全边界**：
- 它有效劝退"低成本脚本刷量"（最常见威胁）
- 它无法阻止"有凭证 + 有算力"的深度滥用
- 对正常用户几乎无感（官方 WASM + 现代设备 37ms 内完成）
- 真正的风险在 token 管理和接口变更，不在 PoW 本身

---

## 二、问题陈述（本项目的痛点）

DeepSeek 网页端私有接口在 `/api/v0/chat/completion` 前要求 PoW 验证（流程见 1.4）。典型 `difficulty=144000`，即最多需计算 144000 次哈希。我最初用纯 Python 实现 Keccak-f[1600]（跳过 round 0），实测：

```
PoW 求解：约 16 秒
端到端对话：24.8 秒（其中 PoW 占 65%）
```

---

## 三、方案调研（网上先进方案）

调研了 deepseek4free、ds2api、deepseek2api、deepseek-webgui skill、freeseek 等主流开源方案，结论一致：**没人用纯 Python 算 PoW**。

| 方案 | 代表项目 | 机制 | 实测耗时（difficulty=144000） |
|------|---------|------|------------------------------|
| 官方 WASM | deepseek4free / deepseek2api / deepseek-webgui | Python 驱动 `sha3_wasm_bg.wasm` | 约 37.5ms（wazero 反推） |
| **Go 纯算** | **ds2api** | 纯 Go 实现 Keccak-f，0 alloc | **13.4ms** |
| Node + WASM | Fly143/deepseek-free-api | Node 子进程调预编译 WASM | 秒级（含进程启动） |
| 纯 Python | 我的初版 | 纯 Python Keccak | 16000ms |

权威性能数据（ds2api README，Apple M4 / Go 1.25）：

```
BenchmarkHash-8     187.5 ns/op    0 alloc   5.33M hash/s
BenchmarkSolve-8    13.4 ms/op     2 alloc   75 道/秒/核
```

结论：**Go 纯算比 WASM 快 2.8 倍**，是公开方案中最快的。

---

## 四、走过的弯路（失败尝试记录）

### 4.1 纯 Python 扁平化优化 —— 失败
尝试把 state 从 5×5 嵌套列表改为扁平 25-lane 数组以加速。结果：
- 4 个官方测试向量**全部 FAIL**（pi 置换映射写错）
- 耗时反而从 16s 增至 44s
- **已回退**

**教训**：哈希算法的任何优化必须先通过测试向量验证，否则会引入静默错误。

### 4.2 Node/WASM 方案 —— 可用但非最优
安装 `@rezaparsian/deepseek-pow-solver`（零依赖、预编译官方 WASM 26KB），端到端从 24.8s 降到 2.18s。这是第一次成功加速，但用户指出 Go 更快，于是继续优化。

---

## 五、定稿方案：三级回退链

```
solve_pow()
   ├─ 方案一：Go 纯算（pow-go/pow-solver.exe）    ~13ms   ← 默认
   ├─ 方案二：Node + 官方 WASM（pow-node/）        ~18ms   ← Go 缺失时
   └─ 方案三：纯 Python（pow_solver.py 内）        ~16s    ← 无外部依赖时
```

### 5.1 Go 求解器实现

- 源码：`app/pow-go/main.go`
- 算法：DeepSeekHashV1 = Keccak-f[1600] 跳过 round 0，rate=136，padding 0x06...0x80
- 接口：stdin 读 challenge JSON → stdout 输出 payload JSON
- 自测：`pow-solver.exe --selftest` 用 4 个官方测试向量验证
- 编译：Go 1.25，`go build -o pow-solver.exe main.go`（二进制约 2.9MB，已随项目提供）

### 5.2 Python 侧集成

- `config.py`：`POW_GO_BINARY`、`POW_NODE_SCRIPT`、`POW_SUBPROCESS_TIMEOUT`
- `pow_solver.py`：`solve_pow()` 按 Go → WASM → Python 顺序尝试，任一成功即返回
- 子进程用 `input=json.dumps(ch).encode('utf-8')` 传参（Python subprocess 无 BOM 问题）

### 5.3 关于 BOM 兼容

PowerShell 管道会加 BOM（甚至 UTF-16LE），曾在测试时误判为程序 bug。实际生产路径是 Python subprocess（纯 UTF-8），无此问题。Go 源码仍保留了 BOM 兼容处理（FF FE / EF BB BF），增强健壮性。

---

## 六、验证结果

### 6.1 正确性（同一 challenge 三种实现交叉验证）

| 实现 | answer | 测试向量 |
|------|--------|---------|
| 纯 Python | 41806 | 4/4 PASS |
| Node/WASM | 41806 | — |
| **Go** | **41806** | **4/4 PASS** |

### 6.2 性能（端到端真实对话，发送 "hi"）

| 阶段 | 耗时 |
|------|------|
| 初版（纯 Python PoW） | 24.8 秒 |
| WASM 方案 | 2.18 秒 |
| **Go 方案（定稿）** | **1.26 秒** |

剩余 1.26 秒为网络往返 + DeepSeek 服务端响应时间，PoW 已完全不是瓶颈。

### 6.3 编译与回归

- `python -m py_compile`：全部 PASS
- `node --check`：PASS
- Go `go build`：PASS，`--selftest` PASS
- 模块导入、服务健康检查：PASS
- 端到端真实对话：PASS（真实返回 "Hello!"）

---

## 七、依赖与部署说明

| 依赖 | 用途 | 缺失影响 |
|------|------|---------|
| Go 1.25（仅编译时） | 编译 `pow-solver.exe` | 二进制已随项目提供，运行时无需 Go |
| `pow-go/pow-solver.exe` | 默认 PoW 求解 | 自动回退到 Node/WASM 或纯 Python |
| Node.js 18+（可选） | WASM 回退 | 自动回退到纯 Python |
| 无外部依赖 | 纯 Python 回退 | 始终可用，但慢 |

**重新编译 Go 求解器**（如需修改算法）：

Go 工具链已随项目放在 `tools/go/`（go1.25.5，约 200MB），无需系统安装：

```powershell
$env:GOROOT = "<项目根>/tools/go"
cd <项目根>/app/pow-go
& "<项目根>/tools/go/bin/go.exe" build -o pow-solver.exe main.go
.\pow-solver.exe --selftest
```

---

## 八、为什么最终选 Go（回答用户提问）

用户问："为何不能用 Go，Go 的用时最少。"

答复：
1. **用户是对的**——Go 确实最快（13.4ms vs WASM 18ms vs Python 16s）。
2. 我上一轮选 WASM 是因为本机已有 Node.js、安装即用，属于"最快落地"而非"最优性能"的取舍，并非 Go 不可用。
3. 本轮按用户要求改用 Go 纯算，并保留 WASM/Python 两级回退，兼顾性能与健壮性。
4. 实测端到端从 WASM 的 2.18s 进一步降到 1.26s。

---

## 九、参考来源

- Adam Back, Hashcash (1997) — PoW 雏形
- ds2api `pow/README.md` — DeepSeekHashV1 算法细节与 Go 性能基准
- i3t2y/ds-free-api `docs/deepseek-api-reference.md` — 接口字段与 SSE 格式
- GitCode 博客《DeepSeek 反爬 PoW 验证如何绕过》— 三层设计意图分析
- deepseek4free / deepseek2api / deepseek-webgui — WASM 求解实践
