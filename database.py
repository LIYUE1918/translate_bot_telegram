"""数据访问层（SQLite）

职责：
- 初始化并维护本地 SQLite 数据库结构
- 提供对用户、词汇、生词学习记录、AI 调用日志的 CRUD 接口

注意：
- 所有函数均为轻量封装，调用后及时关闭连接，避免句柄泄漏
- 表结构见 init_db 内部的 DDL
"""
import sqlite3
import json
import time
import hashlib
from datetime import datetime, timedelta
from logger_config import logger

DB_FILE = "vocab_learning.db"

def get_connection():
    """获取数据库连接（连接到项目根目录下的 DB_FILE）"""
    return sqlite3.connect(DB_FILE)

def _has_column(cursor, table, column):
    cursor.execute(f"PRAGMA table_info({table})")
    rows = cursor.fetchall()
    for r in rows:
        if len(r) > 1 and r[1] == column:
            return True
    return False

def init_db():
    """初始化数据库结构（幂等）

    包含表：
    - users: 用户基本信息与偏好
    - vocabulary: 全局词汇表（去重）
    - learning_records: 用户与词汇的学习关联记录
    - ai_logs: AI 交互记录（用于审计/分析）
    - user_plan: 用户学习计划表
    - vocabulary_add_logs: 难词添加日志
    并建立常用索引以优化查询。
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # users table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        reg_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        preferences TEXT,
        auth_status INTEGER DEFAULT 0, -- 0: unauth, 1: auth, -1: banned
        auth_attempts INTEGER DEFAULT 0
    )
    ''')
    
    # 尝试添加 auth_status 和 auth_attempts 列 (migration)
    try:
        cursor.execute('ALTER TABLE users ADD COLUMN auth_status INTEGER DEFAULT 0')
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute('ALTER TABLE users ADD COLUMN auth_attempts INTEGER DEFAULT 0')
    except sqlite3.OperationalError:
        pass
    
    # vocabulary table
    # 新增 weight (权重), added_at (添加时间), priority (手动优先级)
    # 注意：SQLite ALTER TABLE 功能有限，若表已存在且无新字段，需手动迁移。
    # 这里使用 IF NOT EXISTS 和后续的 ALTER TABLE 尝试来保证兼容。
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS vocabulary (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        word TEXT UNIQUE,
        phonetic TEXT,
        definition TEXT,
        difficulty INTEGER DEFAULT 1,
        tags TEXT,
        weight INTEGER DEFAULT 0,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        priority INTEGER DEFAULT 0
    )
    ''')
    
    # 尝试添加新字段（如果旧表存在）
    try:
        cursor.execute('ALTER TABLE vocabulary ADD COLUMN weight INTEGER DEFAULT 0')
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute('ALTER TABLE vocabulary ADD COLUMN added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP')
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute('ALTER TABLE vocabulary ADD COLUMN priority INTEGER DEFAULT 0')
    except sqlite3.OperationalError:
        pass
    
    # learning_records table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS learning_records (
        user_id INTEGER,
        vocab_id INTEGER,
        status INTEGER DEFAULT 0, -- 0: new, 1: learning, 2: mastered
        review_count INTEGER DEFAULT 0,
        last_review TIMESTAMP,
        mastery_level FLOAT DEFAULT 0.0,
        next_review TIMESTAMP,
        PRIMARY KEY (user_id, vocab_id),
        FOREIGN KEY(user_id) REFERENCES users(user_id),
        FOREIGN KEY(vocab_id) REFERENCES vocabulary(id)
    )
    ''')
    
    # ai_logs table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ai_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        query TEXT,
        response TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        model TEXT
    )
    ''')
    
    # user_plan table (New)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_plan (
        user_id INTEGER PRIMARY KEY,
        plan_json TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(user_id)
    )
    ''')

    # vocabulary_add_logs (New for audit)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS vocabulary_add_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_hash TEXT,
        model_version TEXT,
        success_count INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Indexes for performance
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_records_user ON learning_records(user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_records_next_review ON learning_records(next_review)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_ai_logs_user_time ON ai_logs(user_id, timestamp)')
    if _has_column(cursor, 'vocabulary', 'weight'):
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_vocab_weight ON vocabulary(weight)')
    if _has_column(cursor, 'vocabulary', 'added_at'):
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_vocab_added ON vocabulary(added_at)')

    conn.commit()
    conn.close()

# User Operations
def get_user(user_id):
    """按 user_id 查询用户"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

def create_user(user_id, username, preferences=None):
    """创建用户（若存在则忽略）

    preferences 以 JSON 形式存储，便于扩展。
    """
    conn = get_connection()
    cursor = conn.cursor()
    prefs = json.dumps(preferences or {})
    try:
        cursor.execute('INSERT INTO users (user_id, username, preferences) VALUES (?, ?, ?)', 
                       (user_id, username, prefs))
        conn.commit()
    except sqlite3.IntegrityError:
        pass # User already exists
    conn.close()

def update_user_preferences(user_id, preferences):
    """更新用户偏好设置（整体覆盖）"""
    conn = get_connection()
    cursor = conn.cursor()
    prefs = json.dumps(preferences)
    cursor.execute('UPDATE users SET preferences = ? WHERE user_id = ?', (prefs, user_id))
    conn.commit()
    conn.close()

def check_auth_status(user_id):
    """检查用户认证状态
    return: status (0: unauth, 1: auth, -1: banned), attempts
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT auth_status, auth_attempts FROM users WHERE user_id = ?', (user_id,))
    res = cursor.fetchone()
    conn.close()
    if res:
        return res[0], res[1]
    return 0, 0 # Default unauth if not found (will be created in echo)

def update_auth_status(user_id, status, attempts=None):
    """更新认证状态"""
    conn = get_connection()
    cursor = conn.cursor()
    if attempts is not None:
        cursor.execute('UPDATE users SET auth_status = ?, auth_attempts = ? WHERE user_id = ?', (status, attempts, user_id))
    else:
        cursor.execute('UPDATE users SET auth_status = ? WHERE user_id = ?', (status, user_id))
    conn.commit()
    conn.close()

# Vocabulary Operations
def add_vocabulary(word, phonetic, definition, difficulty=1, tags="", weight=0, priority=0):
    """新增词汇；若已存在则返回其 id
    
    支持新字段 weight 和 priority
    返回：词汇主键 id
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO vocabulary (word, phonetic, definition, difficulty, tags, weight, priority) 
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (word, phonetic, definition, difficulty, tags, weight, priority))
        vocab_id = cursor.lastrowid
        conn.commit()
        return vocab_id
    except sqlite3.IntegrityError:
        cursor.execute('SELECT id FROM vocabulary WHERE word = ?', (word,))
        vocab_id = cursor.fetchone()[0]
        # 可以在这里选择是否更新现有词汇的权重，暂时保持不变
        return vocab_id
    finally:
        conn.close()

def batch_add_vocabulary(words_data):
    """批量添加词汇
    words_data: list of (word, phonetic, definition, difficulty, tags, weight, priority)
    """
    conn = get_connection()
    cursor = conn.cursor()
    added_count = 0
    try:
        for w in words_data:
            try:
                # word, phonetic, definition, difficulty, tags, weight, priority
                cursor.execute('''
                    INSERT INTO vocabulary (word, phonetic, definition, difficulty, tags, weight, priority) 
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', w)
                added_count += 1
            except sqlite3.IntegrityError:
                continue # Skip duplicates
        conn.commit()
    finally:
        conn.close()
    return added_count

def get_vocabulary(vocab_id):
    """按 id 获取词汇完整记录"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM vocabulary WHERE id = ?', (vocab_id,))
    vocab = cursor.fetchone()
    conn.close()
    return vocab

def get_vocab_by_word(word):
    """按单词文本查询词汇"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM vocabulary WHERE word = ?', (word,))
    vocab = cursor.fetchone()
    conn.close()
    return vocab

def increment_vocab_weight(vocab_id):
    """增加词汇权重"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE vocabulary SET weight = weight + 1 WHERE id = ?', (vocab_id,))
    conn.commit()
    conn.close()

def normalize_vocab_weights():
    """归一化权重（简单的防止无限膨胀，例如 weight = weight * 0.9 或重置）"""
    conn = get_connection()
    cursor = conn.cursor()
    # 这里简单实现为：所有权重减半，或者设置上限。
    # 按照需求 "防止无限膨胀"，我们可以设定一个衰减因子
    cursor.execute('UPDATE vocabulary SET weight = cast(weight * 0.9 as int)')
    conn.commit()
    conn.close()

def get_high_weight_vocab(limit=10):
    """获取高权重词汇"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM vocabulary ORDER BY weight DESC LIMIT ?', (limit,))
    items = cursor.fetchall()
    conn.close()
    return items

def log_vocab_add_batch(source_text, model_version, success_count):
    """记录批量添加日志"""
    conn = get_connection()
    cursor = conn.cursor()
    source_hash = hashlib.md5(source_text.encode('utf-8')).hexdigest()
    cursor.execute('''
        INSERT INTO vocabulary_add_logs (source_hash, model_version, success_count)
        VALUES (?, ?, ?)
    ''', (source_hash, model_version, success_count))
    conn.commit()
    conn.close()

# Learning Records Operations
def add_learning_record(user_id, vocab_id):
    """为用户添加某个词汇的学习记录

    默认状态置为学习中(status=1)，并将 last_review/next_review 初始化为当前时间。
    """
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now()
    try:
        cursor.execute('INSERT INTO learning_records (user_id, vocab_id, status, last_review, next_review) VALUES (?, ?, 1, ?, ?)',
                       (user_id, vocab_id, now, now))
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()

def update_learning_record(user_id, vocab_id, quality, interval_days):
    """
    Update learning record based on review quality (e.g., SM2 algorithm output)
    """
    # 依据质量分（quality）与间隔天数（interval_days）更新复习统计与下次复习时间
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now()
    next_rev = now + timedelta(days=interval_days)
    
    cursor.execute('''
        UPDATE learning_records 
        SET review_count = review_count + 1, 
            last_review = ?, 
            next_review = ?,
            mastery_level = mastery_level + ?
        WHERE user_id = ? AND vocab_id = ?
    ''', (now, next_rev, quality * 0.1, user_id, vocab_id)) # Simple mastery increment
    conn.commit()
    conn.close()

def get_due_vocabulary(user_id, limit=10, order='asc'):
    """获取某用户到期需要复习的词汇

    支持按优先级排序：priority DESC (high priority first), then next_review ASC
    order 参数主要用于前端展示列表时的辅助（如按时间倒序），但在复习逻辑中，通常按 next_review 升序。
    若要支持用户手动调整顺序（priority），则应加入排序条件。
    """
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now()
    
    # 优先复习：手动优先级高的 -> 到期时间早的
    # vocabulary 表中有 priority 字段
    sql = '''
        SELECT v.*, r.review_count, r.last_review 
        FROM learning_records r
        JOIN vocabulary v ON r.vocab_id = v.id
        WHERE r.user_id = ? AND r.next_review <= ?
        ORDER BY v.priority DESC, r.next_review ASC
        LIMIT ?
    '''
    cursor.execute(sql, (user_id, now, limit))
    items = cursor.fetchall()
    conn.close()
    return items

def get_learning_stats(user_id, days=7):
    """统计近 days 天的复习数量与平均掌握度"""
    conn = get_connection()
    cursor = conn.cursor()
    start_date = datetime.now() - timedelta(days=days)
    cursor.execute('''
        SELECT count(*), avg(mastery_level)
        FROM learning_records
        WHERE user_id = ? AND last_review >= ?
    ''', (user_id, start_date))
    stats = cursor.fetchone()
    conn.close()
    return stats

def get_recent_learning_logs(user_id, days=30):
    """获取最近30天的学习日志，用于AI规划"""
    conn = get_connection()
    cursor = conn.cursor()
    start_date = datetime.now() - timedelta(days=days)
    # 获取每日复习数、平均掌握度
    cursor.execute('''
        SELECT date(last_review), count(*), avg(mastery_level)
        FROM learning_records
        WHERE user_id = ? AND last_review >= ?
        GROUP BY date(last_review)
        ORDER BY date(last_review) ASC
    ''', (user_id, start_date))
    logs = cursor.fetchall()
    conn.close()
    return logs

# Plan Operations
def save_user_plan(user_id, plan_json):
    """保存用户学习计划"""
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now()
    cursor.execute('''
        INSERT INTO user_plan (user_id, plan_json, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET plan_json=excluded.plan_json, updated_at=excluded.updated_at
    ''', (user_id, plan_json, now))
    conn.commit()
    conn.close()

def get_user_plan(user_id):
    """获取用户学习计划"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT plan_json, updated_at FROM user_plan WHERE user_id = ?', (user_id,))
    res = cursor.fetchone()
    conn.close()
    return res

# Stats Operations
def get_user_word_stats(user_id, offset=0, limit=10):
    """获取用户单词统计列表"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Total count
    cursor.execute('SELECT count(*) FROM learning_records WHERE user_id = ?', (user_id,))
    total = cursor.fetchone()[0]
    
    # List
    cursor.execute('''
        SELECT v.word, r.last_review, r.review_count, r.mastery_level
        FROM learning_records r
        JOIN vocabulary v ON r.vocab_id = v.id
        WHERE r.user_id = ?
        ORDER BY r.last_review DESC
        LIMIT ? OFFSET ?
    ''', (user_id, limit, offset))
    items = cursor.fetchall()
    conn.close()
    return total, items

# AI Logs
def log_ai_interaction(user_id, query, response, model):
    """记录一次 AI 交互

    注意：仅记录必要字段，避免存储敏感数据。
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO ai_logs (user_id, query, response, model) VALUES (?, ?, ?, ?)',
                   (user_id, query, response, model))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    logger.info("Database initialized.")
