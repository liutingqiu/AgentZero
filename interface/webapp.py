WEBAPP_HTML = r'''<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="theme-color" content="#0d0d0d">
<title>零</title>
<style>
:root{--bg:#0d0d0d;--mid:#1a1a1a;--mid2:#252525;--text:#d4d4d4;--text2:#888;--accent:#4ade80;--accent2:#22c55e;--red:#fb2c36;--amber:#ffbd38;--border:#2a2a2a;--active:#14532d}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,-apple-system,PingFang SC,Microsoft YaHei,sans-serif;background:var(--bg);color:var(--text);height:100vh;display:flex;overflow:hidden;font-size:15px}
/* ── 左侧Agent频道 ── */
.sidebar{width:280px;background:var(--mid);border-right:1px solid var(--border);display:flex;flex-direction:column;flex-shrink:0}
.sidebar-header{padding:14px 16px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between}
.sidebar-header h2{font-size:16px;color:var(--accent);font-weight:600}
.sidebar-header select{background:var(--mid2);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:4px 8px;font-size:12px;outline:none}
.agent-list{flex:1;overflow-y:auto;padding:4px}
.agent-item{display:flex;align-items:center;gap:10px;padding:10px 14px;border-radius:8px;cursor:pointer;transition:all .15s;margin:2px 0}
.agent-item:hover{background:var(--mid2)}
.agent-item.active{background:var(--active)}
.agent-item .dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.agent-item .dot.online{background:var(--accent)}
.agent-item .dot.working{background:var(--amber);animation:pulse 1s infinite}
.agent-item .dot.error{background:var(--red)}
.agent-item .dot.offline{background:var(--text2)}
.agent-item .name{font-size:14px;font-weight:500;flex:1}
.agent-item .status-text{font-size:10px;color:var(--text2)}
@keyframes pulse{50%{opacity:.3}}
.sidebar-footer{padding:8px;border-top:1px solid var(--border)}
.sidebar-footer button{width:100%;padding:8px;border:none;border-radius:8px;background:var(--mid2);color:var(--text);cursor:pointer;font-size:12px;text-align:left}
.sidebar-footer button:hover{background:var(--border)}
/* ── 主对话区 ── */
.main{flex:1;display:flex;flex-direction:column;min-width:0}
.header-bar{padding:10px 16px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:10px;background:var(--mid)}
.header-bar .title{font-size:14px;font-weight:600;color:var(--accent)}
.header-bar .badge{font-size:11px;padding:2px 8px;border-radius:10px;background:var(--amber);color:var(--bg)}
.messages{flex:1;overflow-y:auto;padding:16px}
.msg{max-width:80%;margin-bottom:14px;display:flex;gap:10px}
.msg.user{flex-direction:row-reverse;margin-left:auto}
.msg .avatar{width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:16px;flex-shrink:0;background:var(--mid2)}
.msg .bubble{padding:10px 14px;border-radius:14px;font-size:14px;line-height:1.6;word-break:break-word}
.msg.agent .bubble{background:var(--mid2);border-bottom-left-radius:4px}
.msg.user .bubble{background:var(--active);color:#bbf7d0;border-bottom-right-radius:4px}
.msg .agent-name{font-size:11px;color:var(--accent);margin-bottom:4px;font-weight:600}
.msg .agent-name.thinking{color:var(--amber)}
.msg .time{font-size:10px;color:var(--text2);margin-top:4px}
.msg img{max-width:300px;border-radius:8px;margin-top:8px;cursor:pointer}
.msg pre{background:var(--bg);padding:12px;border-radius:8px;overflow-x:auto;font-size:13px;margin-top:8px}
.thinking-block{font-size:12px;color:var(--amber);padding:8px 12px;background:rgba(255,189,56,.1);border-radius:8px;margin:4px 0;border-left:3px solid var(--amber)}
/* ── 输入区 ── */
.input-box{display:flex;padding:10px 14px;border-top:1px solid var(--border);background:var(--mid);gap:8px}
.input-box textarea{flex:1;padding:10px 14px;border-radius:10px;border:1px solid var(--border);background:var(--bg);color:var(--text);outline:none;resize:none;font:inherit;font-size:14px;max-height:100px;min-height:40px}
.input-box textarea:focus{border-color:var(--accent)}
.input-box button{padding:8px 16px;border:none;border-radius:10px;background:var(--accent);color:var(--bg);cursor:pointer;font-weight:600;font-size:14px}
.input-box button:disabled{opacity:.3}
.at-hint{font-size:11px;color:var(--text2);padding:4px 12px}
.at-dropdown{position:absolute;bottom:100%;left:14px;right:14px;background:var(--mid);border:1px solid var(--accent);border-radius:10px;overflow:hidden;z-index:50;display:none}
.at-dropdown.show{display:block}
.at-dropdown .at-item{padding:10px 14px;cursor:pointer;display:flex;align-items:center;gap:8px;font-size:14px}
.at-dropdown .at-item:hover{background:var(--mid2)}
.at-dropdown .at-item .at-role{font-size:11px;color:var(--text2)}
/* ── 登录 ── */
.login-overlay{position:fixed;inset:0;background:var(--bg);display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:100}
.login-overlay.hidden{display:none}
.login-overlay h1{font-size:48px;margin-bottom:24px;color:var(--accent)}
.login-overlay input{background:var(--mid2);border:1px solid var(--border);color:var(--text);padding:14px 20px;border-radius:12px;font-size:16px;text-align:center;width:240px;outline:none}
.login-overlay input:focus{border-color:var(--accent)}
.login-overlay button{margin-top:12px;background:var(--accent);color:var(--bg);border:none;padding:12px 40px;border-radius:12px;font-size:16px;font-weight:600;cursor:pointer}
.login-overlay .err{color:var(--red);font-size:13px;margin-top:8px}
/* ── 通知 ── */
.notify-toast{position:fixed;top:16px;right:16px;background:var(--mid2);border:1px solid var(--accent);padding:12px 16px;border-radius:10px;z-index:200;animation:slideIn .3s;font-size:14px;max-width:300px}
@keyframes slideIn{from{transform:translateX(100%);opacity:0}to{transform:translateX(0);opacity:1}}
/* ── 移动端 ── */
@media(max-width:768px){.sidebar{display:none}.msg{max-width:95%}}
</style>
</head>
<body>

<div class="login-overlay" id="login">
  <h1>零</h1>
  <input id="code" type="password" placeholder="暗号" autocomplete="off" autofocus>
  <button onclick="unlock()">解锁</button>
  <p class="err" id="err"></p>
</div>

<div class="sidebar" id="sidebar">
  <div class="sidebar-header">
    <h2>Agents</h2>
    <select id="groupBy" onchange="renderAgents()"><option value="agent">按Agent</option><option value="task">按任务</option></select>
  </div>
  <div class="agent-list" id="agentList"></div>
  <div class="sidebar-footer">
    <button onclick="toggleHistory()">📋 历史任务</button>
    <button onclick="toggleSettings()">⚙️ 设置</button>
  </div>
</div>

<div class="main">
  <div class="header-bar">
    <span class="title" id="chatTitle">零 · 总控台</span>
    <span class="badge" id="taskBadge" style="display:none"></span>
  </div>
  <div class="messages" id="msgs"></div>
  <div class="at-hint" id="atHint"></div>
  <div class="input-box" style="position:relative">
    <div class="at-dropdown" id="atDropdown"></div>
    <textarea id="inp" rows="1" placeholder="@Agent 输入需求... Shift+Enter换行" onkeydown="handleKey(event)" oninput="handleAt()"></textarea>
    <button id="sendBtn" onclick="send()">发送</button>
  </div>
</div>

<script>
let token='', currentFilter='', showThinking=true, groupBy='agent';
const AGENTS=[
  {id:'zero',name:'零',icon:'📌',role:'中控',status:'online'},
  {id:'reasonix',name:'Reasonix',icon:'🤖',role:'代码/推理',status:'online'},
  {id:'longxia',name:'龙虾',icon:'🦞',role:'设计/浏览器',status:'online'},
  {id:'agnes',name:'Agnes',icon:'🎨',role:'生图/视频',status:'online'},
  {id:'tavily',name:'Tavily',icon:'🔍',role:'搜索',status:'online'},
];
let messages=[], tasks=[];

function unlock(){
  const code=document.getElementById('code').value.trim();
  if(!code)return;
  fetch('/api/auth',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code})})
  .then(r=>r.json()).then(d=>{
    if(d.ok){token=d.token;document.getElementById('login').classList.add('hidden');renderAgents();addMsg('zero','零已就绪。输入需求，我来调度Agent团队。')}
    else document.getElementById('err').textContent=d.error||'暗号错误'
  });
}

function renderAgents(){
  const container=document.getElementById('agentList');
  container.innerHTML=AGENTS.map(a=>{
    const dotClass=a.status==='working'?'working':a.status==='error'?'error':'online';
    const st=a.status==='working'?'工作中':a.status==='online'?'在线':'';
    return `<div class="agent-item ${currentFilter===a.id?'active':''}" onclick="filterAgent('${a.id}')">
      <span class="dot ${dotClass}"></span><span class="name">${a.icon} ${a.name}</span><span class="status-text">${st}</span></div>`;
  }).join('');
}

function filterAgent(id){
  currentFilter=currentFilter===id?'':id;
  document.getElementById('chatTitle').textContent=currentFilter?AGENTS.find(a=>a.id===currentFilter).name+' · 对话':'零 · 总控台';
  renderAgents();
  renderMessages();
}

function addMsg(agentId,text,isThinking=false){
  messages.push({agent:agentId,text,thinking:isThinking});
  if(!currentFilter||currentFilter===agentId||agentId==='user'){
    renderOneMsg(agentId,text,isThinking);
  }
}
function _addMsgLegacy(agentId,text,isThinking=false){
  const agent=AGENTS.find(a=>a.id===agentId)||{name:agentId,icon:'👤'};
  const div=document.createElement('div');
  div.className='msg '+(agentId==='user'?'user':'agent');
  div.setAttribute('data-agent',agentId);
  
  let inner='';
  if(agentId!=='user'){
    const thinkClass=isThinking?'thinking':'';
    inner+=`<div class="agent-name ${thinkClass}">${agent.icon} ${agent.name}${isThinking?' · 思考中...':''}</div>`;
  }
  
  // 检测图片URL
  const imgMatch=text.match(/(https?:\/\/\S+\.(png|jpg|jpeg|gif|webp))/gi);
  let content=text;
  if(imgMatch){
    imgMatch.forEach(url=>{
      content=content.replace(url,`<img src="${url}" onclick="window.open('${url}')" loading="lazy">`);
    });
  }
  // Markdown 渲染
  // 代码块
  content=content.replace(/```(\w*)\n([\s\S]*?)```/g,(_,lang,code)=>`<pre>${code.trim()}</pre>`);
  // 行内代码
  content=content.replace(/`([^`]+)`/g,'<code>$1</code>');
  // 粗体
  content=content.replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>');
  // 斜体
  content=content.replace(/\*([^*]+)\*/g,'<em>$1</em>');
  // 数学块 $$...$$
  content=content.replace(/\$\$([\s\S]*?)\$\$/g,(_,m)=>`<div style="text-align:center;font-family:monospace;background:var(--bg);padding:12px;border-radius:8px;margin:8px 0">${m.trim()}</div>`);
  // 行内数学 $...$
  content=content.replace(/\$([^$]+)\$/g,(_,m)=>`<code style="background:transparent;font-size:inherit">${m}</code>`);
  // 数字+单位美化
  content=content.replace(/(\d[\d,.]*)\s*(k|K)(?=\s|$|[.,;!?)])/g,'$1,000');
  // 换行
  content=content.replace(/\n/g,'<br>');
  
  inner+=`<div class="bubble">${content}</div>`;
  inner+=`<div class="time">${new Date().toLocaleTimeString()}</div>`;
  
  div.innerHTML=inner;
  document.getElementById('msgs').appendChild(div);
  div.scrollIntoView({behavior:'smooth'});
}

function renderMessages(){
  document.getElementById('msgs').innerHTML='';
  const filtered=messages.filter(m=>!currentFilter||m.agent===currentFilter||m.agent==='user');
  filtered.forEach(m=>{
    renderOneMsg(m.agent,m.text,m.thinking);
  });
}
function renderOneMsg(agentId,text,isThinking){
  const agent=AGENTS.find(a=>a.id===agentId)||{name:agentId,icon:'👤'};
  const div=document.createElement('div');
  div.className='msg '+(agentId==='user'?'user':'agent');
  div.setAttribute('data-agent',agentId);
  let inner='';
  if(agentId!=='user'){
    const thinkClass=isThinking?'thinking':'';
    inner+=`<div class="agent-name ${thinkClass}">${agent.icon} ${agent.name}${isThinking?' · 思考中...':''}</div>`;
  }
  const imgMatch=text.match(/(https?:\/\/\S+\.(png|jpg|jpeg|gif|webp))/gi);
  let content=text;
  if(imgMatch){imgMatch.forEach(url=>{content=content.replace(url,`<img src="${url}" onclick="window.open('${url}')" loading="lazy">`)})}
  content=content.replace(/```(\w*)\n([\s\S]*?)```/g,(_,lang,code)=>`<pre>${code.trim()}</pre>`);
  content=content.replace(/`([^`]+)`/g,'<code>$1</code>');
  content=content.replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>');
  content=content.replace(/\$\$([\s\S]*?)\$\$/g,(_,m)=>`<div style="text-align:center;font-family:monospace;background:var(--bg);padding:12px;border-radius:8px;margin:8px 0">${m.trim()}</div>`);
  content=content.replace(/\$([^$]+)\$/g,(_,m)=>`<code style="background:transparent;font-size:inherit">${m}</code>`);
  content=content.replace(/\n/g,'<br>');
  inner+=`<div class="bubble">${content}</div>`;
  inner+=`<div class="time">${new Date().toLocaleTimeString()}</div>`;
  div.innerHTML=inner;
  document.getElementById('msgs').appendChild(div);
  div.scrollIntoView({behavior:'smooth'});
}

function addThinkBlock(agentId,text){
  const div=document.createElement('div');
  div.className='thinking-block';
  div.setAttribute('data-agent',agentId);
  const agent=AGENTS.find(a=>a.id===agentId);
  div.innerHTML=`${agent?.icon||''} <strong>${agent?.name||agentId}</strong>: ${text}`;
  document.getElementById('msgs').appendChild(div);
  div.scrollIntoView({behavior:'smooth'});
  setTimeout(()=>div.remove(),5000);
}

function handleKey(e){
  if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send()}
}

function handleAt(){
  const inp=document.getElementById('inp');
  const lastAt=inp.value.lastIndexOf('@');
  const dd=document.getElementById('atDropdown');
  if(lastAt>=0){
    const partial=inp.value.substring(lastAt+1).toLowerCase().split(' ')[0];
    const matches=AGENTS.filter(a=>a.id.includes(partial)||a.name.includes(partial));
    if(partial.length===0){dd.innerHTML=AGENTS.map(a=>`<div class="at-item" onclick="selectAt('${a.id}')"><span>${a.icon} ${a.name}</span><span class="at-role">${a.role}</span></div>`).join('');dd.classList.add('show')}
    else if(matches.length){
      dd.innerHTML=matches.map(a=>`<div class="at-item" onclick="selectAt('${a.id}')"><span>${a.icon} ${a.name}</span><span class="at-role">${a.role}</span></div>`).join('');
      dd.classList.add('show');
    }else{dd.classList.remove('show')}
  }else{dd.classList.remove('show')}
}
function selectAt(id){
  const inp=document.getElementById('inp');
  const lastAt=inp.value.lastIndexOf('@');
  inp.value=inp.value.substring(0,lastAt)+'@'+id+' ';
  document.getElementById('atDropdown').classList.remove('show');
  inp.focus();
}

async function send(){
  const inp=document.getElementById('inp'),text=inp.value.trim();
  if(!text)return;
  
  // 检测@Agent
  const atMatch=text.match(/@(\w+)/);
  const targetAgent=atMatch?AGENTS.find(a=>a.id===atMatch[1]):null;
  
  // 用户消息
  messages.push({agent:'user',text});
  addMsg('user',text);
  inp.value='';inp.style.height='auto';
  document.getElementById('sendBtn').disabled=true;
  
  // 任务开始
  if(!targetAgent||targetAgent.id==='zero'){
    // 中控模式
    setAgentStatus('zero','working');
    addMsg('zero','收到，正在分析...',true);
    
    setTimeout(()=>{
      addMsg('zero','已拆解为子任务，分配中...');
      // 模拟Agent工作
      const assigned=[];
      if(text.includes('图')||text.includes('画'))assigned.push('agnes');
      if(text.includes('做')||text.includes('网站')||text.includes('写')){assigned.push('reasonix');assigned.push('longxia')}
      if(text.includes('搜')||text.includes('查'))assigned.push('tavily');
      if(!assigned.length)assigned.push('reasonix');
      
      assigned.forEach(aid=>{
        setAgentStatus(aid,'working');
        addThinkBlock(aid,'任务已分配，开始工作...');
      });
    },800);
    
    // 调用后端
    try{
      const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:text,token})});
      const d=await r.json();
      const reply=d.reply||'完成';
      const agent=d.agent||'zero';
      
      addMsg(agent,reply);
      AGENTS.forEach(a=>setAgentStatus(a.id,'online'));
      setAgentStatus('zero','online');
      
      // 通知
      if(document.hidden)notify('零','任务完成');
    }catch(e){
      addMsg('zero','通信错误: '+e.message);
      setAgentStatus('zero','error');
    }
  }else{
    // 直接@Agent
    setAgentStatus(targetAgent.id,'working');
    addMsg(targetAgent.id,'收到 @'+targetAgent.name+'，处理中...',true);
    
    try{
      const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:text,token})});
      const d=await r.json();
      const agent=d.agent||targetAgent.id;
      addMsg(agent,d.reply||'完成');
      setAgentStatus(targetAgent.id,'online');
    }catch(e){
      addMsg(targetAgent.id,'错误: '+e.message);
      setAgentStatus(targetAgent.id,'error');
    }
  }
  
  document.getElementById('sendBtn').disabled=false;
  inp.focus();
  // 更新任务计数
  tasks.push({time:new Date(),text:text.substring(0,50)});
}

function setAgentStatus(id,status){
  const agent=AGENTS.find(a=>a.id===id);
  if(agent)agent.status=status;
  renderAgents();
}

function notify(title,body){
  const toast=document.createElement('div');
  toast.className='notify-toast';
  toast.innerHTML=`<strong>${title}</strong><br>${body}`;
  document.body.appendChild(toast);
  setTimeout(()=>toast.remove(),4000);
  // 标题闪烁
  let count=0,orig=document.title;
  const flash=setInterval(()=>{document.title=count%2?'🔔 任务完成':orig;count++;if(count>6){clearInterval(flash);document.title=orig}},500);
}

function toggleHistory(){
  const html=tasks.length?tasks.map((t,i)=>`<div style="padding:8px;cursor:pointer;border-bottom:1px solid var(--border)" onclick="alert('任务${i+1}: ${t.text}')">📋 ${t.time.toLocaleTimeString()} ${t.text}</div>`).join(''):'暂无历史';
  const div=document.createElement('div');
  div.style='position:fixed;top:10%;left:50%;transform:translateX(-50%);background:var(--mid);border:1px solid var(--border);border-radius:12px;padding:16px;z-index:150;max-height:70%;overflow-y:auto;min-width:300px';
  div.innerHTML='<h3 style="margin-bottom:8px">📋 历史任务 ('+tasks.length+')</h3>'+html+'<button onclick="this.parentElement.remove()" style="margin-top:8px;background:var(--border);color:var(--text);border:none;padding:6px 12px;border-radius:6px;cursor:pointer">关闭</button>';
  document.body.appendChild(div);
}

function toggleSettings(){
  const div=document.createElement('div');
  div.style='position:fixed;top:10%;left:50%;transform:translateX(-50%);background:var(--mid);border:1px solid var(--border);border-radius:12px;padding:16px;z-index:150;min-width:280px';
  div.innerHTML=`
    <h3 style="margin-bottom:12px">⚙️ 设置</h3>
    <label style="display:flex;align-items:center;gap:8px;margin-bottom:8px;cursor:pointer">
      <input type="checkbox" ${showThinking?'checked':''} onchange="showThinking=this.checked"> 显示Agent思考过程
    </label>
    <label style="display:flex;align-items:center;gap:8px;margin-bottom:8px;cursor:pointer">
      <input type="checkbox" checked onchange="toggleSound(this.checked)"> 任务完成提示音
    </label>
    <button onclick="this.parentElement.remove()" style="margin-top:8px;background:var(--border);color:var(--text);border:none;padding:6px 12px;border-radius:6px;cursor:pointer">关闭</button>
  `;
  document.body.appendChild(div);
}

function toggleSound(on){window._soundOn=on}

// 自动检测会话
fetch('/health').then(r=>r.json()).then(d=>{
  if(d.session&&d.session.includes('已解锁')){token='unlocked';document.getElementById('login').classList.add('hidden');renderAgents();addMsg('zero','零已就绪。')}
});
</script>
</body>
</html>'''
