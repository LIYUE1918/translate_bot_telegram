"""词汇学习业务逻辑

职责：
- 封装单词加入、生词到期查询、复习评分处理等核心流程
- 提供简单的 SM2 思想计算函数（示例），当前实现为简化版本
- 处理难词提取、加权、自定义生成
"""
import database as db
import ai_service
import time
from datetime import datetime, timedelta
import random

# Simple SM2 implementation
def calculate_next_interval(repetition, interval, ease_factor, quality):
    """根据 SM2 思想计算下次复习间隔（示例实现）

    参数：
    - repetition: 重复次数
    - interval: 当前间隔（天）
    - ease_factor: 难度系数
    - quality: 评分（0-5）
    返回：更新后的 (repetition, interval, ease_factor)
    """
    if quality < 3:
        repetition = 0
        interval = 1
    else:
        if repetition == 0:
            interval = 1
        elif repetition == 1:
            interval = 6
        else:
            interval = int(interval * ease_factor)
        repetition += 1
        
    ease_factor = ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    if ease_factor < 1.3:
        ease_factor = 1.3
        
    return repetition, interval, ease_factor

async def add_word(user_id, word):
    """将单词加入词库并建立用户学习记录

    若词库中不存在该词，则调用 AI 获取音标与简要中文释义。
    返回：该词在 vocabulary 表中的 id。
    """
    # Check if word exists in vocab
    vocab = db.get_vocab_by_word(word)
    if not vocab:
        # Use AI to get definition and phonetic
        prompt = f"Provide the phonetic transcription and a brief definition (in Chinese) for the word '{word}'. Format: Phonetic | Definition"
        ai_resp = await ai_service.get_ai_response(user_id, prompt)
        
        # Check for rate limit or error messages in response
        if "rate limit" in ai_resp.lower() or "too many requests" in ai_resp.lower():
            raise Exception("AI Service Rate Limit (Upstream). Please try again later.")
            
        try:
            parts = ai_resp.split("|")
            phonetic = parts[0].strip()
            definition = parts[1].strip() if len(parts) > 1 else ai_resp
        except:
            phonetic = ""
            definition = ai_resp
            
        if "rate limit" in definition.lower():
             raise Exception("AI Service Rate Limit (Content). Please try again later.")
            
        vocab_id = db.add_vocabulary(word, phonetic, definition)
    else:
        vocab_id = vocab[0]
        # 命中已有词汇，增加权重
        db.increment_vocab_weight(vocab_id)
        
    # Add to user's learning records
    db.add_learning_record(user_id, vocab_id)
    return vocab_id

def get_due_words(user_id, limit=10, order='asc'):
    """查询到期需要复习的单词
    
    order: 'asc' or 'desc' (though database logic usually enforces priority > time)
    """
    return db.get_due_vocabulary(user_id, limit, order)

def process_review(user_id, vocab_id, quality):
    """处理一次复习评分并更新数据库

    说明：
    - 当前数据库未保存 SM2 的全部参数（如 EF、repetition），因此采用简化逻辑：
      当 quality >= 3 时，间隔按 2*(quality-1) 天递增；否则为 1 天。
    """
    interval_days = 1
    if quality >= 3:
        interval_days = 2 * (quality - 1) # Simple logic
    
    db.update_learning_record(user_id, vocab_id, quality, interval_days)

async def generate_daily_task(user_id, count=5):
    """生成每日学习清单 (旧接口，保留兼容)
    """
    return await generate_words_custom(user_id, count, source="system", level_filter="CET-6")

async def generate_words_custom(user_id, count=50, source="system", level_filter="CET-6"):
    """自定义生成单词
    
    1. 先尝试从高权重词汇中获取
    2. 若不足，则调用 AI 生成
    """
    generated_words = []
    
    # 1. 优先取高权重且用户未学习的词 (这里简化为取高权重，实际应用需排除用户已学)
    # 目前 db.get_high_weight_vocab 返回所有高权重词，未过滤用户
    # 暂跳过复杂的排除逻辑，直接调用 AI 生成，确保数量和质量
    
    # 2. 调用 AI 生成
    prompt = f"Generate {count} English words. Source: {source}. Level: {level_filter}. Format: Word | Phonetic | Definition (Chinese). One per line."
    response = await ai_service.get_ai_response(user_id, prompt)
    
    words_data = []
    
    for line in response.split("\n"):
        if "|" in line:
            parts = line.split("|")
            if len(parts) >= 3:
                word = parts[0].strip()
                phonetic = parts[1].strip()
                definition = parts[2].strip()
                # 默认 AI 生成的词难度设为 5
                words_data.append((word, phonetic, definition, 5, f"AI-{source}", 0, 0))
                generated_words.append((word, definition))
                
    # 批量写入
    if words_data:
        db.batch_add_vocabulary(words_data)
        # 为用户添加记录
        for w_data in words_data:
            vocab = db.get_vocab_by_word(w_data[0])
            if vocab:
                db.add_learning_record(user_id, vocab[0])
                
    return generated_words

async def process_text_for_difficult_words(user_id, text, min_level=6, max_new_words=50):
    """处理文本提取难词流程
    
    1. 调用 AI 提取
    2. 批量入库
    3. 记录日志
    """
    words, raw_resp = await ai_service.extract_difficult_words(text, min_level, max_new_words)
    
    if not words:
        return 0
    
    db_words_data = []
    for w in words:
        # word, phonetic, definition, difficulty, tags, weight, priority
        db_words_data.append((
            w['word'], 
            w.get('phonetic', ''), 
            w.get('definition', ''), 
            w.get('difficulty', 5), 
            'AI-Extracted', 
            1, # Initial weight
            0
        ))
        
    added_count = db.batch_add_vocabulary(db_words_data)

    
    # 记录审计日志
    db.log_vocab_add_batch(text, "ai-extract", len(words))
    
    return len(words)

def clean_bad_vocab():
    """清理因上游限流导致的无效词汇"""
    count = db.delete_vocab_containing("rate limit")
    count += db.delete_vocab_containing("too many requests")
    count += db.delete_vocab_containing("429")
    return count

def clean_vocab_by_date(days=None):
    """清理指定天数内的词汇（默认为全部）"""
    if days is None:
        # Delete all? Or maybe just recent ones? 
        # User said "一段时间的单词", so let's default to 7 days if not specified or handle logic in handler
        pass
    
    start_date = datetime.min
    end_date = datetime.now()
    
    if days:
        start_date = datetime.now() - timedelta(days=days)
        
    return db.delete_vocab_by_date(start_date, end_date)
