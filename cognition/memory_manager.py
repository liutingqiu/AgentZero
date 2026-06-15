"""零 · 短期记忆
================
SQLite + FTS5 全文搜索。存储 24h~7 天的数据。

从 agent-system/memory_manager.py 重写。
"""

import sqlite3, json, os, threading
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE, 'data', 'memory.sqlite')
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

_lock = threading.Lock()


def _init_db():
    with sqlite3.connect(DB_PATH) as conn:
        # 任务记录
        conn.execute('''CREATE TABLE IF NOT EXISTS task_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT UNIQUE, agent TEXT, task_type TEXT,
            input_summary TEXT, outcome TEXT, error_info TEXT,
            duration_ms REAL, tokens_used INTEGER,
            timestamp TEXT, project_tag TEXT, reflection TEXT
        )''')
        
        # 对话摘要
        conn.execute('''CREATE TABLE IF NOT EXISTS conversation_summary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT, topic TEXT, summary TEXT,
            emotion TEXT, importance INTEGER DEFAULT 3,
            messages_count INTEGER DEFAULT 0,
            timestamp TEXT
        )''')
        
        # 今日状态（每天一条）
        conn.execute('''CREATE TABLE IF NOT EXISTS daily_state (
            date TEXT PRIMARY KEY,
            active_project TEXT, files_modified INTEGER,
            messages_count INTEGER, tasks_completed INTEGER,
            mood TEXT, updated_at TEXT
        )''')
        
        # FTS5 全文搜索
        conn.execute('''CREATE VIRTUAL TABLE IF NOT EXISTS task_fts USING fts5(
            task_id, agent, task_type, input_summary, error_info, reflection,
            content='task_memory', content_rowid='id'
        )''')
        
        conn.commit()
    
    # FTS5 同步触发器
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript('''
            CREATE TRIGGER IF NOT EXISTS task_fts_insert AFTER INSERT ON task_memory BEGIN
                INSERT INTO task_fts(rowid, task_id, agent, task_type, input_summary, error_info, reflection)
                VALUES (new.id, new.task_id, new.agent, new.task_type, new.input_summary, new.error_info, new.reflection);
            END;
            CREATE TRIGGER IF NOT EXISTS task_fts_delete AFTER DELETE ON task_memory BEGIN
                INSERT INTO task_fts(task_fts, rowid, task_id, agent, task_type, input_summary, error_info, reflection)
                VALUES ('delete', old.id, old.task_id, old.agent, old.task_type, old.input_summary, old.error_info, old.reflection);
            END;
            CREATE TRIGGER IF NOT EXISTS task_fts_update AFTER UPDATE ON task_memory BEGIN
                INSERT INTO task_fts(task_fts, rowid, task_id, agent, task_type, input_summary, error_info, reflection)
                VALUES ('delete', old.id, old.task_id, old.agent, old.task_type, old.input_summary, old.error_info, old.reflection);
                INSERT INTO task_fts(rowid, task_id, agent, task_type, input_summary, error_info, reflection)
                VALUES (new.id, new.task_id, new.agent, new.task_type, new.input_summary, new.error_info, new.reflection);
            END;
        ''')
        conn.commit()

_init_db()


# ═══════════════════════════════════════════
# 任务记忆
# ═══════════════════════════════════════════

def save_task(task_id, agent, task_type, input_summary, outcome,
              error_info='', duration_ms=0, tokens_used=0, project_tag=''):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        with _lock:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute('''INSERT OR REPLACE INTO task_memory
                    (task_id, agent, task_type, input_summary, outcome,
                     error_info, duration_ms, tokens_used, timestamp, project_tag)
                    VALUES (?,?,?,?,?,?,?,?,?,?)''',
                    (task_id, agent, task_type, input_summary, outcome,
                     error_info, duration_ms, tokens_used, ts, project_tag))
                conn.commit()
        return True
    except Exception as e:
        print(f'[memory] 写入失败: {e}')
        return False


def query_tasks(agent=None, outcome=None, days=7, limit=20):
    sql = 'SELECT * FROM task_memory WHERE 1=1'
    params = []
    if agent:
        sql += ' AND agent=?'; params.append(agent)
    if outcome:
        sql += ' AND outcome=?'; params.append(outcome)
    if days:
        sql += f' AND timestamp >= datetime("now", "-{days} days")'
    sql += ' ORDER BY timestamp DESC LIMIT ?'; params.append(limit)
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
    except Exception as e:
        print(f'[memory] 查询失败: {e}')
        return []


def search_memory(query, limit=10):
    """FTS5 全文搜索，降级为 LIKE"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    'SELECT * FROM task_fts WHERE task_fts MATCH ? ORDER BY rank LIMIT ?',
                    (query, limit)).fetchall()
            except:
                like_q = f'%{query}%'
                rows = conn.execute(
                    'SELECT * FROM task_memory WHERE input_summary LIKE ? OR error_info LIKE ? ORDER BY timestamp DESC LIMIT ?',
                    (like_q, like_q, limit)).fetchall()
            return [dict(r) for r in rows]
    except:
        return []


def stats_recent(hours=24):
    """最近 N 小时统计"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            total = conn.execute(
                'SELECT COUNT(*) as c FROM task_memory WHERE timestamp >= datetime("now", ? || " hours")',
                (str(-hours),)).fetchone()['c']
            success = conn.execute(
                'SELECT COUNT(*) as c FROM task_memory WHERE outcome="success" AND timestamp >= datetime("now", ? || " hours")',
                (str(-hours),)).fetchone()['c']
            by_agent = conn.execute(
                'SELECT agent, COUNT(*) as cnt FROM task_memory WHERE timestamp >= datetime("now", ? || " hours") GROUP BY agent',
                (str(-hours),)).fetchall()
            return {
                'total': total,
                'success': success,
                'failure': total - success,
                'rate': round(success/total*100, 1) if total else 0,
                'by_agent': [dict(r) for r in by_agent]
            }
    except:
        return {'total': 0, 'success': 0, 'failure': 0, 'rate': 0, 'by_agent': []}


# ═══════════════════════════════════════════
# 对话摘要
# ═══════════════════════════════════════════

def save_conversation_summary(topic, summary, emotion='neutral', messages_count=0):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    date = datetime.now().strftime('%Y-%m-%d')
    try:
        with _lock:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute('''INSERT INTO conversation_summary
                    (date, topic, summary, emotion, messages_count, timestamp)
                    VALUES (?,?,?,?,?,?)''',
                    (date, topic, summary, emotion, messages_count, ts))
                conn.commit()
        return True
    except:
        return False


def get_conversation_summaries(days=7, limit=20):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                'SELECT * FROM conversation_summary WHERE date >= date("now", ? || " days") ORDER BY timestamp DESC LIMIT ?',
                (str(-days), limit)).fetchall()
            return [dict(r) for r in rows]
    except:
        return []


# ═══════════════════════════════════════════
# 今日状态
# ═══════════════════════════════════════════

def save_daily_state(active_project, files_modified=0, messages_count=0,
                     tasks_completed=0, mood='normal'):
    date = datetime.now().strftime('%Y-%m-%d')
    ts = datetime.now().isoformat()
    try:
        with _lock:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute('''INSERT OR REPLACE INTO daily_state
                    (date, active_project, files_modified, messages_count,
                     tasks_completed, mood, updated_at)
                    VALUES (?,?,?,?,?,?,?)''',
                    (date, active_project, files_modified, messages_count,
                     tasks_completed, mood, ts))
                conn.commit()
        return True
    except:
        return False


def get_today_state():
    date = datetime.now().strftime('%Y-%m-%d')
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute('SELECT * FROM daily_state WHERE date=?', (date,)).fetchone()
            return dict(row) if row else None
    except:
        return None


# ═══════════════════════════════════════════
# 记忆压缩
# ═══════════════════════════════════════════

def compress_memory(days=30):
    """压缩 30 天前的记忆：截短摘要、清空错误信息"""
    try:
        with _lock:
            with sqlite3.connect(DB_PATH) as conn:
                result = conn.execute(
                    'UPDATE task_memory SET input_summary=substr(input_summary,1,60), error_info="" WHERE timestamp < datetime("now", ? || " days")',
                    (str(-days),))
                conn.commit()
                return {'compressed': result.rowcount}
    except Exception as e:
        return {'error': str(e)}
