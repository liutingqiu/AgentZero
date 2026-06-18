// ===== 零 · 前端主程序 =====
// ===== 状态管理 =====
// Theme toggle function
function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme');
  const next = current === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('zero-theme', next);
}

// Initialize theme
(function() {
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const stored = localStorage.getItem('zero-theme');
  const theme = stored || (prefersDark ? 'dark' : 'light');
  document.documentElement.setAttribute('data-theme', theme);
})();
let conversations = [];
let currentConvId = null;
let currentAgentId = '';
let isSending = false;
let pendingFile = null;
let currentPermissionLevel = localStorage.getItem('zero_permission') || 'plan';

// ===== 工具函数 =====
function uid() { return 'c_' + Date.now() + '_' + Math.random().toString(36).slice(2, 7); }

function saveConversations() {
  try { localStorage.setItem('zero_conv_v2', JSON.stringify(conversations)); localStorage.setItem('zero_current_v2', currentConvId || ''); } catch (e) { console.warn('save failed', e); }
}
function loadConversations() {
  try {
    const raw = localStorage.getItem('zero_conv_v2');
    if (raw) conversations = JSON.parse(raw); else conversations = [];
    currentConvId = localStorage.getItem('zero_current_v2') || null;
  } catch (e) { conversations = []; currentConvId = null; }
}

// 多标签同步
window.addEventListener('storage', function (e) {
  if (e.key === 'zero_conv_v2' || e.key === 'zero_current_v2') {
    loadConversations();
    renderSidebar();
    if (currentConvId) renderMessages();
    else renderWelcome();
  }
});

// ===== 输入框草稿自动保存 =====
(function autosaveDraft() {
  const key = 'zero_draft';
  const inp = document.getElementById('inp');
  if (!inp) return;
  // 恢复草稿
  const saved = localStorage.getItem(key);
  if (saved && inp) { inp.value = saved; autoResize(inp); }
  // 定时保存
  setInterval(function () {
    try { localStorage.setItem(key, inp.value || ''); } catch (e) {}
  }, 2000);
  // 发送后清除
  const origSend = send;
  send = function () {
    try { localStorage.removeItem(key); } catch (e) {}
    return origSend.apply(this, arguments);
  };
})();

// ===== 侧边栏渲染 =====
function renderSidebar() {
  const container = document.getElementById('convList');
  const title = document.getElementById('convTitle');
  if (!conversations.length) {
    container.innerHTML = '<div class="conv-section-title" style="color:#333;padding:10px 8px;">暂无对话</div>';
    if (title) title.style.display = 'none';
    return;
  }
  if (title) title.style.display = 'block';
  const items = conversations.map(function (c) {
    const isActive = c.id === currentConvId;
    return '<div class="conv-item' + (isActive ? ' active' : '') + '" role="listitem" onclick="loadConv(\'' + c.id + '\')" title="' + escapeHtml(c.title || '') + '">'
      + escapeHtml(c.title || '新对话')
      + '<button class="conv-delete" onclick="event.stopPropagation(); deleteConv(\'' + c.id + '\')" title="删除">'
      + '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6 l-2 14 H7 L5 6"></path><line x1="10" y1="11" x2="10" y2="17"></line><line x1="14" y1="11" x2="14" y2="17"></line></svg>'
      + '</button></div>';
  }).join('');
  container.innerHTML = '<div class="conv-section-title">最近对话</div>' + items;

  // Agent 高亮
  document.querySelectorAll('.agent-card').forEach(function (el) {
    el.classList.toggle('active', (el.getAttribute('data-agent') || '') === currentAgentId);
  });
}

function setAgentStatus(agentId, state, text) {
  const dot = document.getElementById('dot_' + (agentId || 'zero'));
  const statusEl = document.getElementById('status_' + (agentId || 'zero'));
  if (!dot) return;
  dot.className = 'agent-dot';
  if (state) dot.classList.add(state);
  if (statusEl && text !== undefined) statusEl.textContent = text || '';
}

function resetAllAgentDots() {
  ['zero', 'agnes_text', 'reasonix', 'tavily'].forEach(function (id) {
    setAgentStatus(id === 'zero' ? '' : id, 'online', '');
  });
}

// ===== 权限等级选择器 =====
function renderPermissionSelector() {
  // 动态创建权限选择器容器
  var wrapper = document.querySelector('.input-wrapper');
  if (!wrapper) return;
  var existing = document.getElementById('permissionSelector');
  if (!existing) {
    var sel = document.createElement('div');
    sel.id = 'permissionSelector';
    sel.className = 'permission-selector';
    var hint = wrapper.querySelector('.input-hint');
    if (hint) {
      hint.parentNode.insertBefore(sel, hint);
    } else {
      wrapper.appendChild(sel);
    }
  }
  var container = document.getElementById('permissionSelector');
  if (!container) return;
  var levels = ['plan', 'auto', 'yolo'];
  container.innerHTML = levels.map(function (l) {
    var active = l === currentPermissionLevel;
    return '<button class="perm-btn perm-' + l + (active ? ' active' : '') + '" onclick="setPermission(\'' + l + '\')">' + l.toUpperCase() + '</button>';
  }).join('');
}

function setPermission(level) {
  currentPermissionLevel = level;
  localStorage.setItem('zero_permission', level);
  renderPermissionSelector();
  // yolo 模式下输入框边框变红警告
  var inp = document.getElementById('inp');
  if (inp) {
    var inputBox = inp.closest('.input-box');
    if (inputBox) {
      inputBox.classList.toggle('yolo-warning', level === 'yolo');
    }
  }
}

// ===== 对话管理 =====
function newChat() {
  currentConvId = null;
  renderSidebar();
  renderWelcome();
  if (window.innerWidth <= 768) toggleSidebar(false);
}

async function deleteConv(id) {
  const confirmed = await confirmDialog('确定要删除此对话吗？');
  if (!confirmed) return;
  conversations = conversations.filter(function (c) { return c.id !== id; });
  if (currentConvId === id) { currentConvId = null; renderWelcome(); }
  renderSidebar();
  saveConversations();
  showToast('对话已删除', 'info');
}

function loadConv(id) {
  const conv = conversations.find(function (c) { return c.id === id; });
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
  return conversations.find(function (c) { return c.id === currentConvId; });
}

function updateCurrentConvTitle(firstUserMsg) {
  const conv = conversations.find(function (c) { return c.id === currentConvId; });
  if (conv && (!conv.title || conv.title === '新对话')) {
    conv.title = (firstUserMsg || '').slice(0, 24) || '新对话';
    renderSidebar();
    saveConversations();
  }
}

function switchAgent(el) {
  const agentId = el.getAttribute('data-agent') || '';
  currentAgentId = agentId;
  const names = { '': '零', agnes_text: 'Agnes 2.0', reasonix: 'Reasonix · 代码', tavily: 'Tavily · 搜索' };
  document.getElementById('chatTitle').textContent = names[agentId] || '零';
  renderSidebar();
}

// ===== 消息渲染 =====
function renderWelcome() {
  const msgs = document.getElementById('msgs');
  msgs.innerHTML = '<div class="welcome" style="flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:20px;">'
    + '<div style="font-size:38px;font-weight:700;background:linear-gradient(135deg,#4ade80,#22c55e);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;margin-bottom:10px;">零</div>'
    + '<div style="color:#888;font-size:16px;margin-bottom:30px;">有什么可以帮你的？</div>'
    + '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:8px;max-width:600px;width:100%;">'
    + '<button class="suggestion-card" onclick="sendAsMsg(\'你好，你能做什么？\')"><div style="font-size:13px;color:#d4d4d4;font-weight:500;margin-bottom:2px;">👋 打招呼</div><div style="font-size:11px;color:#525252;">让零介绍自己</div></button>'
    + '<button class="suggestion-card" onclick="sendAsMsg(\'用代码帮我实现一个 Python 快速排序\')"><div style="font-size:13px;color:#d4d4d4;font-weight:500;margin-bottom:2px;">💻 写代码</div><div style="font-size:11px;color:#525252;">Python 快速排序</div></button>'
    + '<button class="suggestion-card" onclick="sendAsMsg(\'帮我分析如何高效使用大模型 API\')"><div style="font-size:13px;color:#d4d4d4;font-weight:500;margin-bottom:2px;">🔍 分析问题</div><div style="font-size:11px;color:#525252;">技术分析</div></button>'
    + '<button class="suggestion-card" onclick="sendAsMsg(\'讲一个有趣的编程故事\')"><div style="font-size:13px;color:#d4d4d4;font-weight:500;margin-bottom:2px;">✨ 创意写作</div><div style="font-size:11px;color:#525252;">编程故事</div></button>'
    + '</div></div>';
}

function renderMessages() {
  const msgs = document.getElementById('msgs');
  const conv = conversations.find(function (c) { return c.id === currentConvId; });
  if (!conv || !conv.messages.length) { renderWelcome(); return; }
  document.getElementById('chatTitle').textContent = conv.title || '零';
  msgs.innerHTML = '<div class="no-animate">' + conv.messages.map(function (m, i) {
    const isUser = m.role === 'user';
    return '<div class="msg-row ' + (isUser ? 'user' : 'assistant') + '">'
      + '<div class="msg-bubble">'
      + renderMessageBody(m)
      + '<div class="msg-actions">'
      + '<button class="msg-btn" onclick="copyMessage(' + i + ')" title="复制">'
      + '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg></button>'
      + (!isUser ? '<button class="msg-btn regenerate" onclick="regenerate(' + i + ')" title="重新生成">'
        + '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"></path><path d="M21 3v5h-5"></path></svg></button>' : '')
      + '</div>'
      + '</div></div>';
  }).join('') + '</div>';
  msgs.scrollTop = msgs.scrollHeight;
  setTimeout(bindImageClicks, 50);
}

function renderMessageBody(m) {
  // 分离思考过程
  let thinking = null;
  let content = m.content;
  const thinkMatch = m.content.match(/💭\s*思考过程[\s\S]*?(?=\n(?:回复|回答|正文|结果|总结|✅|##|---|$))/i);
  if (thinkMatch) {
    thinking = thinkMatch[0].replace(/^💭\s*思考过程[：:]?\s*/, '').trim();
    content = m.content.replace(thinkMatch[0], '').trim();
  }

  let html = '';
  if (thinking) {
    html += '<details class="thinking-fold" ' + (m._thinkingOpen ? 'open' : '') + '>'
      + '<summary><span class="think-dot done"></span> 思考过程</summary>'
      + '<div class="think-body">' + escapeHtml(thinking) + '</div>'
      + '</details>';
  }
  if (m.role !== 'user' && m._streaming) {
    // 流式中间状态：呼吸灯
    html += '<details class="thinking-fold" open>'
      + '<summary><span class="think-dot pulse"></span> 正在思考...</summary></details>';
  }
  html += '<div class="msg-content">' + renderMarkdown(content) + '</div>';
  return html;
}

// ===== 流式消息占位 + SSE =====
function createStreamingRow() {
  const msgs = document.getElementById('msgs');
  const existing = document.getElementById('streamingRow');
  if (existing) return existing;
  const div = document.createElement('div');
  div.className = 'msg-row assistant';
  div.id = 'streamingRow';
  div.innerHTML = ''
    + '<div class="breathing-container" id="breathingContainer">'
    + '<div class="breathing-ring">'
    + '<div class="ring ring-core"></div>'
    + '<div class="ring ring-1"></div>'
    + '<div class="ring ring-2"></div>'
    + '<div class="ring ring-3"></div>'
    + '</div>'
    + '</div>'
    + '<div class="msg-bubble" id="streamingBubble" style="display:none;">'
    + '<div class="msg-content" id="streamingContent"></div>'
    + '</div>';
  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;
  return div;
}

function finishStreaming(replyText, conv) {
  // 如果光圈还在（零没有任何输出），强制关闭
  const container = document.getElementById('breathingContainer');
  if (container) {
    container.classList.add('fade-out');
    setTimeout(function () { if (container) container.remove(); }, 400);
  }
  conv.messages.push({ role: 'assistant', content: replyText });
  saveConversations();
  renderMessages();
}

// ===== Markdown =====
function escapeHtml(s) {
  return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function safeUrl(url) {
  if (!url) return '';
  const trimmed = String(url).trim();
  if (/^javascript:/i.test(trimmed)) return '';
  if (/^data:/i.test(trimmed) && !/^data:image\//i.test(trimmed)) return '';
  return trimmed;
}

function renderMarkdown(text) {
  if (!text) return '';
  let html = String(text);

  // 保护已有的 <details> 块不被转义
  const protectedBlocks = [];
  html = html.replace(/```([\s\S]*?)```/g, function (m, inside) {
    const nl = inside.indexOf('\n');
    const code = nl > 0 ? inside.slice(nl + 1) : inside;
    const lang = nl > 0 ? inside.slice(0, nl).trim() : '';
    const codeHtml = '<pre><code class="' + escapeHtml(lang) + '">' + escapeHtml(code.trim()) + '</code></pre>';
    const folded = '<details class="code-fold"><summary>📄 ' + (lang || '代码') + '</summary>' + codeHtml + '</details>';
    protectedBlocks.push(folded);
    return '\x00PROT_CODE_' + (protectedBlocks.length - 1) + '\x00';
  });

  // 转义 HTML
  html = escapeHtml(html);

  // 恢复代码块
  for (let i = 0; i < protectedBlocks.length; i++) {
    html = html.replace('\x00PROT_CODE_' + i + '\x00', protectedBlocks[i]);
  }

  // 行内 code
  html = html.replace(/`([^`\n]+)`/g, '<code>$1</code>');
  // 加粗/斜体
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
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
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, function(m, t, u) {
    return '<a href="' + safeUrl(u) + '" target="_blank" rel="noopener">' + t + '</a>';
  });
  // 图片 URL
  html = html.replace(/(^|[^"\'\]\)>\n])(https?:\/\/[^\s<]+?\.(?:png|jpe?g|gif|webp)(?:\?[^\s<]*)?)/gim, function(m, p, u) {
    return p + '<a href="' + safeUrl(u) + '" target="_blank" rel="noopener" class="img-link"><img src="' + safeUrl(u) + '" alt="图片" loading="lazy"></a>';
  });
  // 普通 URL
  html = html.replace(/(^|[^"\'\]\)>\n])(https?:\/\/[^\s<]+)(?=\s|$|<|\)|\])/gm, function(m, p, u) {
    return p + '<a href="' + safeUrl(u) + '" target="_blank" rel="noopener">' + u + '</a>';
  });

  // 表格
  html = html.replace(/(\|.+\|\n\|[-:\|]+\|\n(?:\|.+\|\n?)+)/g, function (m) {
    const lines = m.trim().split('\n').filter(function (l) { return l.trim(); });
    if (lines.length < 2) return m;
    const header = lines[0].slice(1, -1).split('|').map(function (c) { return '<th>' + c.trim() + '</th>'; }).join('');
    const body = lines.slice(2).map(function (line) {
      return '<tr>' + line.slice(1, -1).split('|').map(function (c) { return '<td>' + c.trim() + '</td>'; }).join('') + '</tr>';
    }).join('');
    return '<details class="code-fold"><summary>📊 表格</summary><table><thead><tr>' + header + '</tr></thead><tbody>' + body + '</tbody></table></details>';
  });

  // 列表
  html = html.replace(/((?:^[-*] .+\n?)+)/gm, function (m) {
    const items = m.trim().split('\n').map(function (l) { return '<li>' + l.replace(/^[-*] /, '') + '</li>'; }).join('');
    return '<ul>' + items + '</ul>';
  });
  html = html.replace(/((?:^\d+\. .+\n?)+)/gm, function (m) {
    const items = m.trim().split('\n').map(function (l) { return '<li>' + l.replace(/^\d+\. /, '') + '</li>'; }).join('');
    return '<ol>' + items + '</ol>';
  });

  // 段落
  html = html.replace(/\n{2,}/g, '</p><p>');
  html = '<p>' + html + '</p>';
  html = html.replace(/<p>\s*<\/p>/g, '');
  html = html.replace(/\n/g, '<br>');

  if (typeof DOMPurify !== 'undefined') {
    return DOMPurify.sanitize(html, { ALLOWED_TAGS: ['a','b','i','em','strong','code','pre','ul','ol','li','h1','h2','h3','h4','blockquote','img','table','thead','tbody','tr','th','td','hr','br','p','span','div','details','summary'], ALLOWED_ATTR: ['href','title','target','rel','src','alt','class','loading'] });
  }
  // DOMPurify 未加载的回退：至少移除危险标签
  return html.replace(/<script[\s\S]*?<\/script>/gi, '').replace(/<\/?(?:script|iframe|object|embed|link|meta)[^>]*>/gi, '');
}

// ===== 输入 =====
function autoResize(ta) {
  ta.style.height = 'auto';
  ta.style.height = Math.min(ta.scrollHeight, 150) + 'px';
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
  el.classList.toggle('open', show);
  if (bd) bd.classList.toggle('show', show);
}

function sendAsMsg(text) {
  document.getElementById('inp').value = text;
  send();
}

// ===== 文件上传 =====
function attachFile() {
  document.getElementById('fileInput').click();
}

function handleFileSelect(e) {
  const file = e.target.files[0];
  if (!file) return;
  if (file.size > 10 * 1024 * 1024) { alert('文件大小超过 10MB 限制'); return; }
  pendingFile = file;
  document.getElementById('filePreview').style.display = 'flex';
  document.getElementById('fileName').textContent = file.name;
}

function clearFile() {
  pendingFile = null;
  document.getElementById('filePreview').style.display = 'none';
  document.getElementById('fileInput').value = '';
}

async function uploadPendingFile() {
  if (!pendingFile) return null;
  const formData = new FormData();
  formData.append('file', pendingFile);
  try {
    const resp = await fetch('/api/upload', { method: 'POST', body: formData });
    if (!resp.ok) throw new Error('Upload failed');
    const result = await resp.json();
    const f = (result.files || [])[0];
    clearFile();
    return f ? f.name : null;
  } catch (e) {
    console.warn('upload error', e);
    return null;
  }
}

// ===== 认证 =====
function unlock() {
  const code = document.getElementById('code').value.trim();
  if (!code) return;
  fetch('/api/auth', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code: code })
  }).then(function (r) { return r.json(); }).then(function (d) {
    if (d.ok) {
      document.getElementById('login').classList.add('hidden');
      document.getElementById('userStatus').textContent = '已解锁';
      loadConversations();
      renderSidebar();
      if (currentConvId && conversations.find(function (c) { return c.id === currentConvId; })) {
        renderMessages();
      } else { renderWelcome(); }
    } else {
      document.getElementById('err').textContent = '暗号错误，请重试';
    }
  }).catch(function () { document.getElementById('err').textContent = '网络错误，请重试'; });
}
document.getElementById('code').addEventListener('keydown', function (e) { if (e.key === 'Enter') unlock(); });

// ===== 发送消息 =====
let _abortController = null;

async function send() {
  const inp = document.getElementById('inp');
  const text = inp.value.trim();
  if (!text || isSending) return;
  isSending = true;
  document.getElementById('sendBtn').disabled = true;

  // 设置 Agent breathing
  resetAllAgentDots();
  const aid = currentAgentId || 'zero';
  setAgentStatus(aid, 'thinking', '工作中...');

  const conv = getOrCreateCurrentConv();
  conv.messages.push({ role: 'user', content: text });
  saveConversations();
  updateCurrentConvTitle(text);

  // 上传文件
  let fName = null;
  if (pendingFile) {
    fName = await uploadPendingFile();
  }

  inp.value = '';
  inp.style.height = 'auto';
  renderMessages();
  createStreamingRow();
  document.getElementById('topbarStatus').textContent = '回复中...';

  // 带超时的 SSE 流式请求
  _abortController = new AbortController();
  const timeoutId = setTimeout(function () {
    _abortController.abort();
    showStreamError('响应超时（30 秒无数据），请重试');
    finishSend();
  }, 30000);

  let accumulatedReply = '';
  let hasData = false;
  let streamFinished = false;

  // Bug 2: 拼接文件信息到消息文本
  let messageText = text;
  if (fName) {
    const isImage = /\.(png|jpg|jpeg|gif|webp)$/i.test(fName);
    if (isImage) {
      messageText = text + '\n\n[用户上传了一张图片：' + fName + ']\n![图片](/api/download/' + encodeURIComponent(fName) + ')';
    } else {
      messageText = text + '\n\n[用户上传了文件：' + fName + ']';
    }
  }

  try {
    const url = '/api/chat/stream?m=' + encodeURIComponent(messageText)
      + (currentAgentId ? '&agent=' + encodeURIComponent(currentAgentId) : '')
      + '&perm=' + currentPermissionLevel;
    const resp = await fetch(url, { signal: _abortController.signal });

    clearTimeout(timeoutId);

    if (!resp.ok) {
      // 回退 POST — Bug 2: 使用包含文件信息的 messageText
      await fallbackPost(conv, messageText);
      finishSend();
      return;
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buf = '';

    // 重置超时：每收到数据就延长
    let dataTimeout = setTimeout(function () {
      if (!hasData) {
        showStreamError('服务器无响应，请重试');
        finishSend();
      }
    }, 15000);

    function processLine(line) {
      if (!line.startsWith('data:')) return;
      try {
        const d = JSON.parse(line.substring(5));
        hasData = true;
        if (d.type === 'chunk') {
          accumulatedReply += d.data;
          updateStreamingContent(accumulatedReply);
        } else if (!d.type && d.data) {
          // 兼容无 type 字段的流式数据
          accumulatedReply += d.data;
          updateStreamingContent(accumulatedReply);
        } else if (d.type === 'done') {
          // SSE 完成 — Bug 1 防止重复
          if (streamFinished) return;
          streamFinished = true;
          clearTimeout(dataTimeout);
          clearTimeout(timeoutId);
          finishStreaming(accumulatedReply, conv);
          setAgentStatus(aid, 'done', '');
          document.getElementById('topbarStatus').textContent = '';
          setTimeout(function () { setAgentStatus(aid, 'online', ''); }, 2000);
        } else if (d.type === 'status') {
          // 更新 Agent status（呼吸光圈已替代旧思考面板）
          setAgentStatus(aid, 'thinking', d.data);
        } else if (d.type === 'error') {
          clearTimeout(dataTimeout);
          showStreamError(d.data || '服务器返回错误');
        } else if (d.type === 'approval_required') {
          showApprovalDialog(d.data, d.request_id);
        }
      } catch (e) {}
    }

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop() || '';
      for (const line of lines) processLine(line);
    }

    // 流正常结束但没收到 done 事件 — Bug 1 防止重复
    if (accumulatedReply && !streamFinished) {
      streamFinished = true;
      finishStreaming(accumulatedReply, conv);
      setAgentStatus(aid, 'done', '');
      document.getElementById('topbarStatus').textContent = '';
      setTimeout(function () { setAgentStatus(aid, 'online', ''); }, 2000);
    }

  } catch (err) {
    clearTimeout(timeoutId);
    if (err.name === 'AbortError') {
      // 超时已经处理
    } else {
      showStreamError('连接错误：' + (err.message || err));
    }
  }

  finishSend();

  function finishSend() {
    // 清除所有定时器
    clearTimeout(timeoutId);
    if (typeof dataTimeout !== 'undefined') clearTimeout(dataTimeout);
    isSending = false;
    document.getElementById('sendBtn').disabled = false;
    if (!currentConvId) resetAllAgentDots();
    document.getElementById('topbarStatus').textContent = '';
    inp.focus();
  }
}

async function fallbackPost(conv, text) {
  try {
    const resp = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, agent_id: currentAgentId, permission_level: currentPermissionLevel })
    });
    if (!resp.ok) throw new Error('请求失败 (' + resp.status + ')');
    const d = await resp.json();
    finishStreaming(d.reply || '(空回复)', conv);
    setAgentStatus(currentAgentId || 'zero', 'done', '');
  } catch (e) {
    showStreamError('请求失败：' + (e.message || e));
    conv.messages.push({ role: 'assistant', content: '[错误] ' + (e.message || e) });
    saveConversations();
    renderMessages();
  }
}

function updateStreamingContent(text) {
  const el = document.getElementById('streamingContent');
  if (!el) return;
  // 首次收到内容时：淡出光圈，显示气泡
  const container = document.getElementById('breathingContainer');
  const bubble = document.getElementById('streamingBubble');
  if (container && container.style.opacity !== '0') {
    container.classList.add('fade-out');
    if (bubble) {
      bubble.style.display = 'block';
      bubble.classList.add('fade-in');
    }
    // 动画结束后移除光圈 DOM
    setTimeout(function () {
      if (container) container.remove();
    }, 400);
  }
  el.innerHTML = renderMarkdown(text);
  const msgs = document.getElementById('msgs');
  msgs.scrollTop = msgs.scrollHeight;
}

function showStreamError(msg) {
  // 强制关闭呼吸光圈
  const container = document.getElementById('breathingContainer');
  if (container) {
    container.classList.add('fade-out');
    setTimeout(function () { if (container) container.remove(); }, 400);
  }
  updateStreamingContent('<span style="color:#fb2c36;">' + escapeHtml(msg) + '</span>');
  const bubble = document.getElementById('streamingBubble');
  if (bubble) {
    bubble.style.display = 'block';
    const retryBtn = document.createElement('div');
    retryBtn.className = 'retry-area';
    retryBtn.innerHTML = '<button class="retry-btn" onclick="retryLastSend()">↻ 重试</button>';
    bubble.appendChild(retryBtn);
  }
  // 清除 Agent thinking 状态
  resetAllAgentDots();
}

function retryLastSend() {
  // 重试：找最后一条用户消息
  const conv = conversations.find(function (c) { return c.id === currentConvId; });
  if (!conv || !conv.messages.length) return;
  // 删掉最后一条 assistant 回复（如果是错误回复）
  const last = conv.messages[conv.messages.length - 1];
  if (last && last.role === 'assistant') conv.messages.pop();
  // 找到最后的用户消息
  const lastUser = [...conv.messages].reverse().find(function (m) { return m.role === 'user'; });
  if (lastUser) {
    document.getElementById('inp').value = lastUser.content;
    saveConversations();
    send();
  }
}

function finishSend() {
  isSending = false;
  document.getElementById('sendBtn').disabled = false;
  if (!currentConvId) resetAllAgentDots();
}

// ===== 重新生成 =====
function regenerate(idx) {
  const conv = conversations.find(function (c) { return c.id === currentConvId; });
  if (!conv || idx < 0 || idx >= conv.messages.length) return;
  // 删掉这条和之后的消息
  conv.messages = conv.messages.slice(0, idx);
  saveConversations();
  // 找到前一条用户消息
  const prevUser = [...conv.messages].reverse().find(function (m) { return m.role === 'user'; });
  if (prevUser) {
    document.getElementById('inp').value = prevUser.content;
    renderMessages();
    send();
  } else {
    renderMessages();
  }
}

// ===== 图片灯箱 =====
let currentLightboxUrl = '';

function openLightbox(url) {
  currentLightboxUrl = url;
  const proxyUrl = '/api/image-proxy?url=' + encodeURIComponent(url);
  document.getElementById('lightboxImg').src = url;
  document.getElementById('lightboxDownload').onclick = function (e) {
    e.stopPropagation();
    const a = document.createElement('a');
    a.href = proxyUrl;
    a.download = url.split('/').pop().split('?')[0] || 'image.png';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };
  document.getElementById('lightbox').classList.add('show');
  document.getElementById('lightbox').focus();
}

function closeLightbox(e) {
  if (e && e.target && e.target !== document.getElementById('lightbox') && !e.target.closest('.lightbox-content')) return;
  document.getElementById('lightbox').classList.remove('show');
}

// 灯箱 keyboard 事件
document.getElementById('lightbox').addEventListener('keydown', function (e) {
  if (e.key === 'Escape') closeLightbox();
});

// ===== 消息操作 =====
function copyMessage(idx) {
  const conv = conversations.find(function (c) { return c.id === currentConvId; });
  if (!conv) return;
  const msg = conv.messages[idx];
  if (!msg) return;
  navigator.clipboard.writeText(msg.content).then(function () {
    // 简单反馈
    const btns = document.querySelectorAll('.msg-btn');
    if (btns[idx]) {
      btns[idx].style.color = '#4ade80';
      setTimeout(function () { btns[idx].style.color = ''; }, 800);
    }
    showToast('已复制', 'success');
  }).catch(function (e) {
    // 降级：用 textarea
    const ta = document.createElement('textarea');
    ta.value = msg.content;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
  });
}

// ===== 健康检查 =====
fetch('/health').then(function (r) { return r.json(); }).then(function (d) {
  if (d.session && d.session.indexOf('已解锁') >= 0) {
    document.getElementById('login').classList.add('hidden');
    loadConversations();
    renderSidebar();
    if (currentConvId && conversations.find(function (c) { return c.id === currentConvId; })) {
      renderMessages();
    } else { renderWelcome(); }
  } else {
    loadConversations();
    renderSidebar();
  }
  // Add theme toggle button
    const topbarStatus = document.getElementById('topbarStatus');
    if (topbarStatus) {
      const themeBtn = document.createElement('button');
      themeBtn.className = 'theme-toggle';
      themeBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>';
      themeBtn.onclick = toggleTheme;
      topbarStatus.appendChild(themeBtn);
    }
    // 心跳检测
  setInterval(function () {
    fetch('/health').then(function (r) { return r.json(); }).then(function (s) {
      document.getElementById('offlineBanner').style.display = 'none';
      if (!s.session || s.session.indexOf('已解锁') < 0) {
        document.getElementById('topbarStatus').textContent = '会话已锁定';
      }
    }).catch(function () {
      document.getElementById('offlineBanner').style.display = 'flex';
    });
  }, 10000);
}).catch(function () {
  loadConversations();
  renderSidebar();
});

function reconnectServer() {
  document.getElementById('offlineBanner').style.display = 'none';
  window.location.reload();
}

// ===== 绑定图片点击 =====
function bindImageClicks() {
  document.querySelectorAll('.img-link').forEach(function (a) {
    a.addEventListener('click', function (e) {
      e.preventDefault();
      openLightbox(this.href);
    });
  });
}

// ===== Token 统计 =====
async function refreshTokenStats() {
  try {
    const resp = await fetch('/api/tokens');
    const data = await resp.json();
    document.getElementById('tokenTotal').textContent = data.total_tokens || 0;
    document.getElementById('tokenCost').textContent = (data.total_cost || 0).toFixed(6);
    document.getElementById('tokenCache').textContent = (data.cache_hit_rate || 0) + '%';
  } catch (e) {}
}
setInterval(refreshTokenStats, 5000);
refreshTokenStats();

// ===== 移动端键盘适配 =====
if ('visualViewport' in window) {
  window.visualViewport.addEventListener('resize', function () {
    const inputArea = document.querySelector('.input-area');
    if (inputArea) {
      const diff = window.innerHeight - window.visualViewport.height;
      inputArea.style.paddingBottom = Math.max(12, diff + 12) + 'px';
    }
    document.getElementById('msgs').scrollTop = document.getElementById('msgs').scrollHeight;
  });
}

// ===== Toast 通知系统 =====
function showToast(msg, type, duration) {
  // 默认值
  type = type || 'info';
  duration = duration || 3000;

  // 创建 Toast 容器（如果不存在）
  let container = document.getElementById('toastContainer');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toastContainer';
    container.className = 'toast-container';
    document.body.appendChild(container);
  }

  // 创建 Toast
  const toast = document.createElement('div');
  toast.className = 'toast toast-' + type;
  toast.textContent = msg;

  // 添加到容器
  container.appendChild(toast);

  // 自动移除
  setTimeout(function() {
    toast.classList.add('toast-hide');
    setTimeout(function() { toast.remove(); }, 300);
  }, duration);
}

// ===== 确认弹窗 =====
function confirmDialog(msg) {
  return new Promise(function(resolve) {
    // 创建遮罩
    const overlay = document.createElement('div');
    overlay.className = 'confirm-overlay';

    // 创建确认框
    const box = document.createElement('div');
    box.className = 'confirm-box';

    box.innerHTML =
      '<div class="confirm-msg">' + escapeHtml(msg) + '</div>' +
      '<div class="confirm-actions">' +
        '<button class="confirm-btn confirm-cancel">取消</button>' +
        '<button class="confirm-btn confirm-ok">确认</button>' +
      '</div>';

    overlay.appendChild(box);
    document.body.appendChild(overlay);

    // 延迟显示（用于动画）
    setTimeout(function() { overlay.classList.add('show'); }, 10);

    // 绑定事件
    box.querySelector('.confirm-ok').onclick = function() {
      overlay.classList.remove('show');
      setTimeout(function() { overlay.remove(); resolve(true); }, 200);
    };
    box.querySelector('.confirm-cancel').onclick = function() {
      overlay.classList.remove('show');
      setTimeout(function() { overlay.remove(); resolve(false); }, 200);
    };
    overlay.onclick = function(e) {
      if (e.target === overlay) {
        overlay.classList.remove('show');
        setTimeout(function() { overlay.remove(); resolve(false); }, 200);
      }
    };

    // Esc 键关闭
    function onKey(e) {
      if (e.key === 'Escape') {
        overlay.classList.remove('show');
        overlay.remove();
        document.removeEventListener('keydown', onKey);
        resolve(false);
      }
    }
    document.addEventListener('keydown', onKey);
  });
}

// ===== 审批弹窗 =====
function showApprovalDialog(command, requestId) {
  var overlay = document.createElement('div');
  overlay.className = 'approval-overlay';
  overlay.innerHTML =
    '<div class="approval-box">'
    + '<div class="approval-title">⚠️ 命令执行审批</div>'
    + '<div class="approval-cmd">' + escapeHtml(command || '') + '</div>'
    + '<div class="approval-actions">'
    + '<button class="approval-btn approval-deny" id="approvalDeny">拒绝</button>'
    + '<button class="approval-btn approval-allow" id="approvalAllow">允许</button>'
    + '</div></div>';
  document.body.appendChild(overlay);

  document.getElementById('approvalDeny').onclick = function () {
    overlay.remove();
    fetch('/api/approval/' + requestId, { method: 'POST', body: JSON.stringify({ approved: false }) });
  };
  document.getElementById('approvalAllow').onclick = function () {
    overlay.remove();
    fetch('/api/approval/' + requestId, { method: 'POST', body: JSON.stringify({ approved: true }) });
  };
}

// ===== 全局键盘导航 =====
document.addEventListener('keydown', function(e) {
  // Esc 关闭灯箱
  if (e.key === 'Escape') {
    const lb = document.getElementById('lightbox');
    if (lb && lb.classList.contains('show')) {
      closeLightbox();
      e.preventDefault();
      return;
    }
    // 确认弹窗已由 confirmDialog 处理，这里不需要重复处理
  }

  // Ctrl+Enter 发送消息（备选快捷键）
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    const inp = document.getElementById('inp');
    if (inp === document.activeElement && inp.value.trim()) {
      e.preventDefault();
      send();
    }
  }
});

// ===== 焦点管理 =====
function trapFocus(container, event) {
  // 在弹窗打开时循环 Tab 焦点
  const focusable = container.querySelectorAll(
    'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
  );
  if (focusable.length === 0) return;

  const first = focusable[0];
  const last = focusable[focusable.length - 1];

  if (event.key === 'Tab') {
    if (event.shiftKey) {
      if (document.activeElement === first) {
        event.preventDefault();
        last.focus();
      }
    } else {
      if (document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
  }
}

// ===== 图片灯箱焦点管理增强 =====
// 在灯箱中启用焦点循环
document.getElementById('lightbox').addEventListener('keydown', function(e) {
  if (e.key === 'Tab') {
    trapFocus(this, e);
  }
});

// ===== 右侧面板 =====

// DOM ready 辅助
function ready(fn) {
  if (document.readyState !== 'loading') fn();
  else document.addEventListener('DOMContentLoaded', fn);
}

// 面板状态：桌面端默认显示，移动端默认隐藏
function getRightPanelState() {
  var stored = localStorage.getItem('zero_right_panel');
  if (stored !== null) return stored === 'true';
  return window.innerWidth > 768;
}

function setRightPanelState(visible) {
  try { localStorage.setItem('zero_right_panel', visible ? 'true' : 'false'); } catch (e) {}
}

// 创建分区容器
function createRightSection(title) {
  var section = document.createElement('div');
  section.className = 'right-panel-section';
  var h = document.createElement('div');
  h.className = 'right-panel-section-title';
  h.textContent = title;
  section.appendChild(h);
  return section;
}

// 初始化右侧面板：创建切换按钮和面板容器
function initRightPanel() {
  // 切换按钮 → 插入 topbar
  var topbarStatus = document.getElementById('topbarStatus');
  if (topbarStatus) {
    var toggleBtn = document.createElement('button');
    toggleBtn.className = 'right-panel-toggle';
    toggleBtn.id = 'rightPanelToggle';
    toggleBtn.title = '切换右侧面板';
    toggleBtn.setAttribute('aria-label', '切换右侧面板');
    toggleBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="9" y1="3" x2="9" y2="21"/></svg>';
    topbarStatus.appendChild(toggleBtn);
  }

  // 面板容器 → 追加到 #app
  var panel = document.createElement('div');
  panel.className = 'right-panel';
  panel.id = 'rightPanel';
  if (!getRightPanelState()) {
    panel.classList.add('hidden');
  }

  var app = document.getElementById('app');
  if (app) {
    app.appendChild(panel);
  }

  // 切换按钮 → 点击事件
  var btn = document.getElementById('rightPanelToggle');
  if (btn) {
    btn.addEventListener('click', function () {
      var p = document.getElementById('rightPanel');
      if (!p) return;
      var isHidden = p.classList.contains('hidden');
      if (isHidden) {
        p.classList.remove('hidden');
      } else {
        p.classList.add('hidden');
      }
      setRightPanelState(isHidden); // hidden 之前的状态 → 取反
      // 切换后立即刷新内容
      if (!isHidden) renderRightPanel();
    });
  }

  // 窗口 resize 时，桌面端自动适配
  window.addEventListener('resize', function () {
    var p = document.getElementById('rightPanel');
    if (!p) return;
    if (window.innerWidth > 768) {
      // 桌面端：按 localStorage 决定
      if (getRightPanelState()) {
        p.classList.remove('hidden');
      } else {
        p.classList.add('hidden');
      }
    } else {
      // 移动端：默认隐藏
      p.classList.add('hidden');
    }
  });
}

// Bug 3 防闪烁：首次建 DOM 结构，后续仅增量更新
var _rightPanelBuilt = false;

// 渲染整个右侧面板
function renderRightPanel() {
  var panel = document.getElementById('rightPanel');
  if (!panel) return;
  if (panel.classList.contains('hidden')) return;

  // 首次调用：构建分区 DOM 结构
  if (!_rightPanelBuilt) {
    panel.innerHTML = '';
    var agentSection = createRightSection('Agent 状态');
    var tokenSection = createRightSection('Token 仪表');
    var timelineSection = createRightSection('步骤时间轴');
    var memorySection = createRightSection('记忆');
    var behaviorSection = createRightSection('行为评估');

    panel.appendChild(agentSection);
    panel.appendChild(tokenSection);
    panel.appendChild(timelineSection);
    panel.appendChild(memorySection);
    panel.appendChild(behaviorSection);
    _rightPanelBuilt = true;
  }

  // 后续调用：只更新已有分区内容，不重建 DOM
  var sections = panel.querySelectorAll('.right-panel-section');
  if (sections.length >= 5) {
    renderRightAgentList(sections[0]);
    renderRightTokenMeter(sections[1]);
    renderRightTimeline(sections[2]);
    renderRightMemory(sections[3]);
    renderRightBehavior(sections[4]);
  }
}

// Bug 3: Agent 状态列表 — 缓存避免重复渲染
var _lastAgentListHTML = '';

function renderRightAgentList(container) {
  var agents = [
    { id: 'zero', name: '零 · 路由' },
    { id: 'agnes_text', name: 'Agnes 2.0' },
    { id: 'reasonix', name: 'Reasonix' },
    { id: 'tavily', name: 'Tavily' }
  ];

  var html = '';
  agents.forEach(function (agent) {
    var dotEl = document.getElementById('dot_' + agent.id);
    var statusEl = document.getElementById('status_' + agent.id);

    var dotClass = 'right-agent-dot';
    if (dotEl) {
      var cls = dotEl.className.replace('agent-dot', '').trim();
      if (cls) dotClass += ' ' + cls;
    }

    var statusText = statusEl ? (statusEl.textContent || '') : '';

    html += '<div class="right-agent-item">'
      + '<span class="' + dotClass + '"></span>'
      + '<span class="right-agent-name">' + escapeHtml(agent.name) + '</span>'
      + '<span class="right-agent-status">' + escapeHtml(statusText) + '</span>'
      + '</div>';
  });

  if (html === _lastAgentListHTML) return;  // 无变化，跳过
  _lastAgentListHTML = html;

  // 清除旧 agent-item，保留标题
  var old = container.querySelectorAll('.right-agent-item');
  for (var i = 0; i < old.length; i++) old[i].remove();
  // 插入新 HTML
  var temp = document.createElement('div');
  temp.innerHTML = html;
  while (temp.firstChild) container.appendChild(temp.firstChild);
}

// Bug 3: Token 仪表 — 缓存避免重复渲染
var _lastTokenMeterHTML = '';

function renderRightTokenMeter(container) {
  var totalEl = document.getElementById('tokenTotal');
  var costEl = document.getElementById('tokenCost');
  var cacheEl = document.getElementById('tokenCache');

  var rows = [
    { label: 'tokens', value: totalEl ? totalEl.textContent : '0' },
    { label: 'cost', value: '$' + (costEl ? costEl.textContent : '0.00') },
    { label: 'cache', value: (cacheEl ? cacheEl.textContent : '0%') }
  ];

  var html = '';
  rows.forEach(function (row) {
    html += '<div class="right-token-row">'
      + '<span class="right-token-label">' + escapeHtml(row.label) + '</span>'
      + '<span class="right-token-value">' + escapeHtml(row.value) + '</span>'
      + '</div>';
  });

  if (html === _lastTokenMeterHTML) return;  // 无变化，跳过
  _lastTokenMeterHTML = html;

  // 清除旧行，保留标题
  var old = container.querySelectorAll('.right-token-row');
  for (var i = 0; i < old.length; i++) old[i].remove();
  // 插入新 HTML
  var temp = document.createElement('div');
  temp.innerHTML = html;
  while (temp.firstChild) container.appendChild(temp.firstChild);
}

// Bug 3: 步骤时间轴 — 缓存避免重复渲染
var _lastTimelineHTML = '';

function renderRightTimeline(container) {
  container.id = 'rightTimelineContainer';
  fetch('/api/kanban')
    .then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    })
    .then(function (data) {
      var tasks = data.tasks || [];
      var html = '<div class="right-panel-section-title">步骤时间轴</div>';

      // 输入行
      html += '<div class="kanban-input-row">'
        + '<input class="kanban-input" id="kanbanInput" placeholder="新任务标题..." onkeydown="if(event.key===\'Enter\'){var v=this.value.trim();if(v){kanbanCreateTask(v);this.value=\'\';}}">'
        + '<button class="kanban-add-btn" onclick="var inp=document.getElementById(\'kanbanInput\');var v=inp.value.trim();if(v){kanbanCreateTask(v);inp.value=\'\';}">添加</button>'
        + '</div>';

      // 任务列表
      if (tasks.length === 0) {
        html += '<div style="font-size:11px;color:var(--muted);padding:8px 0;">暂无任务</div>';
      } else {
        tasks.forEach(function (t) {
          var isDone = t.status === 'done';
          html += '<div class="kanban-item">'
            + '<button class="kanban-toggle-btn' + (isDone ? ' done' : '') + '" onclick="kanbanToggleTask(' + t.id + ',\'' + t.status + '\')">'
            + (isDone ? '✓' : '') + '</button>'
            + '<span class="kanban-item-title' + (isDone ? ' done' : '') + '">' + escapeHtml(t.title || '') + '</span>'
            + '<button class="kanban-delete-btn" onclick="kanbanDeleteTask(' + t.id + ')">✕</button>'
            + '</div>';
        });
      }

      if (html === _lastTimelineHTML) return;  // 无变化，跳过
      _lastTimelineHTML = html;
      container.innerHTML = html;
    })
    .catch(function () {
      container.innerHTML = '<div class="right-panel-section-title">步骤时间轴</div>'
        + '<div style="font-size:11px;color:#fb2c36;padding:8px 0;">加载失败</div>';
    });
}

// ===== 看板 CRUD 交互 =====
async function kanbanCreateTask(title) {
  try {
    var resp = await fetch('/api/kanban', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: title })
    });
    var data = await resp.json();
    if (data.ok) {
      showToast('任务已创建', 'success');
      renderRightTimeline(document.getElementById('rightTimelineContainer'));
    } else {
      showToast(data.error && data.error.msg ? data.error.msg : '创建失败', 'error');
    }
  } catch (e) {
    showToast('网络错误: ' + e.message, 'error');
  }
}

async function kanbanToggleTask(id, currentStatus) {
  var newStatus = currentStatus === 'done' ? 'pending' : 'done';
  try {
    var resp = await fetch('/api/kanban/' + id, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: newStatus })
    });
    var data = await resp.json();
    if (data.ok) {
      showToast(newStatus === 'done' ? '任务已完成' : '任务已恢复', 'success');
      renderRightTimeline(document.getElementById('rightTimelineContainer'));
    } else {
      showToast(data.error && data.error.msg ? data.error.msg : '更新失败', 'error');
    }
  } catch (e) {
    showToast('网络错误: ' + e.message, 'error');
  }
}

async function kanbanDeleteTask(id) {
  var confirmed = await confirmDialog('确定要删除此任务吗？');
  if (!confirmed) return;
  try {
    var resp = await fetch('/api/kanban/' + id, {
      method: 'DELETE'
    });
    var data = await resp.json();
    if (data.ok) {
      showToast('任务已删除', 'info');
      renderRightTimeline(document.getElementById('rightTimelineContainer'));
    } else {
      showToast(data.error && data.error.msg ? data.error.msg : '删除失败', 'error');
    }
  } catch (e) {
    showToast('网络错误: ' + e.message, 'error');
  }
}

// Bug 3: 记忆面板 — 缓存避免重复渲染
var _lastMemoryHTML = '';

function renderRightMemory(container) {
  if (!container) return;
  container.id = 'rightMemoryContainer';

  fetch('/api/memory?limit=10')
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (!data.ok || !data.memories) {
        container.innerHTML = '<div style="font-size:11px;color:var(--muted);padding:8px 0;">暂无记忆</div>';
        return;
      }
      var html = '<div class="right-panel-section-title">记忆</div>';
      html += '<div class="memory-search-row">'
        + '<input class="memory-search-input" id="memorySearchInput" placeholder="搜索记忆..." onkeydown="if(event.key===\'Enter\'){memorySearch(this.value);}">'
        + '</div>';

      if (data.memories.length === 0) {
        html += '<div style="font-size:11px;color:var(--muted);padding:8px 0;">暂无记忆</div>';
      } else {
        data.memories.forEach(function (m) {
          html += '<div class="memory-item">'
            + '<div class="memory-item-title">' + escapeHtml(m.title || '') + '</div>'
            + '<div class="memory-item-summary">' + escapeHtml((m.summary || m.content || '').slice(0, 60)) + '</div>'
            + '<button class="memory-delete-btn" onclick="memoryDelete(' + m.id + ')">✕</button>'
            + '</div>';
        });
      }
      if (html === _lastMemoryHTML) return;  // 无变化，跳过
      _lastMemoryHTML = html;
      container.innerHTML = html;
    })
    .catch(function () {
      container.innerHTML = '<div style="font-size:11px;color:#fb2c36;padding:8px 0;">加载失败</div>';
    });
}

// 记忆搜索函数
function memorySearch(query) {
  var container = document.getElementById('rightMemoryContainer');
  if (!container) return;
  fetch('/api/memory?q=' + encodeURIComponent(query) + '&limit=10')
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (!data.ok) return;
      var html = '<div class="right-panel-section-title">记忆 · 搜索</div>';
      html += '<div style="font-size:11px;color:var(--muted);padding:4px 0;">"' + escapeHtml(query) + '" 的搜索结果：</div>';
      if (!data.memories || data.memories.length === 0) {
        html += '<div style="font-size:11px;color:var(--muted);padding:8px 0;">无匹配结果</div>';
      } else {
        data.memories.forEach(function (m) {
          html += '<div class="memory-item">'
            + '<div class="memory-item-title">' + escapeHtml(m.title || '') + '</div>'
            + '<div class="memory-item-summary">' + escapeHtml((m.summary || m.content || '').slice(0, 60)) + '</div>'
            + '<button class="memory-delete-btn" onclick="memoryDelete(' + m.id + ')">✕</button>'
            + '</div>';
        });
      }
      container.innerHTML = html;
      var backBtn = document.createElement('button');
      backBtn.className = 'memory-back-btn';
      backBtn.textContent = '← 返回全部';
      backBtn.onclick = function () { renderRightMemory(container); };
      container.appendChild(backBtn);
    });
}

function memoryDelete(id) {
  confirmDialog('确定要删除这条记忆吗？').then(function (confirmed) {
    if (!confirmed) return;
    fetch('/api/memory/' + id, { method: 'DELETE' })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.ok) {
          showToast('记忆已删除', 'info');
          renderRightMemory(document.getElementById('rightMemoryContainer'));
        } else {
          showToast(data.error && data.error.msg ? data.error.msg : '删除失败', 'error');
        }
      })
      .catch(function () { showToast('网络错误', 'error'); });
  });
}

// Bug 3: 行为评估面板 — 缓存避免重复渲染
var _lastBehaviorHTML = '';

function renderRightBehavior(container) {
  if (!container) return;
  container.id = 'rightBehaviorContainer';

  fetch('/api/behavior/control')
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (!data.ok) {
        container.innerHTML = '<div style="font-size:11px;color:var(--muted);padding:8px 0;">暂无数据</div>';
        return;
      }

      var html = '';

      if (data.controls) {
        var types = Object.keys(data.controls);
        types.forEach(function (t) {
          var c = data.controls[t];
          var barWidth = Math.round(c.control_strength * 100);
          var tempColor = c.temperature > 0.6 ? '#fbbf24' : (c.temperature > 0.4 ? '#3b82f6' : '#4ade80');
          html += '<div class="behavior-row">'
            + '<div class="behavior-label">' + t + '</div>'
            + '<div class="behavior-bar-bg">'
            + '<div class="behavior-bar" style="width:' + barWidth + '%;background:' + tempColor + ';"></div>'
            + '</div>'
            + '<div class="behavior-value">' + barWidth + '%</div>'
            + '</div>';
        });
      } else if (data.control_strength !== undefined) {
        var sw = Math.round(data.control_strength * 100);
        html += '<div class="behavior-row">'
          + '<div class="behavior-label">' + escapeHtml(data.task_type || '') + '</div>'
          + '<div class="behavior-bar-bg">'
          + '<div class="behavior-bar" style="width:' + sw + '%;"></div>'
          + '</div>'
          + '<div class="behavior-value">' + sw + '%</div>'
          + '</div>';
        html += '<div style="font-size:11px;color:var(--muted);margin-top:4px;">温度: ' + data.temperature + '</div>';
      }

      if (html === _lastBehaviorHTML) return;  // 无变化，跳过
      _lastBehaviorHTML = html;
      container.innerHTML = html;
    })
    .catch(function () {
      container.innerHTML = '<div style="font-size:11px;color:#fb2c36;padding:8px 0;">加载失败</div>';
    });
}

// 初始化右侧面板
ready(function () {
  // 权限等级选择器初始化
  renderPermissionSelector();
  initRightPanel();
  renderRightPanel();
  // 每 10 秒刷新面板数据
  setInterval(renderRightPanel, 10000);
});
