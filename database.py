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
from datetime import datetime, timedelta

DB_FILE = "vocab_learning.db"

def get_connection():
    """获取数据库连接（连接到项目根目录下的 DB_FILE）"""
    return sqlite3.connect(DB_FILE)

def init_db():
    """初始化数据库结构（幂等）

    包含表：
    - users: 用户基本信息与偏好
    - vocabulary: 全局词汇表（去重）
    - learning_records: 用户与词汇的学习关联记录
    - ai_logs: AI 交互记录（用于审计/分析）
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
        preferences TEXT
    )
    ''')
    
    # vocabulary table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS vocabulary (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        word TEXT UNIQUE,
        phonetic TEXT,
        definition TEXT,
        difficulty INTEGER DEFAULT 1,
        tags TEXT
    )
    ''')
    
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
    
    # Indexes for performance
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_records_user ON learning_records(user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_records_next_review ON learning_records(next_review)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_ai_logs_user_time ON ai_logs(user_id, timestamp)')

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

# Vocabulary Operations
def add_vocabulary(word, phonetic, definition, difficulty=1, tags=""):
    """新增词汇；若已存在则返回其 id

    返回：词汇主键 id
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO vocabulary (word, phonetic, definition, difficulty, tags) VALUES (?, ?, ?, ?, ?)',
                       (word, phonetic, definition, difficulty, tags))
        vocab_id = cursor.lastrowid
        conn.commit()
        return vocab_id
    except sqlite3.IntegrityError:
        cursor.execute('SELECT id FROM vocabulary WHERE word = ?', (word,))
        vocab_id = cursor.fetchone()[0]
        return vocab_id
    finally:
        conn.close()

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

def get_due_vocabulary(user_id, limit=10):
    """获取某用户到期需要复习的词汇

    返回：(vocabulary.*, review_count, last_review) 的行列表
    """
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now()
    cursor.execute('''
        SELECT v.*, r.review_count, r.last_review 
        FROM learning_records r
        JOIN vocabulary v ON r.vocab_id = v.id
        WHERE r.user_id = ? AND r.next_review <= ?
        ORDER BY r.next_review ASC
        LIMIT ?
    ''', (user_id, now, limit))
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
    print("Database initialized.")
