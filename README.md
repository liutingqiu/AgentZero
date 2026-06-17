# ⚡ 零 (Zero) — AI Agent Runtime

> **半成品 / Work in Progress** — 后端架构已完善，前端设计请暂时忽略。
> Backend architecture is solid. Frontend design is a known work-in-progress — please ignore the visuals for now.

[![Python](https://img.shields.io/badge/Python-3.11+-blue)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Alpha-yellow)]()

---

**EN** | Zero is an AI Agent orchestration runtime. It takes a goal, breaks it into a step chain, executes each step, and delivers the result — all through a single LLM.

**CN** | 零是一个 AI Agent 编排运行时。接收你的目标，拆成步骤链，逐步执行，输出结果。只需要一个 LLM 模型就能跑。

---

## 壳子哲学 / Shell Philosophy

**EN** | Zero is a kernel, not a toolbox. You clone it, plug in your API keys, and it runs. Want social posting? Video generation? Custom tools? You implement them through extension interfaces. Zero stays lean — you own your extensions.

**CN** | 零是内核，不是工具箱。clone 下来，填入 API Key，就能跑。想接入社交发帖、视频生成、自定义工具？通过扩展接口自己加。零保持精简，扩展你说了算。

```
git clone → pip install -r requirements.txt → 双击 start.bat
                                                    ↓
                                        已可用：AI 对话 + 任务编排
                                                    ↓
                           可选：配置 personal_config.json
                           接入你的社交账号、工具链、本地模型
                                                    ↓
                                        你的个性化零
```

---

## 启动 / Quick Start

### 第一次使用 / First Time

```bash
# 安装依赖
E:\python\python.exe -m pip install -r requirements.txt

# 配置 API Key（至少配一个 / at least one required）
cp .env.example .env
# 编辑 .env，填入 LLM_API_KEY
```

### 每次启动 / Every Time

**双击 `start.bat`**

它会：
- 无窗口启动零
- 自动打开浏览器 → `http://127.0.0.1:5052`

**停止：** 双击 `stop.bat`

### Docker

```bash
cp .env.example .env
docker compose up -d
```

---

## 环境变量 / Environment Variables

| 变量 | 必填 | 说明 |
|------|:--:|------|
| `LLM_API_KEY` | **是** | 主力模型密钥（DeepSeek 推荐） |
| `LLM_API_URL` | 否 | 模型 API 地址，默认 DeepSeek |
| `AGNES_API_KEY` | 否 | 免费备选模型（Agnes AI） |
| `OWNER_NAME` | 否 | 你的称呼，默认 "User" |
| `ZERO_PORT` | 否 | 端口，默认 5052 |

---

## 架构 / Architecture

```
zero/
├── app/api/           # HTTP 层 (aiohttp + 16 API 端点)
├── app/services/      # LLM 服务 + 缓存 + 降级
├── action/            # 20 工具 + 单Agent流程链 + Agent注册表
├── cognition/         # 三层上下文记忆 + Token追踪
├── security/          # 越狱检测 + 行为指纹 + 沙箱
├── model_adapter/     # DeepSeek/Agnes/OpenAI/Ollama 适配器
├── interfaces/        # 插件扩展接口（社交/视频/技能/存储）
├── behavior/          # 行为评估 + 温度策略
├── perception/        # 文件监听 + 时钟 + 系统监控
├── config.py          # 集中配置
├── start.bat          # 一键启动
└── API_DOCS.md        # 完整 API 文档
```

---

## API

| 端点 | 说明 |
|------|------|
| `GET /health` | 健康检查 |
| `POST /api/chat` | 对话 |
| `GET /api/chat/stream` | SSE 流式对话 |
| `POST /api/collab` | 多步骤协作 |
| `GET /api/collab/stream` | SSE 流式协作 |
| `GET /api/tokens` | Token 统计 |
| `POST /api/upload` | 文件上传 |
| `GET /api/download/{file}` | 文件下载 |

完整文档 → [API_DOCS.md](API_DOCS.md)

---

## License

MIT © 零 Contributors
