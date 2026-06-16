WEBAPP_HTML = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="theme-color" content="#212121">
<title>零</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; -webkit-font-smoothing: antialiased; }
html, body { height: 100%; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  background: #212121;
  color: #ececec;
  font-size: 16px;
  line-height: 1.6;
  display: flex;
  overflow: hidden;
}

/* ===== 侧边栏 ===== */
.sidebar {
  width: 260px;
  background: #171717;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  border-right: 1px solid #2a2a2a;
  transition: transform 0.25s ease;
}
.sidebar-header {
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  border-bottom: 1px solid #2a2a2a;
}
.new-chat-btn {
  width: 100%;
  padding: 10px 12px;
  background: transparent;
  border: 1px solid #3a3a3a;
  color: #ececec;
  border-radius: 10px;
  cursor: pointer;
  font-size: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  transition: background 0.15s, border-color 0.15s;
  font-family: inherit;
}
.new-chat-btn:hover { background: #2a2a2a; border-color: #4a4a4a; }
.new-chat-btn svg { width: 16px; height: 16px; flex-shrink: 0; }

.model-selector {
  padding: 8px 10px;
  background: #212121;
  border: 1px solid #3a3a3a;
  color: #ececec;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
  font-family: inherit;
  outline: none;
}
.model-selector:focus { border-color: #4ade80; }

.conversations {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}
.conversations::-webkit-scrollbar { width: 6px; }
.conversations::-webkit-scrollbar-thumb { background: #3a3a3a; border-radius: 3px; }
.conversations::-webkit-scrollbar-track { background: transparent; }

.conv-section-title {
  font-size: 11px;
  color: #737373;
  padding: 8px 10px 4px;
  font-weight: 500;
  letter-spacing: 0.3px;
}

.conv-item {
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13.5px;
  color: #d4d4d4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 2px;
  transition: background 0.12s;
  position: relative;
  padding-right: 36px;
}
.conv-item:hover { background: #2a2a2a; }
.conv-item.active { background: #2d2d2d; }
.conv-item .conv-delete {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  opacity: 0;
  transition: opacity 0.12s;
  color: #737373;
  background: none;
  border: none;
  cursor: pointer;
  padding: 2px;
  display: flex;
}
.conv-item:hover .conv-delete { opacity: 1; }
.conv-item .conv-delete:hover { color: #fb2c36; }

/* Agent 卡片 */
.agent-section-title {
  font-size: 11px;
  color: #737373;
  padding: 8px 10px 4px;
  font-weight: 500;
  letter-spacing: 0.3px;
  border-top: 1px solid #2a2a2a;
  margin-top: 4px;
}
.agent-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.12s;
  margin-bottom: 2px;
}
.agent-card:hover { background: #2a2a2a; }
.agent-card.active { background: #2d2d2d; }
.agent-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
  background: #4ade80;
  animation: breathe 2s ease-in-out infinite;
  box-shadow: 0 0 8px rgba(74, 222, 128, 0.4);
}
.agent-dot.offline { background: #525252; animation: none; box-shadow: none; }
.agent-dot.thinking { background: #fbbf24; animation: breathe 1s ease-in-out infinite; box-shadow: 0 0 10px rgba(251, 191, 36, 0.5); }
@keyframes breathe {
  0%, 100% { opacity: 0.6; transform: scale(0.95); }
  50% { opacity: 1; transform: scale(1.1); }
}
.agent-name {
  font-size: 13px;
  color: #d4d4d4;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sidebar-footer {
  padding: 10px;
  border-top: 1px solid #2a2a2a;
  display: flex;
  align-items: center;
  gap: 10px;
}
.user-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: linear-gradient(135deg, #4ade80, #22c55e);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 13px;
  color: #171717;
  flex-shrink: 0;
}
.user-info { flex: 1; min-width: 0; }
.user-name { font-size: 13px; color: #d4d4d4; font-weight: 500; }
.user-status { font-size: 11px; color: #737373; display: flex; align-items: center; gap: 4px; }
.user-status-dot {
  width: 6px; height: 6px; border-radius: 50%; background: #4ade80;
  animation: breathe 2s ease-in-out infinite;
}
.sidebar-toggle-mini {
  background: transparent;
  border: none;
  color: #737373;
  cursor: pointer;
  padding: 4px;
  border-radius: 6px;
  display: flex;
}
.sidebar-toggle-mini:hover { background: #2a2a2a; color: #d4d4d4; }

/* ===== 主区域 ===== */
.main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: #212121;
  position: relative;
}

.topbar {
  padding: 10px 16px;
  display: flex;
  align-items: center;
  gap: 10px;
  border-bottom: 1px solid #2a2a2a;
}
.menu-btn {
  background: transparent;
  border: none;
  color: #d4d4d4;
  cursor: pointer;
  padding: 6px;
  border-radius: 6px;
  display: flex;
  align-items: center;
}
.menu-btn:hover { background: #2a2a2a; }
.topbar-title {
  font-size: 14px;
  color: #d4d4d4;
  font-weight: 500;
}
.topbar-spacer { flex: 1; }

/* ===== 欢迎页 ===== */
.welcome {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 20px 20px 40px;
  overflow-y: auto;
}
.welcome-logo {
  font-size: 44px;
  font-weight: 700;
  background: linear-gradient(135deg, #4ade80, #22c55e);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  margin-bottom: 12px;
}
.welcome-text {
  color: #d4d4d4;
  font-size: 22px;
  font-weight: 600;
  margin-bottom: 36px;
}
.suggestion-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 10px;
  max-width: 720px;
  width: 100%;
}
.suggestion-card {
  background: transparent;
  border: 1px solid #3a3a3a;
  padding: 14px 16px;
  border-radius: 12px;
  cursor: pointer;
  text-align: left;
  transition: background 0.15s, border-color 0.15s;
  color: inherit;
  font-family: inherit;
}
.suggestion-card:hover { background: #262626; border-color: #4a4a4a; }
.suggestion-title {
  font-size: 14px;
  color: #e5e5e5;
  font-weight: 500;
  margin-bottom: 4px;
}
.suggestion-hint {
  font-size: 12px;
  color: #737373;
}

/* ===== 消息区 ===== */
.messages {
  flex: 1;
  overflow-y: auto;
  padding: 24px 0 120px;
}
.messages::-webkit-scrollbar { width: 10px; }
.messages::-webkit-scrollbar-thumb { background: #3a3a3a; border-radius: 5px; }
.messages::-webkit-scrollbar-thumb:hover { background: #4a4a4a; }
.messages::-webkit-scrollbar-track { background: transparent; }

.message-row {
  display: flex;
  gap: 14px;
  padding: 14px 24px 14px;
  max-width: 768px;
  margin: 0 auto;
  animation: fadeIn 0.3s ease;
}
@keyframes fadeIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }

.message-row.user { flex-direction: row-reverse; }

.avatar {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
}
.avatar.assistant {
  background: linear-gradient(135deg, #4ade80, #22c55e);
  color: #171717;
}
.avatar.assistant.thinking {
  animation: breathe 1.5s ease-in-out infinite;
  box-shadow: 0 0 12px rgba(74, 222, 128, 0.5);
}
.avatar.user {
  background: #3a3a3a;
  color: #d4d4d4;
  font-size: 12px;
}

.message-content { flex: 1; min-width: 0; }
.message-row.user .message-content { text-align: right; max-width: 85%; margin-left: auto; }

.message-bubble {
  display: inline-block;
  padding: 0;
  font-size: 15px;
  line-height: 1.7;
  max-width: 100%;
  text-align: left;
  word-wrap: break-word;
}

/* 思考过程区域 */
.thinking-block {
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
  border-radius: 10px;
  margin-bottom: 12px;
  overflow: hidden;
}
.thinking-header {
  padding: 8px 12px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #a3a3a3;
  user-select: none;
  transition: background 0.15s;
}
.thinking-header:hover { background: #222; }
.thinking-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: #fbbf24;
  animation: breathe 1.2s ease-in-out infinite;
  box-shadow: 0 0 8px rgba(251, 191, 36, 0.5);
  flex-shrink: 0;
}
.thinking-dot.done {
  background: #525252;
  animation: none;
  box-shadow: none;
}
.thinking-text {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.thinking-toggle {
  font-size: 10px;
  color: #737373;
  flex-shrink: 0;
}
.thinking-body {
  padding: 10px 14px 14px 36px;
  font-size: 13.5px;
  color: #a3a3a3;
  line-height: 1.6;
  border-top: 1px solid #2a2a2a;
  white-space: pre-wrap;
  display: none;
}
.thinking-block.open .thinking-body { display: block; }

/* Markdown 样式 */
.message-content h1, .message-content h2, .message-content h3 {
  margin: 14px 0 8px;
  font-weight: 600;
  color: #ececec;
}
.message-content h1 { font-size: 22px; }
.message-content h2 { font-size: 19px; }
.message-content h3 { font-size: 17px; }
.message-content p { margin: 8px 0; }
.message-content li { margin: 4px 0; }

.message-content a { color: #4ade80; text-decoration: none; }
.message-content a:hover { text-decoration: underline; }
.message-content a.img-link { display: inline-block; }
.message-content a.img-link:hover { text-decoration: none; opacity: 0.9; }
.message-content strong { font-weight: 600; }
.message-content em { font-style: italic; }

/* 代码块 */
.message-content pre {
  background: #0f0f0f !important;
  padding: 14px 16px;
  border-radius: 10px;
  overflow-x: auto;
  margin: 12px 0;
  border: 1px solid #2a2a2a;
  font-family: "SF Mono", Consolas, Menlo, monospace;
}
.message-content pre code {
  font-size: 13.5px;
  line-height: 1.55;
  display: block;
  white-space: pre;
  background: transparent !important;
  padding: 0 !important;
  border: none !important;
  color: #e5e5e5;
}
/* 行内代码 */
.message-content p code,
.message-content li code {
  background: #2a2a2a;
  padding: 2px 6px;
  border-radius: 4px;
  font-family: "SF Mono", Consolas, "Microsoft YaHei", monospace;
  font-size: 13px;
  color: #fbbf24;
}
/* 引用 */
.message-content blockquote {
  border-left: 3px solid #4ade80;
  padding: 2px 0 2px 14px;
  color: #a3a3a3;
  margin: 12px 0;
  font-style: italic;
}
/* 表格 */
.message-content table {
  border-collapse: collapse;
  margin: 12px 0;
  width: 100%;
  font-size: 13.5px;
}
.message-content th, .message-content td {
  border: 1px solid #3a3a3a;
  padding: 6px 12px;
  text-align: left;
}
.message-content th { background: #1a1a1a; font-weight: 600; }
.message-content img { max-width: 100%; border-radius: 8px; margin: 10px 0; }

/* ===== 输入区 ===== */
.input-area {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  padding: 16px 24px 24px;
  background: linear-gradient(to top, #212121 75%, transparent);
}
.input-wrapper {
  max-width: 768px;
  margin: 0 auto;
}
.input-box {
  background: #2f2f2f;
  border: 1px solid #3a3a3a;
  border-radius: 24px;
  padding: 12px 60px 12px 20px;
  display: flex;
  align-items: flex-end;
  transition: border-color 0.15s, box-shadow 0.15s;
  position: relative;
  min-height: 48px;
}
.input-box:focus-within {
  border-color: #4ade80;
  box-shadow: 0 0 0 3px rgba(74, 222, 128, 0.12);
}
.input-box textarea {
  flex: 1;
  background: transparent;
  border: none;
  color: #ececec;
  font-size: 15px;
  font-family: inherit;
  outline: none;
  resize: none;
  line-height: 1.6;
  max-height: 200px;
  overflow-y: auto;
}
.input-box textarea::placeholder { color: #737373; }
.input-box textarea::-webkit-scrollbar { width: 6px; }
.input-box textarea::-webkit-scrollbar-thumb { background: #3a3a3a; border-radius: 3px; }

.send-btn {
  position: absolute;
  right: 12px;
  top: 50%;
  transform: translateY(-50%);
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: #4ade80;
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s, transform 0.12s;
  color: #171717;
}
.send-btn:hover:not(:disabled) { background: #22c55e; transform: translateY(-50%) scale(1.08); }
.send-btn:disabled {
  background: #4a4a4a;
  cursor: not-allowed;
  opacity: 0.5;
}
.send-btn svg { width: 18px; height: 18px; }

/* ===== 消息操作按钮 ===== */
.msg-actions {
  display: flex;
  gap: 2px;
  margin-top: 6px;
  opacity: 0;
  transition: opacity 0.15s;
}
.message-row:hover .msg-actions { opacity: 1; }
.msg-btn {
  background: transparent;
  border: none;
  color: #525252;
  padding: 4px;
  border-radius: 4px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: color 0.12s;
}
.msg-btn:hover { color: #a3a3a3; }
.msg-btn svg { width: 15px; height: 15px; }

/* ===== 图片灯箱 ===== */
.lightbox-overlay {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.85);
  z-index: 200;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}
.lightbox-overlay.show { display: flex; }
.lightbox-content {
  position: relative;
  max-width: 90vw;
  max-height: 90vh;
  display: flex;
  align-items: center;
  justify-content: center;
}
.lightbox-content img {
  max-width: 90vw;
  max-height: 85vh;
  border-radius: 12px;
  box-shadow: 0 20px 60px rgba(0,0,0,0.6);
  cursor: default;
}
.lightbox-close {
  position: fixed;
  top: 16px;
  right: 20px;
  background: rgba(255,255,255,0.1);
  border: none;
  color: #fff;
  font-size: 24px;
  cursor: pointer;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s;
  z-index: 201;
}
.lightbox-close:hover { background: rgba(255,255,255,0.25); }
.lightbox-download {
  position: fixed;
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%);
  background: #4ade80;
  border: none;
  color: #171717;
  padding: 10px 24px;
  border-radius: 10px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
  font-family: inherit;
  z-index: 201;
  transition: background 0.15s, transform 0.12s;
}
.lightbox-download:hover { background: #22c55e; transform: translateX(-50%) scale(1.04); }

.input-hint {
  text-align: center;
  font-size: 11.5px;
  color: #737373;
  margin-top: 8px;
}

/* ===== 登录页 ===== */
.login-overlay {
  position: fixed;
  inset: 0;
  background: #212121;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  z-index: 100;
  padding: 20px;
}
.login-overlay.hidden { display: none; }
.login-logo {
  font-size: 52px;
  font-weight: 800;
  background: linear-gradient(135deg, #4ade80, #22c55e);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  margin-bottom: 20px;
}
.login-title { font-size: 18px; color: #d4d4d4; margin-bottom: 24px; font-weight: 500; }
.login-input {
  background: #2f2f2f;
  border: 1px solid #3a3a3a;
  color: #ececec;
  padding: 14px 20px;
  border-radius: 10px;
  font-size: 15px;
  width: 280px;
  outline: none;
  text-align: center;
  font-family: inherit;
  transition: border-color 0.15s;
}
.login-input:focus { border-color: #4ade80; }
.login-btn {
  margin-top: 12px;
  background: #4ade80;
  color: #171717;
  border: none;
  padding: 12px 40px;
  border-radius: 10px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  font-family: inherit;
  transition: background 0.15s, transform 0.12s;
}
.login-btn:hover { background: #22c55e; transform: scale(1.02); }
.login-err { color: #fb2c36; font-size: 13px; margin-top: 10px; }

/* ===== 移动端 ===== */
@media (max-width: 768px) {
  .sidebar {
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    z-index: 50;
    transform: translateX(-100%);
    box-shadow: 4px 0 20px rgba(0, 0, 0, 0.5);
    width: 240px;
  }
  .sidebar.open { transform: translateX(0); }
  .message-row { padding: 12px 14px; max-width: 100%; }
  .input-area { padding: 10px 14px 14px; }
  .welcome { padding: 10px 10px 40px; }
  .sidebar-backdrop {
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.5);
    z-index: 40;
  }
  .sidebar-backdrop.show { display: block; }
  .send-btn { width: 32px; height: 32px; right: 8px; bottom: 8px; }
}
/* ===== 工作模式 ===== */
.mode-toggle-bar {
  padding: 12px 16px; border-top: 1px solid #2a2a2a;
  display: flex; gap: 6px;
}
.mode-btn-v1 {
  flex: 1; padding: 8px 6px; border: 1px solid #3a3a3a; border-radius: 8px;
  background: transparent; color: #888; font-size: 12px; cursor: pointer;
  text-align: center; transition: .15s;
}
.mode-btn-v1.active { background: #00d4aa20; border-color: #00d4aa; color: #00d4aa; font-weight: 600; }
.bb-card-v1 {
  background: #1a1a2a; border: 1px solid #2a2a4a; border-radius: 10px;
  padding: 12px; margin: 8px 0; font-size: 13px;
}
.bb-card-v1 .bb-hdr { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.bb-card-v1 .bb-role-tag { font-size: 10px; color: #888; text-transform: uppercase; letter-spacing: 1px; }
.bb-card-v1 .bb-status-tag { font-size: 10px; padding: 2px 8px; border-radius: 6px; }
.bb-card-v1 .bb-status-tag.pending { background: #ffffff10; color: #888; }
.bb-card-v1 .bb-status-tag.running { background: #4a9eff20; color: #4a9eff; }
.bb-card-v1 .bb-status-tag.done { background: #00d4aa20; color: #00d4aa; }
.bb-status-tag.failed { background: #ff5a7a20; color: #ff5a7a; }
.bb-card-v1 .bb-out { font-size: 12px; color: #888; margin-top: 6px; padding: 8px; background: #00000030; border-radius: 6px; max-height: 80px; overflow-y: auto; }
</style>
</head>
<body>

<div class="login-overlay" id="login">
  <div class="login-logo">零</div>
  <div class="login-title">请输入暗号解锁</div>
  <input id="code" type="text" placeholder="暗号" autocomplete="off" autofocus>
  <button class="login-btn" onclick="unlock()">解锁</button>
  <div class="login-err" id="err"></div>
</div>

<div class="sidebar-backdrop" id="sidebarBackdrop" onclick="toggleSidebar()"></div>

<div class="sidebar" id="sidebar">
  <div class="sidebar-header">
    <button class="new-chat-btn" onclick="newChat()">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
      <span>新对话</span>
    </button>
  </div>

  <div class="conversations" id="convList">
    <div class="conv-section-title" id="convTitle" style="display:none;">最近对话</div>
  </div>

  <div class="agent-section-title">Agent</div>
  <div class="agent-card" data-agent="" onclick="switchAgent(this)">
    <div class="agent-dot thinking" id="dot_zero"></div>
    <div class="agent-name">零 · 智能路由</div>
  </div>
  <div class="agent-card" data-agent="agnes_text" onclick="switchAgent(this)">
    <div class="agent-dot"></div>
    <div class="agent-name">Agnes 2.0</div>
  </div>
  <div class="agent-card" data-agent="reasonix" onclick="switchAgent(this)">
    <div class="agent-dot"></div>
    <div class="agent-name">Reasonix · 代码</div>
  </div>
  <div class="agent-card" data-agent="tavily" onclick="switchAgent(this)">
    <div class="agent-dot"></div>
    <div class="agent-name">Tavily · 搜索</div>
  </div>

  <div class="sidebar-footer">
    <div class="user-avatar">橙</div>
    <div class="user-info">
      <div class="user-name">柳橙</div>
      <div class="user-status">
        <span class="user-status-dot"></span>
        <span id="userStatus">已解锁</span>
      </div>
    </div>
    <button class="sidebar-toggle-mini" onclick="newChat()" title="新对话">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
    </button>
  </div>
</div>

<div class="main">
  <div class="topbar">
    <button class="menu-btn" onclick="toggleSidebar()" title="菜单">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="3" y1="6" x2="21" y2="6"></line><line x1="3" y1="12" x2="21" y2="12"></line><line x1="3" y1="18" x2="21" y2="18"></line></svg>
    </button>
    <div class="topbar-title" id="chatTitle">零</div>
    <div class="topbar-spacer"></div>
  </div>

  <div class="messages" id="msgs"></div>

  <div class="input-area">
    <div class="input-wrapper">
      <div class="input-box">
        <textarea id="inp" rows="1" placeholder="给零发消息...（Shift+Enter 换行）" onkeydown="handleKey(event)" oninput="autoResize(this)"></textarea>
        <button class="send-btn" id="sendBtn" onclick="send()" title="发送">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="19" x2="12" y2="5"></line><polyline points="5 12 12 5 19 12"></polyline></svg>
        </button>
      </div>
      <div class="input-hint">零可能会出错。请核对重要信息。</div>
    </div>
  </div>
</div>

<!-- 图片灯箱 -->
<div class="lightbox-overlay" id="lightbox" onclick="closeLightbox(event)">
  <div class="lightbox-content">
    <button class="lightbox-close" onclick="closeLightbox()" title="关闭">✕</button>
    <button class="lightbox-download" id="lightboxDownload" title="保存到本地">保存</button>
    <img id="lightboxImg" src="" alt="原图">
  </div>
</div>

<script>
// ===== 状态管理 =====
let conversations = []; // [{id, title, messages:[{role, content}]}]
let currentConvId = null;
let currentAgentId = ''; // 空 = 智能路由
let isSending = false;

// ===== 工具函数 =====
function uid(){ return 'c_' + Date.now() + '_' + Math.random().toString(36).slice(2, 7); }

function saveConversations() {
  try { localStorage.setItem('zero_conv_v2', JSON.stringify(conversations)); localStorage.setItem('zero_current_v2', currentConvId || ''); } catch(e) {}
}
function loadConversations() {
  try {
    const raw = localStorage.getItem('zero_conv_v2');
    if (raw) conversations = JSON.parse(raw);
    currentConvId = localStorage.getItem('zero_current_v2') || null;
  } catch(e) { conversations = []; }
}

// ===== Markdown 渲染 =====
function escapeHtml(s) {
  return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
function renderMarkdown(text) {
  if (!text) return '';
  let html = String(text);

  // 代码块
  html = html.replace(/```([\s\S]*?)```/g, function(m, inside) {
    const nl = inside.indexOf('\n');
    const code = nl > 0 ? inside.slice(nl + 1) : inside;
    return '\n<pre><code>' + escapeHtml(code.trim()) + '</code></pre>\n';
  });

  // 转义 HTML（先保存代码块的位置，后面再反转）
  // 简单策略：除已处理代码块，其他都转义
  // 使用占位符方案保护已处理内容
  const protectedBlocks = [];
  html = html.replace(/<pre><code>[\s\S]*?<\/code><\/pre>/g, function(m) {
    protectedBlocks.push(m);
    return '__PROT_' + (protectedBlocks.length - 1) + '__';
  });
  html = escapeHtml(html);

  // 行内 code
  html = html.replace(/`([^`\n]+)`/g, function(m, c) { return '<code>' + c + '</code>'; });

  // 加粗
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  // 斜体
  html = html.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');

  // 标题
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');

  // 引用
  html = html.replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>');

  // 分隔线
  html = html.replace(/^---+$/gm, '<hr>');

  // 链接
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');

  // 图片 URL：自动渲染为可点击放大的 <img>
  html = html.replace(/(^|[^"'\]\)>\n])(https?:\/\/[^\s<]+?\.(?:png|jpe?g|gif|webp)(?:\?[^\s<]*)?)/gim, '$1<a href="$2" target="_blank" rel="noopener" class="img-link"><img src="$2" alt="生成的图片" style="max-width:100%;border-radius:8px;margin:10px 0;cursor:pointer;" loading="lazy"></a>');
  // 普通 URL
  html = html.replace(/(^|[^"'\]\)>\n])(https?:\/\/[^\s<]+)(?=\s|$|<|\)|\])/gm, '$1<a href="$2" target="_blank" rel="noopener">$2</a>');

  // 表格
  html = html.replace(/(\|.+\|\n\|[-:\|]+\|\n(?:\|.+\|\n?)+)/g, function(m) {
    const lines = m.trim().split('\n').filter(function(l) { return l.trim(); });
    const headerCells = lines[0].slice(1, -1).split('|').map(function(c) { return '<th>' + c.trim() + '</th>'; }).join('');
    const bodyRows = lines.slice(2).map(function(line) {
      const cells = line.slice(1, -1).split('|').map(function(c) { return '<td>' + c.trim() + '</td>'; }).join('');
      return '<tr>' + cells + '</tr>';
    }).join('');
    return '<table><thead><tr>' + headerCells + '</tr></thead><tbody>' + bodyRows + '</tbody></table>';
  });

  // 无序列表
  html = html.replace(/((?:^[-*] .+\n?)+)/gm, function(m) {
    const items = m.trim().split('\n').map(function(l) { return '<li>' + l.replace(/^[-*] /, '') + '</li>'; }).join('');
    return '<ul>' + items + '</ul>';
  });
  // 有序列表
  html = html.replace(/((?:^\d+\. .+\n?)+)/gm, function(m) {
    const items = m.trim().split('\n').map(function(l) { return '<li>' + l.replace(/^\d+\. /, '') + '</li>'; }).join('');
    return '<ol>' + items + '</ol>';
  });

  // 段落处理：把连续文本用 <p> 包裹，但避免破坏列表/表格等
  html = html.replace(/\n{2,}/g, '</p><p>');
  html = '<p>' + html + '</p>';
  html = html.replace(/<p>\s*<\/p>/g, '');

  // 换行
  html = html.replace(/\n/g, '<br>');

  // 恢复受保护代码块
  for (let i = 0; i < protectedBlocks.length; i++) {
    html = html.replace('__PROT_' + i + '__', protectedBlocks[i]);
  }

  return html;
}

// ===== 侧边栏渲染 =====
function renderSidebar() {
  const container = document.getElementById('convList');
  const title = document.getElementById('convTitle');
  if (!conversations.length) {
    container.innerHTML = '<div class="conv-section-title" style="opacity:0.5;">暂无对话。开始新对话吧</div>';
    title.style.display = 'none';
    return;
  }
  title.style.display = 'block';
  const items = conversations.map(function(c) {
    const isActive = c.id === currentConvId;
    return '<div class="conv-item' + (isActive ? ' active' : '') + '" onclick="loadConv(\'' + c.id + '\')" title="' + escapeHtml(c.title) + '">'
      + escapeHtml(c.title || '新对话')
      + '<button class="conv-delete" onclick="event.stopPropagation(); deleteConv(\'' + c.id + '\')" title="删除">'
      + '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6 l-2 14 H7 L5 6"></path><line x1="10" y1="11" x2="10" y2="17"></line><line x1="14" y1="11" x2="14" y2="17"></line></svg>'
      + '</button>'
      + '</div>';
  }).join('');
  container.innerHTML = '<div class="conv-section-title">最近对话</div>' + items;

  // 高亮当前选择的 Agent
  document.querySelectorAll('.agent-card').forEach(function(el) {
    if ((el.getAttribute('data-agent') || '') === currentAgentId) {
      el.classList.add('active');
    } else {
      el.classList.remove('active');
    }
  });
}

// ===== 对话管理 =====
function newChat() {
  currentConvId = null;
  renderSidebar();
  renderWelcome();
  if (window.innerWidth <= 768) toggleSidebar(false);
}
function deleteConv(id) {
  conversations = conversations.filter(function(c) { return c.id !== id; });
  if (currentConvId === id) { currentConvId = null; renderWelcome(); }
  renderSidebar();
  saveConversations();
}
function loadConv(id) {
  const conv = conversations.find(function(c) { return c.id === id; });
  if (!conv) return;
  currentConvId = id;
  renderSidebar();
  renderMessages();
  if (window.innerWidth <= 768) toggleSidebar(false);
}
function getOrCreateCurrentConv() {
  if (!currentConvId) {
    currentConvId = uid();
    conversations.unshift({ id: currentConvId, title: '新对话', messages: [] });
    saveConversations();
  }
  return conversations.find(function(c) { return c.id === currentConvId; });
}
function updateCurrentConvTitle(firstUserMsg) {
  const conv = conversations.find(function(c) { return c.id === currentConvId; });
  if (conv && (conv.title === '新对话' || !conv.title)) {
    conv.title = firstUserMsg.slice(0, 24) || '新对话';
    renderSidebar();
    saveConversations();
  }
}
function switchAgent(el) {
  const agentId = el.getAttribute('data-agent') || '';
  currentAgentId = agentId;
  const title = '零' + (agentId ? ' · ' + (agentId === 'agnes_text' ? 'Agnes' : agentId === 'reasonix' ? 'Reasonix' : agentId === 'tavily' ? 'Tavily' : agentId === 'agnes_image' ? '生图' : agentId) : '');
  document.getElementById('chatTitle').textContent = title;
  renderSidebar();
}

// ===== 欢迎页 & 消息 =====
function renderWelcome() {
  const msgs = document.getElementById('msgs');
  msgs.innerHTML = '<div class="welcome">'
    + '<div class="welcome-logo">零</div>'
    + '<div class="welcome-text">有什么可以帮你的？</div>'
    + '<div class="suggestion-grid">'
    + '<button class="suggestion-card" onclick="sendAsMsg(\'你好，你能做什么？\')"><div class="suggestion-title">👋 打招呼</div><div class="suggestion-hint">让零介绍自己</div></button>'
    + '<button class="suggestion-card" onclick="sendAsMsg(\'用代码帮我实现一个 Python 的快速排序函数\')"><div class="suggestion-title">💻 写代码</div><div class="suggestion-hint">Python 快速排序</div></button>'
    + '<button class="suggestion-card" onclick="sendAsMsg(\'帮我分析一下如何高效使用大模型 API\')"><div class="suggestion-title">🔍 分析问题</div><div class="suggestion-hint">深度分析技术问题</div></button>'
    + '<button class="suggestion-card" onclick="sendAsMsg(\'讲一个有趣的编程相关故事\')"><div class="suggestion-title">✨ 创意写作</div><div class="suggestion-hint">编程故事</div></button>'
    + '</div></div>';
}

function renderMessages() {
  const msgs = document.getElementById('msgs');
  const conv = conversations.find(function(c) { return c.id === currentConvId; });
  if (!conv || !conv.messages.length) { renderWelcome(); return; }
  document.getElementById('chatTitle').textContent = conv.title || '零';

  msgs.innerHTML = conv.messages.map(function(m) {
    const isUser = m.role === 'user';
    const avatarClass = isUser ? 'user' : 'assistant';
    const avatarText = isUser ? '橙' : '零';

    // 分离思考过程和正文
    let thinking = null;
    let content = m.content;
    const thinkingMatch = m.content.match(/[\u{1f4ad}\u{2601}\u{1f4ac}]\s*?(思考过程|思考|thinking)[^\n]*?[:：]\s*?([\s\S]*?)(?=\n\s*?\n|\n\s*?(?=(?:回复|回答|正文|步骤|结果|总结|✅|✅|📌|💡|【|##|\*\*))|$)/i);
    if (thinkingMatch) {
      thinking = thinkingMatch[2].trim();
      content = (m.content.slice(0, thinkingMatch.index) + m.content.slice(thinkingMatch.index + thinkingMatch[0].length)).trim();
    }

    let html = '<div class="message-row ' + (isUser ? 'user' : 'assistant') + '">'
      + '<div class="avatar ' + avatarClass + '">' + avatarText + '</div>'
      + '<div class="message-content"><div class="message-bubble">';

    if (thinking && !isUser) {
      html += '<div class="thinking-block" onclick="this.classList.toggle(\'open\')">'
        + '<div class="thinking-header">'
        + '<div class="thinking-dot done"></div>'
        + '<div class="thinking-text">已深度思考 ' + Math.ceil(thinking.length / 80) + ' 步</div>'
        + '<div class="thinking-toggle">点击展开 ▾</div>'
        + '</div>'
        + '<div class="thinking-body">' + escapeHtml(thinking) + '</div>'
        + '</div>';
    }

    html += renderMarkdown(content);

    // 操作按钮（复制 + 编辑 — 纯图标）
    const mIdx = conv.messages.indexOf(m);
    html += '<div class="msg-actions">'
      + '<button class="msg-btn" onclick="event.stopPropagation();copyMessage(' + mIdx + ')" title="复制">'
      + '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
      + '<rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>'
      + '</svg></button>'
      + '<button class="msg-btn" onclick="event.stopPropagation();editMessage(' + mIdx + ')" title="编辑">'
      + '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
      + '<path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"></path>'
      + '</svg></button>'
      + '</div>';

    html += '</div></div></div>';
    return html;
  }).join('');
  msgs.scrollTop = msgs.scrollHeight;
  // 绑定图片灯箱事件
  setTimeout(bindImageClicks, 50);
}

function appendStreamingMessage(isStreaming) {
  const msgs = document.getElementById('msgs');
  // 如果已有 streamingRow 则复用
  if (msgs.querySelector('#streamingRow')) {
    return msgs.querySelector('#streamingRow');
  }
  const div = document.createElement('div');
  div.className = 'message-row assistant';
  div.id = 'streamingRow';
  div.innerHTML = '<div class="avatar assistant thinking">零</div>'
    + '<div class="message-content"><div class="message-bubble">'
    + '<div class="thinking-block open" id="streamingThinking">'
    + '<div class="thinking-header">'
    + '<div class="thinking-dot"></div>'
    + '<div class="thinking-text">正在思考...</div>'
    + '<div class="thinking-toggle">点击收起 ▴</div>'
    + '</div>'
    + '<div class="thinking-body" id="streamingThinkingBody"></div>'
    + '</div>'
    + '<div id="streamingContent"></div>'
    + '</div></div>';
  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;
  return div;
}

function finishStreaming(replyText, conv) {
  // 把完整回复保存到 conversation
  conv.messages.push({ role: 'assistant', content: replyText });
  saveConversations();
  renderMessages();
}

// ===== 输入处理 =====
function autoResize(ta) {
  ta.style.height = 'auto';
  ta.style.height = Math.min(ta.scrollHeight, 200) + 'px';
}
function handleKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    send();
  }
}
function toggleSidebar(force) {
  const el = document.getElementById('sidebar');
  const bd = document.getElementById('sidebarBackdrop');
  const show = typeof force === 'boolean' ? force : !el.classList.contains('open');
  if (show) { el.classList.add('open'); bd.classList.add('show'); }
  else { el.classList.remove('open'); bd.classList.remove('show'); }
}
function sendAsMsg(text) {
  document.getElementById('inp').value = text;
  send();
}

// ===== 认证 =====
function unlock() {
  const code = document.getElementById('code').value.trim();
  if (!code) return;
  fetch('/api/auth', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code: code })
  }).then(function(r) { return r.json(); }).then(function(d) {
    if (d.ok) {
      document.getElementById('login').classList.add('hidden');
      document.getElementById('userStatus').textContent = '已解锁';
      loadConversations();
      renderSidebar();
      if (currentConvId && conversations.find(function(c) { return c.id === currentConvId; })) {
        renderMessages();
      } else {
        renderWelcome();
      }
    } else {
      document.getElementById('err').textContent = '暗号错误，请重试';
    }
  }).catch(function() { document.getElementById('err').textContent = '网络错误，请重试'; });
}
document.getElementById('code').addEventListener('keydown', function(e) { if (e.key === 'Enter') unlock(); });

// ===== 发送消息 =====
async function send() {
  const inp = document.getElementById('inp');
  const text = inp.value.trim();
  if (!text || isSending) return;
  isSending = true;
  document.getElementById('sendBtn').disabled = true;

  // 更新 Agent 状态为 thinking
  document.querySelectorAll('.agent-dot').forEach(function(d) { d.classList.remove('thinking'); });
  const activeAgentCard = document.querySelector('.agent-card.active');
  if (activeAgentCard) {
    const dot = activeAgentCard.querySelector('.agent-dot');
    if (dot) dot.classList.add('thinking');
  } else {
    document.getElementById('dot_zero').classList.add('thinking');
  }

  const conv = getOrCreateCurrentConv();
  conv.messages.push({ role: 'user', content: text });
  saveConversations();
  updateCurrentConvTitle(text);

  inp.value = '';
  inp.style.height = 'auto';
  renderMessages();

  // 准备 streaming 容器
  appendStreamingMessage(true);

  const replyText = { content: '', thinking: '' };
  let thinkingMode = 'unknown'; // unknown -> thinking/reply
  let accumulatedThinking = '';
  let accumulatedReply = '';

  try {
    // 先尝试 SSE 流式
    const url = '/api/chat/stream?m=' + encodeURIComponent(text)
      + (currentAgentId ? '&agent=' + encodeURIComponent(currentAgentId) : '');
    const resp = await fetch(url);

    if (!resp.ok) {
      // 回退到 POST
      const postResp = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, agent_id: currentAgentId })
      });
      if (!postResp.ok) throw new Error('请求失败 (' + postResp.status + ')');
      const d = await postResp.json();
      let replyContent = d.reply || '';
      let thinkingData = null;

      // 检测思考数据（orchestrator 返回的 JSON）
      try {
        const parsed = JSON.parse(replyContent);
        if (parsed.summary && parsed.thinking) {
          replyContent = parsed.summary;
          thinkingData = parsed.thinking;
        }
      } catch(e) {}

      replyText.content = replyContent;

      // 渲染思考面板
      let thinkingHtml = '';
      if (thinkingData && thinkingData.length > 0) {
        const labels = { '设计': '#f472b6', '代码': '#4ade80', '检索': '#fbbf24', '系统': '#737373', '分析': '#a78bfa' };
        thinkingHtml = '<div class="thinking-block open" id="streamingThinking"><div class="thinking-header" onclick="this.parentElement.classList.toggle(\'open\')"><div class="thinking-dot done"></div><div class="thinking-text">查看思考过程 (' + thinkingData.length + '个Agent)</div><div class="thinking-toggle">点击收起 ▴</div></div><div class="thinking-body" style="display:block;padding:8px 12px 12px 12px;font-size:13px;line-height:1.5;">';
        thinkingData.forEach(function(s) {
          var lb = s.label || '系统';
          var lc = labels[lb] || '#737373';
          thinkingHtml += '<div style="margin-bottom:10px;padding:8px 10px;background:#1a1a1a;border-radius:8px;border-left:3px solid ' + lc + '">';
          thinkingHtml += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">';
          thinkingHtml += '<span style="font-weight:500;color:#d4d4d4">' + (s.agent || '?') + '</span>';
          thinkingHtml += '<span style="font-size:11px;padding:1px 6px;border-radius:4px;background:' + lc + '20;color:' + lc + '">' + lb + '</span>';
          thinkingHtml += '</div>';
          if (s.output) thinkingHtml += '<div style="color:#a3a3a3;white-space:pre-wrap;word-break:break-word">' + (s.output || '').slice(0, 300) + '</div>';
          var meta = [];
          if (s.score) meta.push('评分 ' + s.score);
          if (s.file_written) meta.push('已写入 ' + s.file_written);
          if (meta.length) thinkingHtml += '<div style="font-size:11px;color:#525252;margin-top:4px">' + meta.join(' · ') + '</div>';
          thinkingHtml += '</div>';
        });
        thinkingHtml += '</div></div>';
      }

      const tc = document.getElementById('streamingContent');
      if (tc) tc.innerHTML = thinkingHtml + renderMarkdown(replyContent);
      finishStreaming(replyContent, conv);
    } else {
      const reader = resp.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buf = '';
      let allDone = false;
      let firstChunkReceived = false;

      // 逐行处理 SSE
      let processLine = function(line) {
        if (!line.startsWith('data:')) return;
        try {
          const d = JSON.parse(line.substring(5));
          if (d.type === 'chunk') {
            // 追加到回复内容
            accumulatedReply += d.data;
            firstChunkReceived = true;
            const tc = document.getElementById('streamingContent');
            if (tc) {
              tc.innerHTML = renderMarkdown(accumulatedReply);
              document.getElementById('msgs').scrollTop = document.getElementById('msgs').scrollHeight;
            }
            // 第一块之后，关闭 thinking 动画
            const thinkBlock = document.getElementById('streamingThinking');
            if (thinkBlock) {
              if (accumulatedReply.length > 400 && thinkBlock.classList.contains('open')) {
                thinkBlock.classList.remove('open');
              }
              const thinkText = thinkBlock.querySelector('.thinking-text');
              if (thinkText && accumulatedThinking.length === 0) {
                thinkText.textContent = '正在组织回复...';
                const thDot = thinkBlock.querySelector('.thinking-dot');
                if (thDot) thDot.classList.add('done');
              }
            }
          } else if (d.type === 'done') {
            allDone = true;
            // 关闭 thinking 块，标记完成
            const thinkBlock = document.getElementById('streamingThinking');
            if (thinkBlock) {
              thinkBlock.classList.remove('open');
              const thinkText = thinkBlock.querySelector('.thinking-text');
              if (thinkText) thinkText.textContent = '已完成';
              const thDot = thinkBlock.querySelector('.thinking-dot');
              if (thDot) thDot.classList.add('done');
            }
          } else if (d.type === 'status') {
            const thinkText = document.querySelector('#streamingThinking .thinking-text');
            if (thinkText && d.data) thinkText.textContent = d.data;
          } else if (d.type === 'error') {
            accumulatedReply += '\n[错误] ' + d.data;
            const tc = document.getElementById('streamingContent');
            if (tc) tc.innerHTML = renderMarkdown(accumulatedReply);
          }
        } catch(err) {}
      };

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split('\n');
        buf = lines.pop() || '';
        for (const line of lines) processLine(line);
      }

      // 保存最终回复
      const finalReply = accumulatedReply;
      replyText.content = finalReply;
      finishStreaming(finalReply, conv);
    }
  } catch(err) {
    const errMsg = '出错：' + (err.message || err);
    const tc = document.getElementById('streamingContent');
    if (tc) tc.innerHTML = '<span style="color:#fb2c36;">' + escapeHtml(errMsg) + '</span>';
    conv.messages.push({ role: 'assistant', content: errMsg });
    saveConversations();
    renderMessages();
  } finally {
    isSending = false;
    document.getElementById('sendBtn').disabled = false;
    // 恢复 Agent 呼吸灯为正常
    document.querySelectorAll('.agent-dot').forEach(function(d) { d.classList.remove('thinking'); });
    inp.focus();
  }
}

// ===== 图片灯箱 =====
let currentLightboxUrl = '';
let currentLightboxProxyUrl = '';
function openLightbox(url) {
  currentLightboxUrl = url;
  currentLightboxProxyUrl = '/api/image-proxy?url=' + encodeURIComponent(url);
  document.getElementById('lightboxImg').src = url;
  document.getElementById('lightboxDownload').onclick = function(e) { e.stopPropagation(); downloadImage(currentLightboxProxyUrl); };
  document.getElementById('lightbox').classList.add('show');
}
function closeLightbox(e) {
  if (e && e.target !== document.getElementById('lightbox')) return;
  document.getElementById('lightbox').classList.remove('show');
}
function downloadImage(proxyUrl) {
  // 同源代理 URL → <a download> 弹出系统「另存为」对话框
  const a = document.createElement('a');
  a.href = proxyUrl;
  a.download = currentLightboxUrl.split('/').pop().split('?')[0] || 'image.png';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

// ===== 消息操作 =====
function copyMessage(idx) {
  const conv = conversations.find(function(c) { return c.id === currentConvId; });
  if (!conv) return;
  const msg = conv.messages[idx];
  navigator.clipboard.writeText(msg.content).then(function() {
    // 短暂反馈
  }).catch(function() {});
}
function editMessage(idx) {
  const conv = conversations.find(function(c) { return c.id === currentConvId; });
  if (!conv) return;
  // 截断对话：保留到这条消息为止（不含），当前消息内容填入输入框
  const msg = conv.messages[idx];
  // 去掉这条及之后的消息；但保留这条之前的所有消息
  conv.messages = conv.messages.slice(0, idx);
  saveConversations();
  renderMessages();
  // 把这条消息的内容填入输入框
  const inp = document.getElementById('inp');
  inp.value = msg.content;
  inp.focus();
  autoResize(inp);
}

// 页面加载后，给所有图片链接绑定灯箱事件
function bindImageClicks() {
  document.querySelectorAll('.img-link').forEach(function(a) {
    a.addEventListener('click', function(e) {
      e.preventDefault();
      openLightbox(this.href);
    });
  });
}

// ===== 健康检查 =====
fetch('/health').then(function(r) { return r.json(); }).then(function(d) {
  if (d.session && d.session.indexOf('已解锁') >= 0) {
    document.getElementById('login').classList.add('hidden');
    loadConversations();
    renderSidebar();
    if (currentConvId && conversations.find(function(c) { return c.id === currentConvId; })) {
      renderMessages();
    } else {
      renderWelcome();
    }
  } else {
    loadConversations();
    renderSidebar();
  }
}).catch(function() {
  loadConversations();
  renderSidebar();
});

// ===== 智能路由：一句话落地 =====
// 检测是否需要多Agent协作
function isComplexTask(text) {
  var t = text.toLowerCase();
  var complexWords = ['做', '建', '搭', '开发', '项目', '网站', '应用',
    '写一个', '实现', '创建', '规划', '设计', '拆解',
    '全流程', '整个', '完整', '帮我做', '做一个',
    '分析', '重构', '优化', '部署'];
  return complexWords.some(function(w) { return t.indexOf(w) >= 0; });
}

// 协作模式: SSE 流式，实时展示每一步
async function sendCollab(text) {
  var conv = getOrCreateCurrentConv();
  var msgs = document.getElementById('msgs');
  var loadDiv = document.createElement('div');
  loadDiv.className = 'message assistant';
  loadDiv.innerHTML = '<div class="msg-header"><span class="msg-role">⚙️ 协作</span></div><div class="msg-content"><div id="bbSteps"></div><div id="bbAnswer" style="margin-top:12px;line-height:1.6"></div></div>';
  msgs.appendChild(loadDiv);
  var stepsDiv = document.getElementById('bbSteps');
  var answerDiv = document.getElementById('bbAnswer');
  var finalAnswer = '';
  var icons = {pending:'⏳',running:'🔄',done:'✅',failed:'❌'};
  var roleNames = {planner:'📋 规划',executor:'🔧 执行',critic:'🔍 审查',synthesizer:'📝 整合'};

  try {
    var resp = await fetch('/api/collab/stream?m=' + encodeURIComponent(text));
    var reader = resp.body.getReader();
    var decoder = new TextDecoder();
    var buf = '';
    while (true) {
      var result = await reader.read();
      if (result.done) break;
      buf += decoder.decode(result.value, {stream:true});
      var lines = buf.split('\n');
      buf = lines.pop() || '';
      for (var i = 0; i < lines.length; i++) {
        var line = lines[i];
        if (!line.startsWith('data: ')) continue;
        try {
          var evt = JSON.parse(line.substring(6));
          if (evt.type === 'step') {
            var d = evt.data;
            var card = document.createElement('div');
            card.className = 'bb-card-v1';
            card.id = 'bb-' + (d.id || d.role);
            card.innerHTML = '<div class="bb-hdr">'
              + '<span>' + (icons[d.status]||'🔄') + '</span>'
              + '<span class="bb-role-tag">' + (roleNames[d.role]||d.role) + '</span>'
              + '<span class="bb-status-tag ' + d.status + '">' + d.status + '</span>'
              + '</div>'
              + '<div style="font-size:12px;color:#aaa">' + escapeHtml(d.action||'') + '</div>'
              + (d.output ? '<div class="bb-out"><code>' + escapeHtml(d.output).substring(0,300) + '</code></div>' : '');
            var existing = document.getElementById('bb-' + (d.id || d.role));
            if (existing && d.id) existing.replaceWith(card);
            else if (existing) existing.replaceWith(card);
            else stepsDiv.appendChild(card);
          } else if (evt.type === 'done') {
            finalAnswer = evt.data.answer || '';
            answerDiv.innerHTML = renderMarkdown(finalAnswer);
          } else if (evt.type === 'error') {
            answerDiv.innerHTML = '<span style="color:#ff5a7a">' + escapeHtml(evt.data) + '</span>';
          } else if (evt.type === 'status') {
            stepsDiv.innerHTML += '<div style="font-size:12px;color:#888;padding:4px 0">' + escapeHtml(evt.data) + '</div>';
          }
        } catch(e) {}
      }
    }
    conv.messages.push({role:'assistant',content:finalAnswer||'协作完成'});
    saveConversations();
  } catch(err) {
    stepsDiv.innerHTML = '<span style="color:#ff5a7a">协作失败: ' + escapeHtml(err.message||err) + '</span>';
  } finally {
    isSending = false;
    document.getElementById('sendBtn').disabled = false;
    document.getElementById('dot_zero').classList.remove('thinking');
    document.getElementById('inp').focus();
    renderMessages();
  }
}

// 拦截 send：自动判断走聊天还是协作
var _origSend2 = send;
send = async function() {
  var inp = document.getElementById('inp');
  var text = inp.value.trim();
  if (!text || isSending) return;

  if (isComplexTask(text)) {
    // 复杂任务 → 多Agent协作
    isSending = true;
    document.getElementById('sendBtn').disabled = true;
    document.getElementById('dot_zero').classList.add('thinking');
    var conv = getOrCreateCurrentConv();
    conv.messages.push({role:'user',content:text});
    saveConversations();
    updateCurrentConvTitle(text);
    inp.value = ''; inp.style.height = 'auto';
    renderMessages();
    return sendCollab(text);
  }
  // 简单任务 → 正常聊天
  return _origSend2();
};
</script>
</body>
</html>'''
