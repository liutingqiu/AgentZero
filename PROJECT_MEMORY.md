# 零 v5 · 项目记忆
> 最后更新: 2026-06-16

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

## 当前架构（14个模块）

```
zero/
├── zero_server.py          # 主服务器 :5052
├── message_bus.py           # 消息总线(线程池+15种任务事件)
├── module.py                # 模块基类
├── gpt_tools.py             # GPT-4o工具桥接
├── agnes_proxy.py           # Agnes Codex代理
├── security/
│   ├── guard.py             # 暗号/行为指纹/越狱检测
│   └── sandbox.py           # Windows Job Object沙箱
├── action/
│   ├── tools.py             # 18工具(含Scrapling+Agnes)
│   ├── agent_loop.py        # Think→Act→Observe循环
│   ├── agent_registry.py    # 5 Agent能力匹配+熔断
│   ├── task_orchestrator.py # 任务拆解执行
│   ├── reviewer.py          # 独立质量验证
│   ├── proactive.py         # 主动推送策略
│   ├── reflection.py        # 每日反思
│   └── kanban.py            # SQLite看板(Hermes风格)
├── cognition/
│   ├── working_memory.py    # 会话工作记忆
│   ├── memory_manager.py    # SQLite短期记忆+FTS5
│   ├── context.py           # 上下文自动注入
│   └── intent_engine.py     # 意图分类(LLM+缓存)
├── perception/
│   ├── file_watcher.py      # 文件监听
│   ├── clock.py             # 时钟感知
│   └── sysmon.py            # 系统监控
└── interface/
    ├── webapp.py            # ChatGPT风格Web界面
    └── hermes_web/          # Hermes React UI(备用)
```

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
