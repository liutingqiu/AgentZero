# 任务 008：后端看板 CRUD 接口

> **身份**：你只负责这个任务包。不要查看或修改本任务包未指定的任何文件。
> 你是一个没有大局观的 AI，只能在同一文件内新增函数和路由。涉及跨文件改动或全局架构决策你会产生幻觉，必须拒绝执行并向上级报告。

---

## 边界规则（不可违反）

1. 只改 `app/api/server.py` 这一个文件。
2. 只新增路由 handler（函数），不修改现有路由或函数。
3. 不改 `action/kanban.py`（看板内部逻辑不动）。
4. 不改 `config.py`、`app/services/` 等任何其他文件。
5. 不改已有的错误响应格式（使用 `_error_response`）。
6. 如果有任何不确定的地方，问清楚再动手，不要猜测。

---

## 前置准备

读取以下文件：
- `app/api/server.py`（完整读取，了解现有路由注册模式）
- `action/kanban.py`（完整读取，了解 kanban 模块提供了哪些方法）
- `API_DOCS.md`（了解现有 API 风格）

---

## 需求

后端现在只有 `GET /api/kanban` 一个只读端点。看板模块（`action/kanban.py`）内部很可能已有 `add_task`、`update_task`、`delete_task` 方法，但没有 HTTP 接口暴露它们。

新增 3 个 API 端点：

### 端点 1：`POST /api/kanban` — 创建看板任务

**路由注册**：
```python
app.router.add_post('/api/kanban', handle_kanban_create)
```

**handler 函数**：
```python
async def handle_kanban_create(request):
    """创建看板任务"""
    try:
        body = await request.json()
    except Exception:
        return _error_response(ERR_BAD_REQUEST, '请求格式错误')

    title = body.get('title', '').strip()
    if not title:
        return _error_response(ERR_BAD_REQUEST, '任务标题不能为空')

    try:
        # 调用 kanban 模块的 add_task 方法
        task = kanban.add_task(title)
        return web.json_response({'ok': True, 'task': task})
    except Exception as e:
        return _error_response(ERR_INTERNAL, str(e), status=500)
```

**请求体**：
```json
{"title": "分析用户反馈"}
```

**成功响应**：
```json
{"ok": true, "task": {"id": 1, "title": "分析用户反馈", "status": "pending"}}
```

### 端点 2：`PUT /api/kanban/{id}` — 更新看板任务

**路由注册**：
```python
app.router.add_put('/api/kanban/{id}', handle_kanban_update)
```

**handler 函数**：
```python
async def handle_kanban_update(request):
    """更新看板任务状态"""
    task_id = request.match_info.get('id')
    if not task_id or not task_id.isdigit():
        return _error_response(ERR_BAD_REQUEST, '无效的任务 ID')

    try:
        body = await request.json()
    except Exception:
        return _error_response(ERR_BAD_REQUEST, '请求格式错误')

    status = body.get('status', '').strip()
    if status and status not in ('pending', 'running', 'done', 'failed'):
        return _error_response(ERR_BAD_REQUEST, f'无效的状态: {status}')

    try:
        task = kanban.update_task(int(task_id), status=status if status else None)
        if task is None:
            return _error_response(ERR_NOT_FOUND, f'任务 {task_id} 不存在')
        return web.json_response({'ok': True, 'task': task})
    except Exception as e:
        return _error_response(ERR_INTERNAL, str(e), status=500)
```

**请求体**：
```json
{"status": "running"}
```

**成功响应**：
```json
{"ok": true, "task": {"id": 1, "title": "分析用户反馈", "status": "running"}}
```

### 端点 3：`DELETE /api/kanban/{id}` — 删除看板任务

**路由注册**：
```python
app.router.add_delete('/api/kanban/{id}', handle_kanban_delete)
```

**handler 函数**：
```python
async def handle_kanban_delete(request):
    """删除看板任务"""
    task_id = request.match_info.get('id')
    if not task_id or not task_id.isdigit():
        return _error_response(ERR_BAD_REQUEST, '无效的任务 ID')

    try:
        result = kanban.delete_task(int(task_id))
        if not result:
            return _error_response(ERR_NOT_FOUND, f'任务 {task_id} 不存在')
        return web.json_response({'ok': True})
    except Exception as e:
        return _error_response(ERR_INTERNAL, str(e), status=500)
```

**成功响应**：
```json
{"ok": true}
```

### 注册路由的位置

在 `def make_app()` 函数中，找到 `app.router.add_get('/api/kanban', ...)` 那一行，紧跟在它后面加上三条新路由：

```python
# 看板
app.router.add_get('/api/kanban', handle_kanban_list)       # 已有
app.router.add_post('/api/kanban', handle_kanban_create)     # 新增
app.router.add_put('/api/kanban/{id}', handle_kanban_update) # 新增
app.router.add_delete('/api/kanban/{id}', handle_kanban_delete) # 新增
```

### `kanban` 模块的导入

检查 `server.py` 顶部是否已经 `from action.kanban import ...`。如果没有，添加：

```python
from action.kanban import KanbanBoard  # 根据实际情况调整类名和导入方式
```

或如果已有 `from action import kanban` 的导入方式，使用已有方式。

---

## 验收标准

1. `curl -X POST -H "Content-Type: application/json" -d '{"title":"测试任务"}' http://127.0.0.1:5052/api/kanban` 返回 `{"ok": true, "task": {...}}`
2. `curl -X PUT -H "Content-Type: application/json" -d '{"status":"done"}' http://127.0.0.1:5052/api/kanban/1` 返回 `{"ok": true, "task": {...}}`
3. `curl -X DELETE http://127.0.0.1:5052/api/kanban/1` 返回 `{"ok": true}`
4. `curl -X POST -H "Content-Type: application/json" -d '{}' http://127.0.0.1:5052/api/kanban` 返回 400 错误

---

## 如何验证

```bash
# 1. 创建任务
curl -X POST -H "Content-Type: application/json" -d '{"title":"任务1"}' http://127.0.0.1:5052/api/kanban

# 2. 更新任务状态
curl -X PUT -H "Content-Type: application/json" -d '{"status":"running"}' http://127.0.0.1:5052/api/kanban/1

# 3. 删除任务
curl -X DELETE http://127.0.0.1:5052/api/kanban/1

# 4. 查看列表（确认 CRUD 影响）
curl http://127.0.0.1:5052/api/kanban
```

---

## 遇到问题时的决策树

1. `action/kanban.py` 中的方法名不是 `add_task` / `update_task` / `delete_task` → 查看实际方法名，用正确的名称调用
2. `action/kanban.py` 中的方法需要不同参数 → 按实际签名传入，不要脑补
3. `kanban` 模块在 `server.py` 中未导入 → 在文件顶部添加 import（注意不要重复导入）
4. 看板模块本身没有提供这些方法 → 停止，报告（可能需要另开任务实现 kanban 内部逻辑）