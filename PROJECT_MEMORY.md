# 零 v5 · 项目记忆
> 最后更新: 2026-06-18

## v6 重构（当前进度：完成 10/10 项任务 + 2 项新增 + 8 项 P3/P4/P5 扩展）
> P0-3 和 P3-2 为会话中新增任务
> 
> 本轮会话（2026-06-17~18）新增 8 项：
> - 完整测试套件（110 测试，6 模块覆盖）
> - Docker 依赖完善（requirements.txt + .dockerignore + Dockerfile 改进）
> - Agent @ 协作改进（用户输入 @ + LLM 回复 @ 均保留上下文）
> - 文件上传/下载 API
> - 定时任务接入编排器
> - 多轮迭代（"再改/不够好/重新"触发）
> - 前端拆分 + 极简 UI 重构（webapp 内嵌 HTML/JS/CSS → 独立文件；全 UI 改造：圆角气泡/呼吸灯/A-gent 状态/思考折叠/代码折叠/SSE 重连/重试/超时/灯箱 Escape/多标签同步/草稿保存/键盘适配）
> - 前端全面 Bug 修复与体验优化（80+ 项审计修复）

## v5 核心升级：壳子加固（模型无关的 Agent Runtime）

### 新增模块
- `utils/result.py` — 统一错误协议（Result + ErrorInfo + ErrorCode）
- `model_adapter/` — 模型适配器层（DeepSeek/Agnes/OpenAI/Ollama）
- `data/zero_config.json` — 认证可配置，默认关闭暗号

### 关键改动
- `action/tools.py` — 全部 18 个工具返回统一 Result 信封
- `action/agent_registry.py` — 新增 ProficiencyTracker 权重评估系统
- `action/reviewer.py` — 双轨评分（规则 60% + LLM 40%）
- `action/task_orchestrator.py` — _call_agent 返回 Result，修复 executor 参数不匹配
- `cognition/working_memory.py` — 加 threading.Lock 并发安全
- `security/guard.py` — 认证从 hardcode 改为配置文件驱动 + lock() 持久化
- `zero_server.py` — _handle_file_op 适配 Result 协议
- `gpt_tools.py` — secure_config 导入容错

### 修复的 9 个 Bug
1. task_orchestrator executor 参数不匹配（缺 extra）→ TypeError
2. executor 返回字符串被当 dict 调 .get() → AttributeError
3. working_memory.flush 调不存在的方法 → AttributeError
4. reflection.py 三个方法名错误 → 每日反思崩溃
5. SessionManager.lock 不持久化 → 重启丢失锁状态
6. gpt_tools secure_config 导入无容错
7. SSE handler 裸 except: pass 吞真异常
8. file_watcher OSError 不区分类型
9. intent_engine 裸 except 捕获 KeyboardInterrupt

## 项目位置
- 主项目: E:\project\tools\zero\
- 旧系统: E:\project\tools\agent-system\ (参考用)
- GitHub: github.com/liutingqiu/zero (私密)

## v6 重构（当前进度：完成 8/8 项任务）

### 已完成

#### P0-1: model_adapter 层全面激活
- `llm.py` 和 `async_llm.py` 从硬编码 API 调用重构为使用 `model_adapter.load_adapters()` 发现适配器
- 移除了所有直接的 httpx POST 调用，统一走 adapter.chat() 接口
- 异步场景通过 `asyncio.to_thread()` 桥接同步适配器

#### P0-2: 消除 behavior_canon.py vs evaluate.py 代码重复
- `behavior/evaluate.py` 从 711 行缩减至 110 行（-85%）
- Phase 7/8/9 评估逻辑统一到 `behavior_canon.py`，evaluate.py 做 re-export 保持向后兼容

#### P1-1: 硬编码模型名集中配置
- `config.py` 新增 `MODEL_NAMES` 字典（支持 `ZERO_MODEL_*` 环境变量覆盖）
- 更新 6 个文件（`gpt_tools.py`, `agnes_proxy.py`, `action/tools.py`, `action/agent_registry.py`, `_diag_network.py`, `model_adapter/__init__.py`）中的硬编码模型名字符串

#### P1-2: 硬编码 API URL 统一
- `agnes_proxy.py` 的独立 `AGNES_URL` 改为引用 `config.AGNES_API_URL`
- 诊断脚本改用集中配置的 URL

#### P1-3: secure_config 隐藏依赖消除
- `gpt_tools.py` 直接从 `config` 导入，不再 fallback 到 `secure_config`
- `config.py` 中保留兼容但标为废弃

#### P1-4: System prompt 可配置化
- `config.py` 新增 `SYSTEM_IDENTITY`（环境变量 `ZERO_SYSTEM_IDENTITY` 覆盖）
- `behavior_canon.py` 的 `build_system()` 和 `canonicalize()` 默认值改用集中配置

#### P2-1: 平台插件自动发现机制
- 新增 `interfaces/istorage.py`（存储后端接口）
- 新增 `interfaces/plugin_loader.py`——自动发现并注入插件实现
- 发现路径：`personal/plugins/` → `ZERO_PLUGINS_DIR` 环境变量 → 内置 Null 实现
- 各接口模块保持 Null* 默认实现，插件不存在时静默降级

#### P3-1: 根目录清理
- 11 个诊断脚本（`_test_*`, `_diag_*`, `_find_*`, `_check_*`, `_validate*`, `_verify*`）移至 `scripts/`
- 6 个 HTML 测试文件删除
- `scripts/` 下脚本加 path 引导，可从任意目录运行

#### P0-3: LLM 响应缓存（会话中新增）
- `cognition/token_tracker.py` 新增 `make_hash()` 静态方法，从 messages + model + temperature 生成缓存 key
- `app/services/llm.py` `call_llm()` 适配器调用前先查缓存，命中直接返回并标记 `cached=True`
- `app/services/async_llm.py` `async_call_llm()` 同样加缓存逻辑
- 缓存命中时 TokenTracker 标记 `cached=True`，前端状态栏 `cache_hit_rate` 自动展示
- key 范围：同 session 内相同 messages + model + temperature 组合

#### P3-2: 单 Agent 流程链（会话中新增）
- 新增 `action/single_agent.py` — `SingleAgentOrchestrator` 类
- 四角色：Planner(拆步骤) → Executor(执行) → Critic(审查) → Synthesizer(整合)
- 所有用户请求都尝试拆步骤链，不硬判关键词（替代 `task_orchestrator.decompose()` 的关键词判断）
- Critic 双轨评分：规则 40%（零成本）+ LLM 60%（精准评审）
- 失败降级：planning 失败 → 单步执行，synthesize 失败 → 拼接各步骤输出
- `app/services/llm.py` 中 `handle_message()` 复杂任务自动走流程链
- 完全独立，不破坏已有 v4/v5/v8 路径

### 当前架构（更新版）

```
zero/
├── zero_server.py              # 主服务器 :5052
├── message_bus.py               # 消息总线
├── module.py                    # 模块基类
├── config.py                    # 集中配置（模型名/URL/身份/密钥）
├── gpt_tools.py                 # GPT-4o工具桥接
├── agnes_proxy.py               # Agnes Codex代理
├── behavior_canon.py            # 行为标准化 + Phase 7/8/9评估
├── semantic_gateway.py          # 语义门控
├── security/
│   ├── guard.py                 # 暗号/行为指纹/越狱检测
│   └── sandbox.py               # Windows Job Object沙箱
├── action/
│   ├── tools.py                 # 18工具(含Scrapling+Agnes)
│   ├── agent_loop.py            # Think→Act→Observe循环
│   ├── agent_registry.py        # 5 Agent能力匹配+熔断
│   ├── task_orchestrator.py     # v4 任务拆解执行
│   ├── single_agent.py          # v6 单Agent流程链(Planner→Executor→Critic→Synthesizer)
│   ├── reviewer.py              # 独立质量验证
│   ├── proactive.py             # 主动推送策略
│   ├── reflection.py            # 每日反思
│   └── kanban.py                # SQLite看板(Hermes风格)
├── cognition/
│   ├── working_memory.py        # 会话工作记忆
│   ├── memory_manager.py        # SQLite短期记忆+FTS5
│   ├── context.py               # 上下文自动注入
│   └── intent_engine.py         # 意图分类(LLM+缓存)
├── perception/
│   ├── file_watcher.py          # 文件监听
│   ├── clock.py                 # 时钟感知
│   └── sysmon.py                # 系统监控
├── model_adapter/               # 模型适配器层
│   ├── __init__.py              # load_adapters / 自动发现
│   ├── base.py                  # ModelAdapter基类
│   ├── agnes.py                 # Agnes适配器
│   ├── deepseek.py              # DeepSeek适配器
│   ├── openai.py                # OpenAI适配器
│   └── ollama.py                # Ollama适配器
├── interfaces/                  # 插件扩展接口
│   ├── __init__.py
│   ├── ipublisher.py            # 社交发布接口
│   ├── ivideo_producer.py       # 视频生产接口
│   ├── iskill_engine.py         # 技能引擎接口
│   ├── iextra_tool.py           # 自定义工具接口
│   ├── istorage.py              # 存储后端接口(v6新增)
│   └── plugin_loader.py         # 插件自动发现加载器(v6新增)
├── app/
│   ├── services/
│   │   ├── llm.py               # 同步LLM服务(已适配器化)
│   │   └── async_llm.py         # 异步LLM服务(已适配器化)
│   └── api/
│       └── server.py            # API路由
├── behavior/                    # 行为模块
│   ├── evaluate.py              # Phase 4.1核心类型 + re-export
│   ├── canonical.py             # 行为规范
│   ├── grounding.py             # 接地
│   ├── calibration.py           # 校准
│   └── profiles.py              # 行为画像
├── multi_agent/                 # 多Agent编排
├── utils/
│   ├── result.py                # 统一错误协议
│   └── json_helpers.py
├── interface/                   # Web界面
│   ├── webapp.py
│   └── hermes_web/              # Hermes React UI
├── scripts/                     # 诊断/测试脚本(v6从根目录迁入)
│   ├── diag_network.py
│   ├── test_agnes.py / test_api.py / test_flow.py / test_http.py / test_sse.py
│   ├── validate.py / verify.py
│   ├── check_key.py / find_env.py / read_registry.py
```

## 待重构清单（已更新 2026-06-17）

### P1 Token 成本控制
- [ ] **上下文增量传递** — 步骤链中每步只传增量上下文，不重复传前面步骤输出（当前 `call_llm` 全量传，步骤链模式下可大幅节省 token）
- [ ] **月预算限制 + 自动降级** — `TokenTracker.set_budget()` 已实现骨架，需在 `call_llm` 中检查预算超额后自动切换到免费模型（Agnes）

### P2 编排器优化
- [ ] **v4/v5 合并** — 当前 `task_orchestrator.py`(v4) 已废弃并由 `goal_orchestrator.py` + `single_agent.py` 替代，`multi_agent/` 目录实际不存在，P0 已解决

### P5 前端重构（本轮完成）
- [x] **前端拆分** — `interface/webapp.py` 的 1609 行内嵌 HTML/JS/CSS 已拆为 `interface/webapp_static/` 下的独立文件（index.html + style.css + app.js），`server.py` 改为从文件加载，支持 `/static/` 静态路由
- [x] **极简 UI 改造** — 无头像、圆角气泡（用户绿色/助手深灰）、向上箭头发送按钮、加号文件上传、Agent 呼吸灯状态侧边栏
- [x] **SSE 断线重连 + 超时处理** — 30s 无数据超时 + 15s 首数据超时 + 重试按钮
- [x] **请求失败处理** — 错误内联显示 + retryLastSend 自动找到最后用户消息重试 + regenerate 重新生成按钮
- [x] **草稿自动保存** — localStorage 每 2 秒自动保存输入框内容，页面刷新不丢失
- [x] **多标签同步** — `storage` 事件监听，多标签页切换自动同步对话列表
- [x] **Agent 状态侧边栏** — 独立 online/thinking/done/error 四态呼吸灯，对话列表/Agent 区域分开滚动
- [x] **思考过程折叠** — `<details>` 原生折叠，展开/收起无 JS
- [x] **代码块/表格折叠** — markdown 渲染时代码块自动包 `<details>`，表格同
- [x] **流式中间状态** — 侧边栏 Agent 呼吸灯 + 思考文本实时同步
- [x] **XSS 防护** — `escapeHtml` 覆盖所有用户/AI 内容
- [x] **图片灯箱 Escape 关闭** — `onkeydown` + focus 管理
- [x] **移动端键盘适配** — `visualViewport` 监听，iOS Safari 键盘不遮挡输入框
- [x] **移除 isComplexTask 自动协作** — 不再根据关键词自动走协作模式
- [x] **系统托盘图标** — pystray 托盘，右键菜单（打开浏览器/停止/重启），支持 `data/custom_icon.png` 自定义图标
- [x] **图标上传接口** — `POST /api/icon` 上传自定义托盘图标，聊天指令"换图标"引导操作
- [x] **pythonw.exe 无窗口启动** — `start.bat` 使用 `pythonw.exe`，无黑色控制台窗口

### P4 功能类（已部分完成）
- [ ] 语音输入/输出
- [x] **Agent 间互相 @ 协作** — 用户输入 @ 先走 LLM 理解上下文再执行 Agent，LLM 回复 @ 保留原始回复附加执行结果
- [x] **导入文件（上传 API）** — POST /api/upload + GET /api/download/{filename}
- [ ] 导出功能
- [x] **定时任务完善** — `perception/clock.py` 已接入 server.py main() 启动
- [x] **多轮迭代** — 检测 "再改/不够好/重新" 关键词触发重新生成，失败步骤自动提示用户可迭代
- [x] **前端完善** — 移动端适配优化（字体/间距/代码块换行/键盘适配）

## API资产
- Agnes: 5个免费模型(文本/图像/视频) — 主力
- AIHubMix: DeepSeek/GPT-4o — 付费兜底
- Tavily: 搜索 — 免费
- QQ邮箱: 报告发送
- Scrapling: 爬虫
- Playwright: 浏览器测试

## 凭据位置
- Windows Credential Manager (keyring)
- AGNES/KEY, AIHUBMIX/KEY, SEARCH_API/TAVILY_KEY
- GitHub Token: ⚠️ 已撤销，请用新 Token

## 当前运行
- 零 v4: http://127.0.0.1:5052 (Agnes优先→DeepSeek兜底)
- OpenClaw(龙虾): 已停
- Hermes: 已装但和龙虾冲突，精华已提取
- KnowledgeSys: 爬虫运行中
- Cloudflare Tunnel: 内网穿透

## 待办
- 语音输入/输出
- Agent间互相@协作
- 导入文件(拖拽)
- 导出功能
- 定时任务完善
- 多轮迭代("不够好再改")
- 前端完善(移动端、通知音效等)

## 启动命令
E:\python\python.exe E:\project\tools\zero\zero_server.py
