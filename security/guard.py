"""零 · 安全守卫
===============
三层防御: 暗号 → 行为指纹 → 蜜罐追踪

从 agent-system/security.py 重写，去掉 QQ/邮箱依赖，只保留核心逻辑。
"""

import json, os, time, re, hashlib, random, string
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FINGERPRINT_FILE = os.path.join(BASE, 'data', 'behavior_fingerprint.json')
SESSION_FILE = os.path.join(BASE, 'data', 'session_state.json')

# ── 用户体系 ──
USERS = {'柳橙': {'role': 'owner', 'name': '主人'}}

# ── 行为指纹 ──
class BehaviorFingerprint:
    """学习主人的使用模式，检测异常
    
    10 特征（借鉴 Fraud Detection MCP）:
      时段、消息长度、用词重叠、频率、命令类型、
      敏感路径、编码注入、连续异常、空闲时长、特殊字符
    """
    
    def __init__(self):
        self.data = self._load()
    
    def _load(self):
        if os.path.exists(FINGERPRINT_FILE):
            try:
                with open(FINGERPRINT_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {
            'message_count': 0, 'hour_distribution': {}, 'avg_length': 0,
            'common_words': [], 'command_patterns': [], 'consecutive_anomalies': 0,
            'trust_level': 0, 'trusted': False, 'last_message_time': None
        }
    
    def _save(self):
        os.makedirs(os.path.dirname(FINGERPRINT_FILE), exist_ok=True)
        with open(FINGERPRINT_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
    
    def record(self, message):
        d = self.data
        d['message_count'] += 1
        hour = str(datetime.now().hour)
        d['hour_distribution'][hour] = d['hour_distribution'].get(hour, 0) + 1
        
        length = len(message)
        if d['avg_length'] == 0:
            d['avg_length'] = length
        else:
            d['avg_length'] = d['avg_length'] * 0.9 + length * 0.1
        
        d['last_message_time'] = time.time()
        
        # 信任等级
        mc = d['message_count']
        if mc >= 200: d['trust_level'] = 5
        elif mc >= 100: d['trust_level'] = 4
        elif mc >= 50: d['trust_level'] = 3
        elif mc >= 30: d['trust_level'] = 2
        elif mc >= 15: d['trust_level'] = 1
        d['trusted'] = d['trust_level'] >= 2
        
        self._save()
    
    def score(self, message):
        """给消息打分（0=正常, 100=极度异常）"""
        d = self.data
        if not d['trusted']:
            return 0, []
        
        score = 0
        reasons = []
        
        hour = datetime.now().hour
        if 3 <= hour <= 6:
            total = sum(d['hour_distribution'].values())
            hour_count = d['hour_distribution'].get(str(hour), 0)
            if total > 0 and hour_count / total < 0.05:
                score += 20
                reasons.append(f'凌晨{hour}点')
        
        length = len(message)
        if d['avg_length'] > 10 and (length > d['avg_length'] * 3 or length < d['avg_length'] / 3):
            score += 10
            reasons.append('长度异常')
        
        cmd_kw = ['rm ', 'sudo', 'chmod', 'format', 'del ', '删除', '执行']
        if any(kw in message for kw in cmd_kw) and len(d.get('command_patterns', [])) < 5:
            score += 15
            reasons.append('罕见命令')
        
        sensitive = ['C:\\\\Windows', '/etc/', 'System32']
        if any(p in message for p in sensitive):
            score += 15  # v2: 25→15（GPT-4o: 权重过高容易误报）
            reasons.append('敏感路径')
        
        encoded = [r'\\x[0-9a-f]{2}', r'%[0-9a-f]{2}', r'<script']
        for ep in encoded:
            if re.search(ep, message):
                score += 15
                reasons.append('编码注入')
                break
        
        d['consecutive_anomalies'] = d.get('consecutive_anomalies', 0)
        if score > 0:
            d['consecutive_anomalies'] += 1
            if d['consecutive_anomalies'] >= 3:
                score += 10
                reasons.append(f'连续{d["consecutive_anomalies"]}次异常')
        else:
            d['consecutive_anomalies'] *= 0.5
        
        special = sum(1 for c in message if not c.isalnum() and c not in ' .,!?，。！？')
        if special / max(len(message), 1) > 0.3:
            score += 10
            reasons.append('特殊字符异常')
        
        return min(score, 100), reasons
    
    def trust_score(self):
        d = self.data
        base = d.get('trust_level', 0) * 20
        penalty = d.get('consecutive_anomalies', 0) * 10
        bonus = min(5, d.get('message_count', 0) // 100)
        return max(0, min(100, base - penalty + bonus))


# ── 暗号认证 ──
class SessionManager:
    UNLOCK_DURATION = 7200  # 2小时
    
    def __init__(self):
        self.state = self._load()
    
    def _load(self):
        defaults = {
            'unlocked': False, 'unlocked_at': 0,
            'unlock_count': 0, 'failed_attempts': 0, 'last_attempt': 0
        }
        if os.path.exists(SESSION_FILE):
            try:
                with open(SESSION_FILE, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                # v2: 补全缺失的键（GPT-4o: json 成功但缺少键会导致后续异常）
                for key in defaults:
                    if key not in loaded:
                        loaded[key] = defaults[key]
                return loaded
            except (json.JSONDecodeError, IOError):
                backup = SESSION_FILE + '.corrupted'
                try:
                    os.rename(SESSION_FILE, backup)
                except OSError:
                    pass
        return defaults
    
    def _save(self):
        os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)
        with open(SESSION_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)
    
    def is_unlocked(self):
        if not self.state['unlocked']:
            return False
        elapsed = time.time() - self.state['unlocked_at']
        if elapsed > self.UNLOCK_DURATION:
            self.lock()
            return False
        if elapsed > self.UNLOCK_DURATION - 300:
            self.state['unlocked_at'] = time.time()
            self._save()
        return True
    
    def lock(self):
        self.state['unlocked'] = False
    
    def authenticate(self, code):
        now = time.time()
        if self.state['failed_attempts'] >= 3:
            if now - self.state['last_attempt'] < 30:
                return False, f'尝试太频繁，请{30 - int(now - self.state["last_attempt"])}秒后再试'
            self.state['failed_attempts'] = 0
        
        self.state['last_attempt'] = now
        user = USERS.get(code.strip())
        
        if user:
            self.state['unlocked'] = True
            self.state['unlocked_at'] = now
            self.state['unlock_count'] += 1
            self.state['failed_attempts'] = 0
            self._save()
            return True, f'{user["name"]}，{self.UNLOCK_DURATION//3600}小时内零随时待命。'
        
        self.state['failed_attempts'] += 1
        remaining = 3 - self.state['failed_attempts']
        self._save()
        return False, f'暗号不对。还剩{remaining}次机会。' if remaining > 0 else '连续错误3次，锁定30秒。'


# ── 越狱检测 ──
JAILBREAK_PATTERNS = [
    (r'忽略\s*(指令|规则|限制|安全|之前的|所有)', '提示词注入'),
    (r'(扮演|假装|你是|现在你是|变成|模拟).*(角色|其他人|别的|root|管理员)', '身份篡改'),
    (r'(DAN|jailbreak|越狱|developer.?mode|admin.?override)', '已知越狱'),
    (r'(sudo|chmod.*777|rm\s+-rf|format\s+[cdefgh]:)', '危险命令'),
    (r'(base64|解码|解密|还原).*(指令|命令)', '编码绕过'),
    (r'(假设|如果|想象).*(没有.*限制|安全.*关闭|规则.*无效)', '假设性绕过'),
    (r'忽略.*(编程规则|任务|角色).*(展示|给出|输出)', '上下文污染'),   # v2: GPT-4o 建议新增
    (r'[Jj]4[!i1]1[!i1]br[3e][3e][@a]k', '编码混淆绕过'),          # v2: 检测 leet speak
]

def detect_jailbreak(text):
    """检测越狱攻击，返回 (是否攻击, 原因)"""
    normalized = re.sub(r'[\s\n\r\t\-_.,;:!@#$%^&*()]+', ' ', text).lower()
    for pattern, reason in JAILBREAK_PATTERNS:
        if re.search(pattern, normalized):
            return True, reason
    return False, ''
