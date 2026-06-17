"""零 · 短期记忆（SQLite）

修复要点：
  - 启用 WAL 模式，支持并发读写
  - 显式事务管理，避免 autocommit 下频繁 fsync
  - FTS5 用 content=task_memory 外部表 + 触发器，保持全文索引与主表同步
  - 写记忆时统一异常处理，不再裸 except pass
"""

import os
import sqlite3
import threading
from datetime import datetime

from config import MEMORY_DB, get_logger

logger = get_logger('zero.memory')

_DB_LOCK = threading.Lock()


def _connect():
    """获取连接。每次创建新连接（SQLite 连接不是线程安全的）。"""
    conn = sqlite3.connect(MEMORY_DB, timeout=15, isolation_level=None)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=3000')
    conn.row_factory = sqlite3.Row
    return conn


def _init_db():
    """初始化表结构（幂等）。"""
    os.makedirs(os.path.dirname(MEMORY_DB), exist_ok=True)
    with _connect() as conn:
        # 先删旧触发器（避免 schema 变更后残留引用不存在的列）
        for trig in ('task_memory_ai', 'task_memory_au', 'task_memory_ad'):
            conn.execute(f'DROP TRIGGER IF EXISTS {trig}')
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS task_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT UNIQUE,
            agent TEXT,
            task_type TEXT,
            input_summary TEXT,
            outcome TEXT,
            tokens_used INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS task_fts USING fts5(
            task_id, input_summary, outcome,
            content='task_memory', content_rowid='id'
        );

        CREATE TRIGGER IF NOT EXISTS task_memory_ai AFTER INSERT ON task_memory
        BEGIN
            INSERT INTO task_fts(rowid, task_id, input_summary, outcome)
            VALUES (new.id, new.task_id, new.input_summary, new.outcome);
        END;

        CREATE TRIGGER IF NOT EXISTS task_memory_au AFTER UPDATE ON task_memory
        BEGIN
            INSERT INTO task_fts(task_fts, rowid, task_id, input_summary, outcome)
            VALUES ('delete', old.id, old.task_id, old.input_summary, old.outcome);
            INSERT INTO task_fts(rowid, task_id, input_summary, outcome)
            VALUES (new.id, new.task_id, new.input_summary, new.outcome);
        END;

        CREATE TRIGGER IF NOT EXISTS task_memory_ad AFTER DELETE ON task_memory
        BEGIN
            INSERT INTO task_fts(task_fts, rowid, task_id, input_summary, outcome)
            VALUES ('delete', old.id, old.task_id, old.input_summary, old.outcome);
        END;

        CREATE INDEX IF NOT EXISTS idx_task_memory_agent
            ON task_memory(agent, created_at);
        CREATE INDEX IF NOT EXISTS idx_task_memory_outcome
            ON task_memory(outcome, created_at);
        ''')
        logger.debug('memory DB initialized (%s)', MEMORY_DB)


def _migrate():
    """自动迁移旧 schema：补建缺失的列。FTS5 表有 schema 变更则重建。"""
    try:
        with _connect() as conn:
            cols = {r[1] for r in conn.execute(
                'PRAGMA table_info(task_memory)',
            ).fetchall()}
            if 'created_at' not in cols:
                conn.execute(
                    "ALTER TABLE task_memory ADD COLUMN created_at TEXT"
                )
                logger.info('migrated: added created_at to task_memory')
            if 'updated_at' not in cols:
                conn.execute(
                    "ALTER TABLE task_memory ADD COLUMN updated_at TEXT"
                )
                logger.info('migrated: added updated_at to task_memory')

            # FTS5: 如果缺 outcome 列则重建（FTS5 不支持 ALTER）
            try:
                fts_cols = {r[1] for r in conn.execute(
                    'PRAGMA table_info(task_fts)',
                ).fetchall()}
            except sqlite3.Error:
                fts_cols = set()
            if 'outcome' not in fts_cols:
                conn.execute('DROP TABLE IF EXISTS task_fts')
                conn.execute('''
                    CREATE VIRTUAL TABLE task_fts USING fts5(
                        task_id, input_summary, outcome,
                        content='task_memory', content_rowid='id'
                    )
                ''')
                # 重建数据
                conn.execute('''
                    INSERT INTO task_fts(rowid, task_id, input_summary, outcome)
                    SELECT id, task_id, input_summary, outcome FROM task_memory
                ''')
                logger.info('migrated: rebuilt task_fts with outcome column')
    except sqlite3.Error as exc:
        logger.warning('migration warning: %s', exc)


# 启动时初始化一次（多线程安全）
# 顺序：先迁移旧表（补列），再初始化（建表/索引）
with _DB_LOCK:
    if os.path.exists(MEMORY_DB):
        _migrate()
    _init_db()


# ── 写操作 ───────────────────────────────────────────────────────────
def save_task(task_id, agent, task_type, input_summary, outcome,
              tokens_used=0):
    """保存/更新任务。显式事务。"""
    with _DB_LOCK:
        try:
            with _connect() as conn:
                conn.execute('BEGIN')
                now = datetime.now().isoformat(timespec='seconds')
                cursor = conn.execute(
                    'SELECT id FROM task_memory WHERE task_id = ?', (task_id,),
                )
                if cursor.fetchone():
                    conn.execute(
                        '''UPDATE task_memory SET agent=?, task_type=?,
                           input_summary=?, outcome=?, tokens_used=?,
                           updated_at=? WHERE task_id=?''',
                        (agent, task_type, input_summary, outcome,
                         tokens_used, now, task_id),
                    )
                else:
                    conn.execute(
                        '''INSERT INTO task_memory(task_id, agent, task_type,
                           input_summary, outcome, tokens_used, created_at)
                           VALUES(?,?,?,?,?,?,?)''',
                        (task_id, agent, task_type, input_summary, outcome,
                         tokens_used, now),
                    )
                conn.execute('COMMIT')
        except sqlite3.Error as exc:
            logger.warning('save_task failed: %s', exc)
            return False
    return True


def search_tasks(keyword, limit=20):
    """全文搜索最近任务。"""
    try:
        with _connect() as conn:
            rows = conn.execute(
                '''SELECT t.task_id, t.agent, t.task_type, t.input_summary,
                      t.outcome, t.created_at
                 FROM task_memory t
                 JOIN task_fts f ON f.rowid = t.id
                 WHERE task_fts MATCH ?
                 ORDER BY t.created_at DESC LIMIT ?''',
                (keyword, limit),
            ).fetchall()
            return [dict(r) for r in rows]
    except sqlite3.Error as exc:
        logger.warning('search_tasks failed: %s', exc)
        return []


def get_recent_tasks(hours=24, limit=50):
    """最近 N 小时任务列表。"""
    try:
        with _connect() as conn:
            rows = conn.execute(
                '''SELECT task_id, agent, task_type, input_summary,
                      outcome, created_at
                 FROM task_memory
                 WHERE created_at >= datetime('now', ?)
                 ORDER BY created_at DESC LIMIT ?''',
                (f'-{hours} hours', limit),
            ).fetchall()
            return [dict(r) for r in rows]
    except sqlite3.Error as exc:
        logger.warning('get_recent_tasks failed: %s', exc)
        return []


def summary():
    """返回任务汇总统计。"""
    try:
        with _connect() as conn:
            total = conn.execute(
                'SELECT COUNT(*) AS c FROM task_memory',
            ).fetchone()['c']
            success = conn.execute(
                "SELECT COUNT(*) AS c FROM task_memory WHERE outcome='success'",
            ).fetchone()['c']
            failed = conn.execute(
                "SELECT COUNT(*) AS c FROM task_memory WHERE outcome='failed'",
            ).fetchone()['c']
            by_agent = conn.execute(
                '''SELECT agent, COUNT(*) AS c FROM task_memory
                   GROUP BY agent ORDER BY c DESC LIMIT 10''',
            ).fetchall()
        return {
            'total': total,
            'success': success,
            'failed': failed,
            'by_agent': [dict(r) for r in by_agent],
        }
    except sqlite3.Error as exc:
        logger.warning('summary query failed: %s', exc)
        return {'total': 0, 'success': 0, 'failed': 0, 'by_agent': []}


# ── 对话摘要（历史消息归档） ─────────────────────────────────────
def save_conversation_summary(topic, summary, emotion='normal',
                              messages_count=0):
    try:
        with _connect() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS conversation_summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT,
                    summary TEXT,
                    emotion TEXT,
                    messages_count INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.execute(
                '''INSERT INTO conversation_summaries(topic, summary,
                   emotion, messages_count) VALUES(?,?,?,?)''',
                (topic, summary, emotion, messages_count),
            )
        return True
    except sqlite3.Error as exc:
        logger.warning('save_conversation_summary failed: %s', exc)
        return False


def save_persistent_memory(topic: str, content: str, tags: str = ''):
    """写入持久化记忆（跨会话保留）。
    
    topic 用于检索，content 是完整内容，tags 用于分类。
    """
    try:
        with _connect() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS persistent_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT UNIQUE,
                    content TEXT,
                    tags TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            now = datetime.now().isoformat(timespec='seconds')
            conn.execute('''
                INSERT INTO persistent_memory(topic, content, tags, updated_at)
                VALUES(?,?,?,?)
                ON CONFLICT(topic) DO UPDATE SET
                    content=excluded.content,
                    tags=excluded.tags,
                    updated_at=excluded.updated_at
            ''', (topic, content, tags, now))
        return True
    except sqlite3.Error as exc:
        logger.warning('save_persistent_memory failed: %s', exc)
        return False


def get_persistent_memory(topic: str) -> str | None:
    """读取持久化记忆。返回 content 或 None。"""
    try:
        with _connect() as conn:
            row = conn.execute(
                'SELECT content FROM persistent_memory WHERE topic = ?',
                (topic,),
            ).fetchone()
            return row['content'] if row else None
    except sqlite3.Error as exc:
        logger.warning('get_persistent_memory failed: %s', exc)
        return None


def list_persistent_memories(limit=20) -> list:
    """列出所有持久化记忆主题。"""
    try:
        with _connect() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS persistent_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT UNIQUE,
                    content TEXT,
                    tags TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            rows = conn.execute(
                'SELECT topic, tags, updated_at FROM persistent_memory ORDER BY updated_at DESC LIMIT ?',
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
    except sqlite3.Error as exc:
        logger.warning('list_persistent_memories failed: %s', exc)
        return []


def get_conversation_summaries(days=7, limit=50):
    try:
        with _connect() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS conversation_summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT, summary TEXT, emotion TEXT,
                    messages_count INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            rows = conn.execute(
                '''SELECT topic, summary, emotion, messages_count, created_at
                   FROM conversation_summaries
                   WHERE created_at >= datetime('now', ?)
                   ORDER BY created_at DESC LIMIT ?''',
                (f'-{days} days', limit),
            ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error as exc:
        logger.warning('get_conversation_summaries failed: %s', exc)
        return []


# ── 清理/压缩 ───────────────────────────────────────────────────────
def compress(days_keep=30):
    """清理 N 天前数据，优化 WAL。"""
    try:
        with _connect() as conn:
            conn.execute(
                'DELETE FROM task_memory '
                "WHERE created_at < datetime('now', ?)",
                (f'-{days_keep} days',),
            )
            conn.execute(
                'DELETE FROM conversation_summaries '
                "WHERE created_at < datetime('now', ?)",
                (f'-{days_keep} days',),
            )
            conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        logger.info('memory compress ok (keep %d days)', days_keep)
        return True
    except sqlite3.Error as exc:
        logger.warning('memory compress failed: %s', exc)
        return False


def status():
    return {
        'db_path': MEMORY_DB,
        'db_size_mb': round(
            (os.path.getsize(MEMORY_DB) / 1024 / 1024)
            if os.path.exists(MEMORY_DB) else 0, 2,
        ),
        **summary(),
    }


# ── 今日状态（给 context 注入器用） ────────────────────────
def get_today_state():
    """返回今日任务统计，用于 LLM 上下文注入。"""
    try:
        with _connect() as conn:
            # 今日任务数
            tasks = conn.execute(
                "SELECT COUNT(*) AS c FROM task_memory "
                "WHERE created_at >= date('now')",
            ).fetchone()['c']
            # 今日成功任务
            success = conn.execute(
                "SELECT COUNT(*) AS c FROM task_memory "
                "WHERE created_at >= date('now') AND outcome='success'",
            ).fetchone()['c']
            # 今日对话消息数（conversation_summaries 中的数量）
            try:
                conv = conn.execute(
                    "SELECT SUM(messages_count) AS c FROM conversation_summaries "
                    "WHERE created_at >= date('now')",
                ).fetchone()['c'] or 0
            except sqlite3.Error:
                conv = 0
        return {
            'messages_count': conv,
            'tasks_completed': success,
            'files_modified': tasks,
            'total_today': tasks,
        }
    except sqlite3.Error as exc:
        logger.warning('get_today_state failed: %s', exc)
        return {'messages_count': 0, 'tasks_completed': 0,
                'files_modified': 0, 'total_today': 0}


# ── 记忆检索（给 context 注入器用） ────────────────────────
def search_memory(keyword, limit=3):
    """全文检索相关记忆。优先 FTS5，退化为 LIKE。"""
    if not keyword or not keyword.strip():
        return []
    term = keyword.strip()
    try:
        with _connect() as conn:
            # 先试 FTS5
            try:
                rows = conn.execute(
                    '''SELECT tm.task_id, tm.input_summary, tm.outcome,
                              tm.agent, tm.task_type, tm.created_at
                       FROM task_fts
                       JOIN task_memory tm ON tm.id = task_fts.rowid
                       WHERE task_fts MATCH ?
                       ORDER BY rank LIMIT ?''',
                    (f'"{term}"', limit),
                ).fetchall()
                if rows:
                    return [dict(r) for r in rows]
            except sqlite3.Error:
                pass  # FTS5 可能因老版本不支持，走 LIKE 回退
            # LIKE 回退
            rows = conn.execute(
                '''SELECT task_id, input_summary, outcome, agent, task_type, created_at
                   FROM task_memory
                   WHERE input_summary LIKE ? ORDER BY created_at DESC LIMIT ?''',
                (f'%{term}%', limit),
            ).fetchall()
            return [dict(r) for r in rows]
    except sqlite3.Error as exc:
        logger.warning('search_memory failed: %s', exc)
        return []
