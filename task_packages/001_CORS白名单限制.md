# 任务 A：后端 CORS 白名单限制

> **身份**：你只负责这个任务，不要查看或修改本任务包未指定的任何文件。
> 你是一个没有大局观的 AI，只能处理单一文件、单一函数的修改。涉及多个文件或需要全局判断的修改你会产生幻觉，必须拒绝执行并向上级报告。

---

## 边界规则（不可违反）

1. 只改 `app/api/server.py` 这一个文件。
2. 只改这个文件里的 `_cors_headers()` 函数体。
3. 不改任何其他函数（路由 handler、中间件、SSE 逻辑、认证逻辑等一律不动）。
4. 不新增路由、不新增配置项、不新增依赖。
5. 不改 `config.py`，不改 `app/services/llm.py`，不改 `action/` 下的任何文件。
6. 不改前后端交互的 JSON 结构。
7. 如果有任何不确定的地方，问清楚再动手，不要猜测。

---

## 前置准备

读取以下文件：
- `app/api/server.py`（完整读取，重点关注 `_cors_headers` 函数）

---

## 需求

将 `_cors_headers()` 函数中硬编码的 `Access-Control-Allow-Origin: *` 改为基于请求 Origin 的白名单检查。

### 实现要点

1. 在 `_cors_headers` 函数中，从 `request.headers.get('Origin')` 获取请求来源。
2. 定义允许的 Origin 白名单：
   - `http://127.0.0.1:5052`
   - `http://localhost:5052`
3. 如果请求的 Origin 在白名单中，返回 `Access-Control-Allow-Origin: {Origin}`。
4. 如果请求的 Origin 不在白名单中，返回空（不设置该头）。
5. 保留现有的 `Access-Control-Allow-Methods` 和 `Access-Control-Allow-Headers` 不变。
6. 保留现有的 `Access-Control-Allow-Credentials` 设置。

### 禁止的行为
- ❌ 不要添加 `*` 通配符
- ❌ 不要修改函数签名
- ❌ 不要添加全局变量或环境变量读取逻辑
- ❌ 不要改动任何其他函数

---

## 验收标准

1. `curl -H "Origin: http://evil.com" -X OPTIONS -v http://127.0.0.1:5052/api/chat` 返回头中**不包含** `Access-Control-Allow-Origin`
2. `curl -H "Origin: http://127.0.0.1:5052" -X OPTIONS -v http://127.0.0.1:5052/api/chat` 返回头中包含 `Access-Control-Allow-Origin: http://127.0.0.1:5052`
3. 正常前端访问不受影响，登录、聊天等功能正常

---

## 如何验证

```bash
# 测试合法的 Origin
curl -H "Origin: http://127.0.0.1:5052" -X OPTIONS -v http://127.0.0.1:5052/api/chat 2>&1 | grep "Access-Control-Allow-Origin"

# 测试非法的 Origin
curl -H "Origin: https://malicious-site.com" -X OPTIONS -v http://127.0.0.1:5052/api/chat 2>&1 | grep "Access-Control-Allow-Origin"

# 验证正常接口不受影响
curl http://127.0.0.1:5052/health
```

---

## 遇到问题时的决策树

1. 找不到 `_cors_headers` 函数 → 停止，报告
2. 需要改别的文件才能实现功能 → 停止，报告
3. 不确定白名单应该包含哪些 Origin → 停止，问清楚
4. 发现现有代码有其他 bug → 记录但不修改，报告