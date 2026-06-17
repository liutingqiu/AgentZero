// ===== 零 · 前端主程序 =====
// ===== 状态管理 =====
let conversations = [];
let currentConvId = null;
let currentAgentId = '';
let isSending = false;
let pendingFile = null;

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
    return '<div class="conv-item' + (isActive ? ' active' : '') + '" onclick="loadConv(\'' + c.id + '\')" title="' + escapeHtml(c.title || '') + '">'
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

// ===== 对话管理 =====
function newChat() {
  currentConvId = null;
  renderSidebar();
  renderWelcome();
  if (window.innerWidth <= 768) toggleSidebar(false);
}

function deleteConv(id) {
  conversations = conversations.filter(function (c) { return c.id !== id; });
  if (currentConvId === id) { currentConvId = null; renderWelcome(); }
  renderSidebar();
  saveConversations();
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
  div.innerHTML = '<div class="msg-bubble" id="streamingBubble">'
    + '<details class="thinking-fold" open id="streamingThink">'
    + '<summary><span class="think-dot pulse"></span> <span id="streamingThinkText">正在思考...</span></summary>'
    + '<div class="think-body" id="streamingThinkBody"></div>'
    + '</details>'
    + '<div class="msg-content" id="streamingContent"></div>'
    + '</div></div>';
  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;
  return div;
}

function finishStreaming(replyText, conv) {
  conv.messages.push({ role: 'assistant', content: replyText });
  saveConversations();
  renderMessages();
}

// ===== Markdown =====
function escapeHtml(s) {
  return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
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
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  // 图片 URL
  html = html.replace(/(^|[^"\'\]\)>\n])(https?:\/\/[^\s<]+?\.(?:png|jpe?g|gif|webp)(?:\?[^\s<]*)?)/gim, '$1<a href="$2" target="_blank" rel="noopener" class="img-link"><img src="$2" alt="图片" loading="lazy"></a>');
  // 普通 URL
  html = html.replace(/(^|[^"\'\]\)>\n])(https?:\/\/[^\s<]+)(?=\s|$|<|\)|\])/gm, '$1<a href="$2" target="_blank" rel="noopener">$2</a>');

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

  return html;
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

  try {
    const url = '/api/chat/stream?m=' + encodeURIComponent(text)
      + (currentAgentId ? '&agent=' + encodeURIComponent(currentAgentId) : '');
    const resp = await fetch(url, { signal: _abortController.signal });

    clearTimeout(timeoutId);

    if (!resp.ok) {
      // 回退 POST
      await fallbackPost(conv, text);
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
          // 首块后切换思考状态
          if (accumulatedReply.length > 50) {
            const thinkFold = document.getElementById('streamingThink');
            if (thinkFold) {
              thinkFold.removeAttribute('open');
              const sum = thinkFold.querySelector('summary');
              if (sum) sum.innerHTML = '<span class="think-dot done"></span> 正在组织回复';
            }
          }
        } else if (d.type === 'done') {
          // SSE 完成
          clearTimeout(dataTimeout);
          clearTimeout(timeoutId);
          finishStreaming(accumulatedReply, conv);
          setAgentStatus(aid, 'done', '');
          document.getElementById('topbarStatus').textContent = '';
          setTimeout(function () { setAgentStatus(aid, 'online', ''); }, 2000);
        } else if (d.type === 'status') {
          const st = document.querySelector('#streamingThinkText');
          if (st && d.data) st.textContent = d.data;
          // 同时更新 Agent status
          setAgentStatus(aid, 'thinking', d.data);
        } else if (d.type === 'error') {
          clearTimeout(dataTimeout);
          showStreamError(d.data || '服务器返回错误');
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

    // 流正常结束但没收到 done 事件
    if (accumulatedReply) {
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
      body: JSON.stringify({ message: text, agent_id: currentAgentId })
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
  if (el) el.innerHTML = renderMarkdown(text);
  const msgs = document.getElementById('msgs');
  msgs.scrollTop = msgs.scrollHeight;
}

function showStreamError(msg) {
  updateStreamingContent('<span style="color:#fb2c36;">' + escapeHtml(msg) + '</span>');
  const bubble = document.getElementById('streamingBubble');
  if (bubble) {
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
