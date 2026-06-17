# 零 v6 · HTTP API 文档

> Base URL: `http://127.0.0.1:5052`
> 认证: 关闭（默认）/ 暗号解锁 见 `/api/auth`

---

## 端点总览

| 方法 | 路径 | 用途 | 需认证 |
|------|------|------|:--:|
| GET | `/health` | 健康检查 | ❌ |
| GET | `/` | Web UI 界面 | ❌ |
| GET | `/api/settings` | 系统设置/状态 | ✅ |
| GET | `/api/history` | 历史会话摘要 | ✅ |
| GET | `/api/kanban` | 看板任务列表 | ✅ |
| GET | `/api/tokens` | Token 统计 | ✅ |
| GET | `/api/tokens/recent` | 最近调用记录 | ✅ |
| GET | `/api/notifications` | 通知列表 | ✅ |
| GET | `/api/image-proxy?url=` | 图片代理 | ❌ |
| GET | `/api/chat/stream?m=` | SSE 流式聊天 | ✅ |
| GET | `/api/collab/stream?m=` | SSE 协作风流 | ✅ |
| GET | `/api/download/{filename}` | 下载文件 | ✅ |
| POST | `/api/auth` | 暗号认证 | ❌ |
| POST | `/api/chat` | 发送消息 | ✅ |
| POST | `/api/agents/{agent_id}/run` | 调用指定 Agent | ✅ |
| POST | `/api/collab` | 协作模式（步骤链） | ✅ |
| POST | `/api/upload` | 上传文件 | ✅ |

---

## 详细说明

### GET /health — 健康检查

```
GET /health
```

**响应:**
```json
{
  "status": "ok",
  "session": "已解锁",
  "active_tokens": 1
}
```

---

### POST /api/auth — 暗号认证

```
POST /api/auth
Content-Type: application/json

{"code": "你的暗号"}
```

**响应（成功）:**
```json
{"ok": true, "token": "xxx", "message": "用户，2小时内零随时待命。"}
```

**响应（失败）:**
```json
{"ok": false, "error": "暗号不对。还剩2次机会。"}
```

> 如 `zero_config.json` 中 `auth.enabled=false`，认证始终通过。

---

### POST /api/chat — 发送消息

```
POST /api/chat
Content-Type: application/json

{"message": "你好，帮我总结一下今天的项目进度"}
```

**响应:**
```json
{
  "reply": "今天项目进度如下：...",
  "status": "ok",
  "agent": "reasonix"
}
```

**指定 Agent:**
```json
{"message": "搜索 AI 最新动态", "agent_id": "tavily"}
```

---

### GET /api/chat/stream — SSE 流式聊天

```
GET /api/chat/stream?m=你好
```

**SSE 事件流:**
```
data: {"type":"status","data":"thinking"}
data: {"type":"chunk","data":"你好！"}
data: {"type":"chunk","data":"今天有什么..."}
data: {"type":"done","data":{"agent":"reasonix","total_chars":150}}
```

---

### POST /api/collab — 协作模式（步骤链）

```
POST /api/collab
Content-Type: application/json

{"message": "帮我做一个响应式网站首页"}
```

**响应:**
```json
{
  "status": "done",
  "answer": "网站已创建: E:/project/tools/zero/data/index.html",
  "steps": [
    {"id": "step_1", "action": "设计HTML结构", "status": "done", "output": "...", "version_count": 1, "critiques": [true]},
    {"id": "step_2", "action": "添加CSS样式", "status": "done", "output": "...", "version_count": 1, "critiques": [true]}
  ],
  "completed": 2,
  "failed": 0,
  "grounded": 0,
  "events": {"total": 0}
}
```

---

### GET /api/collab/stream — SSE 协作流

```
GET /api/collab/stream?m=帮我做一个登录页面
```

SSE 事件包含 Planner→Executor→Critic→Synthesizer 每个步骤的实时进度。

---

### POST /api/agents/{agent_id}/run — 调用指定 Agent

```
POST /api/agents/reasonix/run
Content-Type: application/json

{"message": "写一个快速排序", "capabilities": ["code_generation"]}
```

**可用 Agent:** `reasonix`, `agnes_text`, `agnes_image`, `tavily`, `deepseek`

---

### GET /api/tokens — Token 统计

```
GET /api/tokens
```

**响应:**
```json
{
  "total_calls": 25,
  "total_tokens": 45120,
  "total_cost": 0.0063,
  "budget": 0.50,
  "budget_remaining": 0.4937,
  "cached_tokens": 0,
  "cache_hit_rate": 0.0,
  "by_agent": {
    "reasonix": {"calls": 20, "tokens": 35000, "cost": 0.0049, "cached": 0}
  }
}
```

---

### GET /api/tokens/recent — 最近调用

```
GET /api/tokens/recent
```

返回最近 30 次 LLM 调用的明细（时间、模型、Token 量、费用、是否缓存命中）。

---

### GET /api/settings — 系统设置

```
GET /api/settings
```

**响应:**
```json
{
  "agents": {"reasonix": "online", "agnes_text": "online", ...},
  "memory": {"sessions": 12, "tasks": 45},
  "apis": {"agnes": true, "deepseek": true, "base_url": "https://api.deepseek.com/v1/chat/completions"},
  "session_unlocked": true,
  "watch_root": ".",
  "owner": "User"
}
```

---

### POST /api/upload — 文件上传

```
POST /api/upload
Content-Type: multipart/form-data

file: example.py
```

**响应:**
```json
{"ok": true, "files": [{"name": "example.py", "size": 1024}]}
```

文件保存到 `data/uploads/`。

---

### GET /api/download/{filename} — 文件下载

```
GET /api/download/example.py
```

返回文件的二进制流。

---

### GET /api/image-proxy — 图片代理

```
GET /api/image-proxy?url=https://example.com/image.png
```

代理远程图片（用于前端绕过跨域限制）。

---

### GET /api/history — 历史会话摘要

```
GET /api/history
```

返回最近 7 天/50 条对话摘要。

---

### GET /api/kanban — 看板

```
GET /api/kanban
```

返回任务看板（已完成数/总数/任务列表）。

---

## 认证说明

`zero_config.json` 控制认证开关:

```json
{
  "auth": {
    "enabled": false,
    "passphrase": "",
    "unlock_hours": 2
  }
}
```

- `enabled=false` → 所有 API 无需认证
- `enabled=true` → 先 POST `/api/auth` 获取 token，前端自动带 Authorization header

## 预算配置

```json
{
  "budget": {
    "monthly_usd": 0.50,
    "auto_degrade_threshold": 0.05
  }
}
```

- `monthly_usd=0` → 不限预算
- `monthly_usd=0.50` → 月预算 $0.50
- `auto_degrade_threshold=0.05` → 剩余低于 $0.05 自动切免费模型（Agnes AI）

## 启动方式

```
E:\python\python.exe E:\project\tools\zero\zero_server.py
```

或双击 `start.bat`。
