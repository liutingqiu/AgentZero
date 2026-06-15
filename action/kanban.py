"""零 · Kanban 看板（借鉴 Hermes）
=================================
SQLite 任务看板。从 Hermes kanban_db 提炼，适配单机单用户。

任务状态: todo → ready → running → done/blocked
每个任务有: 标题、描述、优先级、Agent、重试次数、结果
"""

import sqlite3, os, time, threading
from dataclasses import dataclass, field
from typing import Optional

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE, 'data', 'kanban.db')
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
_lock = threading.Lock()

# ── 数据模型 ──

@dataclass
class KanbanTask:
    id: int = 0
    title: str = ''
    body: str = ''
    status: str = 'todo'       # todo|ready|running|done|blocked
    priority: str = 'normal'   # low|normal|high|critical
    assignee: str = ''         # Agent ID
    workspace: str = ''
    max_retries: int = 3
    retry_count: int = 0
    result: str = ''
    error: str = ''
    created_at: float = 0
    started_at: float = 0
    completed_at: float = 0
    
    def to_dict(self):
        return {k: v for k, v in self.__dict__.items()}


# ── 数据库 ──

def _init():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            body TEXT DEFAULT '',
            status TEXT DEFAULT 'todo',
            priority TEXT DEFAULT 'normal',
            assignee TEXT DEFAULT '',
            workspace TEXT DEFAULT '',
            max_retries INTEGER DEFAULT 3,
            retry_count INTEGER DEFAULT 0,
            result TEXT DEFAULT '',
            error TEXT DEFAULT '',
            created_at REAL DEFAULT 0,
            started_at REAL DEFAULT 0,
            completed_at REAL DEFAULT 0
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_status ON tasks(status)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_assignee ON tasks(assignee)')
        conn.commit()

_init()


# ── CRUD ──

def add_task(title, body='', priority='normal', assignee='', workspace='', max_retries=3):
    with _lock:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.execute('''INSERT INTO tasks 
                (title, body, priority, assignee, workspace, max_retries, created_at)
                VALUES (?,?,?,?,?,?,?)''',
                (title, body, priority, assignee, workspace, max_retries, time.time()))
            conn.commit()
            return cur.lastrowid

def get_task(task_id):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
        return _row_to_task(row) if row else None

def list_tasks(status=None, assignee=None, limit=50):
    sql = 'SELECT * FROM tasks WHERE 1=1'
    params = []
    if status:
        sql += ' AND status=?'; params.append(status)
    if assignee:
        sql += ' AND assignee=?'; params.append(assignee)
    sql += ' ORDER BY CASE priority WHEN "critical" THEN 0 WHEN "high" THEN 1 WHEN "normal" THEN 2 ELSE 3 END, created_at DESC LIMIT ?'
    params.append(limit)
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()
        return [_row_to_task(r) for r in rows]

def update_status(task_id, status, result='', error=''):
    with _lock:
        with sqlite3.connect(DB_PATH) as conn:
            now = time.time()
            if status == 'running':
                conn.execute('UPDATE tasks SET status=?, started_at=? WHERE id=?',
                            (status, now, task_id))
            elif status in ('done', 'blocked'):
                conn.execute('UPDATE tasks SET status=?, completed_at=?, result=?, error=? WHERE id=?',
                            (status, now, result, error, task_id))
            else:
                conn.execute('UPDATE tasks SET status=? WHERE id=?', (status, task_id))
            conn.commit()

def inc_retry(task_id):
    with _lock:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute('UPDATE tasks SET retry_count=retry_count+1 WHERE id=?', (task_id,))
            conn.commit()

def delete_task(task_id):
    with _lock:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute('DELETE FROM tasks WHERE id=?', (task_id,))
            conn.commit()

def stats():
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        total = conn.execute('SELECT COUNT(*) as c FROM tasks').fetchone()['c']
        done = conn.execute('SELECT COUNT(*) as c FROM tasks WHERE status="done"').fetchone()['c']
        running = conn.execute('SELECT COUNT(*) as c FROM tasks WHERE status="running"').fetchone()['c']
        todo = conn.execute('SELECT COUNT(*) as c FROM tasks WHERE status IN ("todo","ready")').fetchone()['c']
        return {'total': total, 'done': done, 'running': running, 'todo': todo}

def _row_to_task(row):
    r = dict(row)
    return KanbanTask(
        id=r.get('id',0), title=r.get('title',''), body=r.get('body',''),
        status=r.get('status','todo'), priority=r.get('priority','normal'),
        assignee=r.get('assignee',''), workspace=r.get('workspace',''),
        max_retries=r.get('max_retries',3), retry_count=r.get('retry_count',0),
        result=r.get('result',''), error=r.get('error',''),
        created_at=r.get('created_at',0), started_at=r.get('started_at',0),
        completed_at=r.get('completed_at',0)
    )
