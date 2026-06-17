# Zero 重构设计报告

> 日期：2026-06-17 | 基于 v5 代码库分析

---

## 一、项目现状

### 1.1 基本信息

| 指标 | 值 |
|------|-----|
| Python 文件 | 83 个 |
| 类定义 | 120 个 |
| 函数定义 | 199 个 |
| 模块数 | 14 |
| 当前版本 | v5（原型阶段） |

### 1.2 当前架构图

```
zero_server.py :5052
    │
    ├── app/api/          → HTTP 层（aiohttp）
    ├── action/           → 执行层（Agent循环、注册表、18工具、看板、反思）
    ├── multi_agent/      → v5 核心（因果事件图、对抗式共识、分片流、合约）
    ├── cognition/        → 认知层（工作记忆、SQLite长期记忆、意图引擎）
    ├── perception/       → 感知层（文件监听、时钟、系统监控）
    ├── model_adapter/    → 模型适配（Agnes/DeepSeek/OpenAI/Ollama）
    ├── security/         → 安全守卫（暗号、行为指纹、越狱检测、沙箱）
    ├── semantic_gateway.py → 语义网关（L1硬阻断→L2标准化→L3软约束）
    ├── message_bus.py    → 事件总线 + 15态任务状态机
    └── interface/        → ChatGPT风格Web UI + Hermes React（备用）
```

### 1.3 现存问题

| 问题 | 严重程度 |
|------|----------|
| v4 和 v5 两套编排器并存，功能重叠互不调用 | **P0** |
| `agents.py` `blackboard.py` `consensus.py` `events.py` `orchestrator.py` 含大量重复 import/docstring | **P0** |
| 硬编码个人信息（"柳橙"、`E:\\project` 路径） | **P0** |
| 安全层默认关闭，感知层未接入编排器 | **P1** |
| 无跨会话记忆检索、无 Agent 通话记录持久化 | **P2** |
| 前端 1500+ 行内嵌 HTML/JS/CSS | **P2** |

---

## 二、定位：一个壳子的哲学

### 2.1 核心理念

Zero 是 **一个 AI Agent 编排系统内核（核），而不是一个装满功能的 AI 工具箱**。

它只做一件事：**接收用户目标 → 拆成步骤链 → 逐步执行 → 输出结果**。

用户拿到 Zero 的代码（从 GitHub clone），配好 API Key 就能跑。用户想接入自己的 AI 工具、社交账号、视频管线、本地模型——自己按接口接入。

### 2.2 项目分层

```
┌──────────────────────────────────────────┐
│            personal_config.json           │ ← 用户自己的配置（.gitignore）
│            .env                           │ ← 用户自己的密钥
├──────────────────────────────────────────┤
│  personal/                                │ ← 用户自己的实现
│    ├── tools/                             │
│    ├── adapters/                          │
│    └── workflow/                          │
├──────────────────────────────────────────┤
│  interfaces/                              │ ← 扩展点声明（接口）
│    ├── ipublisher.py                      │   社交发布
│    ├── ivideo_producer.py                 │   视频生产
│    ├── iskill_engine.py                   │   技能引擎
│    └── iextra_tool.py                     │   额外工具
├──────────────────────────────────────────┤
│  multi_agent/    action/    cognition/    │ ← 内核（不变，上传 GitHub）
│  message_bus/    security/  perception/   │
│  semantic_gateway/  model_adapter/       │
└──────────────────────────────────────────┘
```

- **上传 GitHub 的是内核 + interfaces**，不含 personal/ 和 personal_config.json
- **用户 git clone → 按需填入 personal_config → 零就变成自己的零**

---

## 三、单 Agent 流程链

### 3.1 核心概念

Zero 的核心能力是：**即使用户只有一个 LLM 模型，也能把任务拆成步骤链，让 Agent 一步步执行。**

```
用户输入: "帮我做一个响应式网站"
                     │
                     ▼
            ┌─────────────────────┐
            │   LLM 拆解步骤链      │
            │   (Planner 角色)     │
            └─────────┬───────────┘
                      │
          ┌───────────▼───────────┐
          │   step1: 写 HTML      │──→ 工具: write_file
          │   step2: 写 CSS       │──→ 工具: write_file
          │   step3: 写 JS        │──→ 工具: write_file
          └───────────┬───────────┘
                      │
          ┌───────────▼───────────┐
          │   同一个 LLM           │
          │   逐个执行每步          │
          │   (Executor 角色)      │
          └───────────┬───────────┘
                      │
          ┌───────────▼───────────┐
          │   Critic 审查结果      │→ 不通过则重试
          └───────────┬───────────┘
                      │
          ┌───────────▼───────────┐
          │   Synthesizer 整合     │
          │   输出最终答案          │
          └───────────────────────┘
```

### 3.2 关键设计

- **Planner/Executor/Critic/Synthesizer 是角色（role），不是 Agent 实例**
- 在单 Agent 模式下，四个角色共享同一个 LLM 调用，只是 system prompt 不同
- 每步执行的输出都会反馈给 Critic，Critic 通过后再进入下一步
- 前端通过 SSE 流实时展示步骤进度

### 3.3 当前代码差距

| 差距 | 需要改动的点 |
|------|-------------|
| `decompose()` 硬判关键词才拆 | 改为"用户所有请求都尝试拆步骤链" |
| 步骤链仅支持 v5 路径 | 合并 v4/v5 两条执行路径为一条 |
| Critic 依赖 LLM 额外调用 | 单 Agent 模式可用规则评分 + 简单校验 |

---

## 四、重构计划

### 4.1 改动量估算

| 阶段 | 新增文件 | 修改文件 | 预估行数 |
|------|----------|----------|----------|
| Phase 1：剥离个人信息 | 3 | 8 | ~300 |
| Phase 2：定义接口层 | 5 | 2 | ~200 |
| Phase 3：统一编排器 | 0 | 4 | ~150 |
| Phase 4：单 Agent 流程链 | 0 | 3 | ~100 |
| Phase 5：文档 | 2 | 1 | ~150 |

### 4.2 Phase 1：剥离个人信息到配置

改动目标：任何个人标识都不在代码中，全部读配置

| 文件 | 当前硬编码 | 改为 |
|------|-----------|------|
| `config.py:103-104` | `AGNES_API_URL` 固定值 | 环境变量 `AGNES_API_BASE`，默认保留当前值 |
| `config.py:30` | `E:\\project\\tools\\agent-system` 路径 | `config.json` 的 `extra_paths` |
| `agent_registry.py:278-280` | "柳橙（主人）" | `config.json` 的 `owner_name`，默认 "User" |
| `agent_registry.py:294-296` | "你叫 Reasonix" | 统一从配置读 |
| `guard.py` | 空用户字典 | 保持，用户自行配置 |
| `data/zero_config.json` | `watch_root: "E:\\project"` | 改为 `.` |
| `action/tools.py:369` | 龙虾 exec 保留 | 移到可配置块 |

### 4.3 Phase 2：定义接口/扩展点

新增 `interfaces/` 目录，定义 Zero 的插件接口：

```
interfaces/
├── __init__.py
├── ipublisher.py         # 社交发布接口
├── ivideo_producer.py    # 视频生产接口
├── iskill_engine.py      # 技能引擎接口
├── iextra_tool.py        # 自定义工具接口
└── istorage.py           # 存储后端接口（默认 SQLite）
```

每个接口的**默认实现是 no-op**。用户配置了 personal_config 后，系统自动注入真实实现。

接口设计示例：

```python
# interfaces/ipublisher.py
class PostResult(TypedDict):
    platform: str
    success: bool
    post_url: str | None
    error: str | None

class IPublisher(Protocol):
    def post(self, platform: str, content: str,
             media_paths: list[str] = []) -> PostResult: ...
    def list_platforms(self) -> list[str]: ...
    
class NullPublisher:
    """默认无操作发布器"""
    def post(self, *args, **kwargs) -> PostResult:
        return {"platform": "", "success": False, 
                "post_url": None, "error": "未配置发布器"}
    def list_platforms(self) -> list[str]: return []
```

### 4.4 Phase 3：统一编排器（v4 + v5 合并）

当前两条路径：

```
v4 路径: task_orchestrator.py → AgentRegistry → agent_loop.py
v5 路径: orchestrator.py → agents.py → blackboard.py + consensus.py
```

合并方案：**以 v5 的四角色架构为骨架，复用 v4 的 AgentRegistry 能力匹配**

```
统一编排器:
  run(task)
    → planner.propose()          # 拆步骤（v5）
    → registry.match()            # 匹配Agent（v4）
    → executor.execute()          # 执行（v5，实际调用 registry）
    → critic.review()             # 审查（v5）
    → consensus.evaluate()        # 共识（v5）
    → synthesizer.synthesize()    # 整合（v5）
```

### 4.5 Phase 4：单 Agent 流程链

在统一编排器上加一层"单 Agent"模式：

```python
class SingleAgentOrchestrator:
    """单 Agent 流程链：用户只有一个 LLM，拆成步骤链执行"""
    
    def run(self, task: str, llm_caller) -> dict:
        # 1. 拆步骤
        steps = self._decompose(task, llm_caller)
        
        # 2. 逐步执行（同一 LLM，切换 system prompt）
        for step in steps:
            step_result = llm_caller(executor_prompt(step))
            review = llm_caller(critic_prompt(step, step_result))
            if not review.passed:
                step_result = llm_caller(executor_prompt(step, feedback=review))
            results.append(step_result)
        
        # 3. 整合输出
        return llm_caller(synthesizer_prompt(task, results))
```

### 4.6 Phase 5：文档和示例

```
.env.example              # 告诉用户要配什么
personal_config.example.json  # 完整的配置示例（值全为空）
README.md                 # 壳子哲学 + 快速开始 + 个性化指南
```

---

## 五、个性化资产接入指南

以下是你的 CREDENTIALS.md 资产如何接入 Zero 的清单，也是用户拿到 Zero 后需要做的事。

| 资产 | 接入方式 | 用户需要做的 |
|------|----------|-------------|
| **LLM API**（Agnes/DeepSeek/Crow5） | 环境变量 | 填 API Key |
| **11 社交平台** | 实现 `IPublisher` | 在 `personal_config` 填 cookie/token |
| **MoneyPrinterTurbo** | 实现 `IVideoProducer` | 配 MPT 地址 + Pexels Key |
| **NewsFactory** | Zero 消息总线下游 | 配路径和 cron 表达式 |
| **Playwright / Browser Use** | 注册为 `browser_control` 工具 | 安装依赖 |
| **Darbot Windows** | 注册为 `desktop_control` 工具 | 安装 npm 包 |
| **muapi Skills** | 实现 `ISkillEngine` | 配 muapi API Key |
| **Pexels / Tavily / QQ 邮箱** | 环境变量 | 填 API Key/密码 |
| **Ollama** | `model_adapter/ollama.py` 已有 | 配 base_url |

---

## 六、Token 成本控制策略

### 6.1 问题

用户直接用 DeepSeek API 和自己跑 Zero 花的是同样的 token 费用。凭什么用 Zero 比直接调 LLM 更省？

### 6.2 三层节省策略

```
层1：上下文压缩（零成本，立即生效）
  ├── 历史对话不全文传递，只传摘要（当前已实现）
  ├── 步骤链中每步只传递增量上下文，不重复传前面步骤的输出
  ├── 系统 prompt 缓存，仅在切换 Agent 角色时重建
  └── 工作记忆裁剪：超过 2000 chars 的上下文自动截断

层2：LLM 响应缓存（中等成本，效果显著）
  ├── key = hash(provider + model + messages + temperature)
  ├── 同一 prompt 在同一会话中重复命中 → 直接从缓存返回
  ├── 跨会话共享（SQLite 持久化），相同任务可复用
  └── TTL 过期 + LRU 淘汰（默认 1000 条，1 小时）

层3：前端透明展示
  ├── 底部状态栏实时展示：总Tokens / 总花费 / 缓存命中率
  ├── 每次 LLM 调用在侧边栏记录明细（Agent名 + 用量 + 缓存标记）
  └── 可选月预算设置，超限自动降级到免费模型
```

### 6.3 用户感知到的差异

| 场景 | 直接调 LLM | 通过 Zero |
|------|-----------|-----------|
| 连续对话（10 轮） | 每轮全量传历史，~8000 tokens | 只传摘要，~1500 tokens |
| 重复请求（同 prompt） | 每次收费 | 缓存命中，0 成本 |
| 多 Agent 协作（4 角色） | N/A | 角色间共享上下文，不重复传 |
| 长步骤链（5 步） | 一次传全量 | 每步只传增量 |

### 6.4 当前实现状态

- [x] `cognition/token_tracker.py` — 实时追踪器，记录每次 LLM 调用的 token 和成本
- [x] `/api/tokens` + `/api/tokens/recent` — 前端 API 端点
- [x] 底部状态栏实时展示 Tokens / 花费 / 缓存率
- [x] LLM 响应缓存（key=prompt hash 的内存缓存，同 session 内相同 prompt 零成本返回）
- [ ] 步骤链上下文增量传递
- [ ] 月预算限制 + 自动降级

---

## 七、技术指标

| 指标 | 当前 | 目标 |
|------|------|------|
| 启动步骤数 | 1（填 API Key） | 1（填 API Key） |
| 个性化配置格式 | 无 | `personal_config.json` |
| 单 Agent 流程链 | 有雏形但双轨 | 统一入口，步步骤可见 |
| 扩展点 | 无 | 5 个接口 + 默认 no-op |
| GitHub 安全性 | 含个人信息 | 零个人信息 |
| 用户从 clone 到能用 | 30 分钟（需改代码） | 3 分钟（填 .env） |

---

## 七、路线图

```
Phase 1（立即）
  ├── 剥离 config.py 所有个人信息到环境变量
  ├── agent_registry.py prompt 通用化
  ├── 新增 .env.example 和 .gitignore 条目
  └── data/zero_config.json 默认值通用化

Phase 2（紧接着）
  ├── 创建 interfaces/ 目录（定义扩展点）
  ├── 合并 v4/v5 编排器路径
  ├── 实现 SingleAgentOrchestrator
  └── 更新 README（壳子哲学 + 快速开始）

Phase 3（并行）
  ├── 创建 personal/seed.py（你的个性化注入）
  ├── 创建 personal/tools/（社交发布、MPT、NewsFactory）
  └── 创建 personal_config.example.json

Phase 4（后续）
  ├── 完整测试套件
  ├── Docker 依赖完善
  ├── 前端拆分（独立项目或静态文件）
  └── 性能监控仪表板
```

---

## 八、总结

Zero 的核心价值不是"有什么工具"，而是 **"拆步骤链"的编排能力**——单 Agent 和多 Agent 的流程是一样的，只是背后用几个 LLM 实例的区别。

重构的核心动作只有三个：

1. **代码不留个人信息**（config + prompt）
2. **定义扩展点**（interfaces/）
3. **合并 v4/v5 两条路径**（统一编排器）

剩下的就是把 CREDENTIALS.md 里的资产以插件形式注入，这个只对你本地的 `personal/` 目录有意义，不会上传 GitHub。
