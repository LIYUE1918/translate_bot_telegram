"""AI 服务封装层

职责：
- 统一封装对 302.AI 的调用（兼容 OpenAI Chat Completions 格式）
- 提供简单的内存缓存与限流策略，避免频繁请求与滥用
- 面向上层的高阶能力：翻译、学习进度总结、难词提取、计划生成

环境变量：
- AI_API_KEY：访问 302.AI 的密钥（从 .env 或系统环境变量读取）
"""
import os
import aiohttp
import asyncio
import json
import time
from datetime import datetime
import logging
from database import log_ai_interaction, get_learning_stats, get_recent_learning_logs

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 302.AI Configuration
API_BASE_URL = "https://api.302.ai/v1/chat/completions"
DEFAULT_MODEL = "deepseek-v3.2" # Non-thinking version
# Thinking version is "deepseek-v3.2-thinking" if needed

# In-memory cache: {query_hash: (response, timestamp)}
_CACHE = {}
CACHE_TTL = 3600 * 24 # 24 hours

# Rate limiting: {user_id: [timestamp, ...]}
_RATE_LIMIT = {}
RATE_LIMIT_WINDOW = 60 # seconds
RATE_LIMIT_MAX_REQUESTS = 10

def get_api_key():
    """读取 AI 接口密钥

    优先从环境变量中获取，注意不要将密钥硬编码在代码里。
    """
    return os.environ.get("AI_API_KEY")

async def call_ai_api(messages, model=DEFAULT_MODEL, temperature=0.7, max_tokens=1000):
    """底层请求函数：调用 302.AI Chat Completions

    参数：
    - messages: 聊天消息数组（role/content）
    - model: 使用的模型名称
    - temperature: 随机性
    - max_tokens: 最长生成长度

    返回：LLM 返回的字符串内容；如失败返回错误信息
    """
    api_key = get_api_key()
    if not api_key:
        logger.warning("AI_API_KEY not set in environment variables.")
        return "Error: AI_API_KEY is not configured. Please set it in .env file."

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(API_BASE_URL, headers=headers, json=payload) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"AI API Error: {response.status} - {error_text}")
                    return f"AI Service Error: {response.status}"
                
                data = await response.json()
                return data['choices'][0]['message']['content']
        except Exception as e:
            logger.error(f"AI Request Failed: {e}")
            return f"AI Request Failed: {str(e)}"

def check_rate_limit(user_id):
    """简单的滑动窗口限流

    在 RATE_LIMIT_WINDOW 秒内最多允许 RATE_LIMIT_MAX_REQUESTS 次请求。
    返回 True 表示允许；False 表示超限。
    """
    now = time.time()
    if user_id not in _RATE_LIMIT:
        _RATE_LIMIT[user_id] = []
    
    # Clean old requests
    _RATE_LIMIT[user_id] = [t for t in _RATE_LIMIT[user_id] if now - t < RATE_LIMIT_WINDOW]
    
    if len(_RATE_LIMIT[user_id]) >= RATE_LIMIT_MAX_REQUESTS:
        return False
    
    _RATE_LIMIT[user_id].append(now)
    return True

def get_cached_response(query):
    """读取查询缓存（针对可缓存的固定任务，如总结）"""
    query_hash = hash(query)
    if query_hash in _CACHE:
        response, timestamp = _CACHE[query_hash]
        if time.time() - timestamp < CACHE_TTL:
            return response
        else:
            del _CACHE[query_hash]
    return None

def set_cache_response(query, response):
    """写入查询缓存"""
    query_hash = hash(query)
    _CACHE[query_hash] = (response, time.time())

async def get_ai_response(user_id, query, system_prompt="You are a helpful language learning assistant.", model=DEFAULT_MODEL, temperature=0.7):
    """通用对话接口封装

    - 做限流校验
    - 调用底层 API
    - 记录审计日志（问题/回答/模型）
    """
    if not check_rate_limit(user_id):
        return "Rate limit exceeded. Please try again later."
    
    # Check cache for simple queries (optional, maybe not for chat)
    # For now, we only cache specific heavy tasks like summaries
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": query}
    ]
    
    response = await call_ai_api(messages, model=model, temperature=temperature)
    
    # Log interaction
    log_ai_interaction(user_id, query, response, model)
    
    return response

async def summarize_learning_progress(user_id, days=7):
    """学习进度总结

    从数据库获取近 days 天的数据，生成简短总结并缓存结果。
    """
    cache_key = f"summary_{user_id}_{days}"
    cached = get_cached_response(cache_key)
    if cached:
        return cached

    # Get stats from DB
    stats = get_learning_stats(user_id, days) # Returns (count, avg_mastery)
    count, mastery = stats if stats else (0, 0)
    
    prompt = f"""
    use chinese language to write the summary   
    Please analyze the user's learning progress for the last {days} days.
    - Words reviewed: {count}
    - Average mastery level: {mastery:.2f} (scale 0-1)
    
    Provide a concise summary, identify potential weaknesses if mastery is low, and suggest a study plan.
    """
    
    response = await get_ai_response(user_id, prompt, model=DEFAULT_MODEL)
    set_cache_response(cache_key, response)
    return response

async def ai_translate(text, target_lang="zh", model=DEFAULT_MODEL):
    """使用 LLM 进行翻译（仅返回译文，不包含解释）

    说明：相比第三方翻译库，LLM 翻译适合在 DeepSeek 模型可用且对风格有要求时使用。
    """
    prompt = f"Translate the following text to {target_lang}. Only provide the translation, no explanations.\n\nText: {text}"
    # Use a simpler system prompt for translation
    return await get_ai_response(0, prompt, system_prompt="You are a professional translator.", model=model)

async def extract_difficult_words(text, min_level=6, max_new_words=50):
    """提取难词
    
    1. 接收一段文本
    2. 调用 AI 模型返回“复杂词汇列表”（≥CET-6、雅思 7 分、专八等标准）。
    3. 返回 JSON 格式的列表
    """
    prompt = f"""
    Identify difficult words (>= CET-6/IELTS 7/GRE level) from the text below.
    Exclude simple words. 
    Return a JSON list of objects with fields: 'word', 'phonetic', 'definition' (in Chinese), 'difficulty' (integer 1-10).
    Max {max_new_words} words.
    
    Text:
    {text}
    
    Format:
    [
      {{"word": "example", "phonetic": "/.../", "definition": "...", "difficulty": 8}},
      ...
    ]
    Only return the JSON.
    """
    
    response = await get_ai_response(0, prompt, system_prompt="You are a vocabulary expert.", temperature=0.3)
    try:
        # Try to parse JSON from response
        # AI might wrap in ```json ... ```
        clean_resp = response.replace("```json", "").replace("```", "").strip()
        words = json.loads(clean_resp)
        if isinstance(words, list):
            return words, response # Return raw response too for audit logs if needed
        else:
            return [], response
    except Exception as e:
        logger.error(f"Failed to parse difficult words: {e}")
        return [], response

async def generate_learning_plan(user_id):
    """生成 7 日学习计划
    
    1. 读取用户近 30 天学习日志（单词、正确率、复习间隔、耗时）。
    2. 调用 AI 模型，输入上述指标，输出未来 7 天每日任务：新词量、复习量、预计时长、重点词根。
    """
    logs = get_recent_learning_logs(user_id, days=30)
    # log format: (date, count, avg_mastery)
    
    log_summary = "\n".join([f"Date: {l[0]}, Reviewed: {l[1]}, Mastery: {l[2]:.2f}" for l in logs])
    
    prompt = f"""
    Based on the user's learning history (last 30 days):
    {log_summary}
    
    Create a 7-day study plan (Day 1 to Day 7).
    For each day, provide:
    - new_words_count (int)
    - review_count (int)
    - estimated_minutes (int)
    - focus_topic (string, e.g. "Root: struct", "Topic: Technology")
    
    Return purely JSON format:
    {{
      "days": [
        {{"day": 1, "new_words": 10, "review": 20, "minutes": 15, "focus": "..."}},
        ...
      ]
    }}
    """
    
    response = await get_ai_response(user_id, prompt, system_prompt="You are a study planner.", temperature=0.5)
    try:
        clean_resp = response.replace("```json", "").replace("```", "").strip()
        plan = json.loads(clean_resp)
        return plan
    except Exception as e:
        logger.error(f"Failed to parse plan: {e}")
        return None

async def generate_words_custom(count, source="system", level_filter="CET-6"):
    """自定义生成单词
    """
    prompt = f"""
    Generate {count} English words for a learner.
    Source/Topic: {source}
    Difficulty Level: {level_filter}
    
    Format: Word | Phonetic | Definition (Chinese)
    One per line.
    """
    return await get_ai_response(0, prompt, temperature=0.7)

async def fuzzy_match_word(word, max_candidates=5):
    prompt = f"""
    You are an English spell-correction assistant.
    Input: "{word}"
    
    Rules:
    1. If the input is a valid English word (including slang, proper nouns, inflected forms), set "is_valid": true.
    2. If it's likely a typo, set "is_valid": false and provide the best corrections.
    3. If "is_valid" is true, provide its primary Chinese translation in "cn".
    4. Ensure candidates are UNIQUE and do not include the input or the "best" word.
    
    Return strict JSON:
    {{
      "input": "{word}",
      "is_valid": true/false,
      "best": {{"word": "...", "confidence": 0.0, "cn": "..."}},
      "candidates": [
        {{"word": "...", "confidence": 0.0}}
      ]
    }}
    Only output JSON.
    """
    resp = await get_ai_response(0, prompt, system_prompt="You correct spelling and return JSON.", temperature=0.0)
    try:
        clean = resp.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean)
        return data
    except Exception:
        return {"input": word, "is_valid": True, "best": {"word": word, "confidence": 0.99, "cn": ""}, "candidates": []}

async def get_word_detail(word):
    prompt = f"""
    Provide detailed information for the English word: {word}
    Include:
    - Full meanings with parts of speech in Chinese
    - Gerund/participles or verbal noun forms if applicable
    - 3 example sentences (English) with Chinese translations
    - 3 synonyms and 3 antonyms
    - IPA for UK and US as uk_ipa and us_ipa
    Return strict JSON:
    {{
      "word":"{word}",
      "uk_ipa":"...",
      "us_ipa":"...",
      "meanings":[{{"pos":"...", "cn":"..."}}],
      "gerund":"...",
      "examples":[{{"en":"...", "cn":"..."}}],
      "synonyms":["..."],
      "antonyms":["..."]
    }}
    Only output JSON.
    """
    resp = await get_ai_response(0, prompt, system_prompt="You are a lexicon expert returning JSON.", temperature=0.2)
    try:
        clean = resp.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean)
        return data
    except Exception:
        return None

async def chat_word(user_id, text):
    prompt = f"""
    User asks about: {text}
    
    Instructions:
    1. If the input is Chinese, explain it directly WITHOUT Pinyin.
    2. Do NOT use markdown bold syntax (**text**). Use headers like 【Memory】, 【Examples】, 【Root】 or emojis to structure the response.
    3. Format the output clearly and friendly.

    Provide:
    - Memory techniques or cultural context (if applicable)
    - 2 concise example sentences (EN/CN)
    - Root/affix analysis (if applicable)
    
    Keep under 150 words.
    """
    return await get_ai_response(user_id, prompt, system_prompt="You are a helpful vocabulary tutor.", model=DEFAULT_MODEL, temperature=0.7)

async def get_ipa(word):
    async def cambridge_ipa(w, accent):
        return None
    detail = await get_word_detail(word)
    if detail and detail.get("uk_ipa") and detail.get("us_ipa"):
        return {"uk": detail.get("uk_ipa"), "us": detail.get("us_ipa")}
    uk_try = await cambridge_ipa(word, "uk")
    us_try = await cambridge_ipa(word, "us")
    if uk_try or us_try:
        return {"uk": uk_try or "", "us": us_try or ""}
    prompt = f"Provide UK and US IPA for the word '{word}' as JSON {{\"uk\":\"/.../\",\"us\":\"/.../\"}}. Only JSON."
    resp = await get_ai_response(0, prompt, system_prompt="Return IPA JSON only.", temperature=0.0)
    try:
        clean = resp.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean)
        uk = data.get("uk") or data.get("uk_ipa") or ""
        us = data.get("us") or data.get("us_ipa") or ""
        return {"uk": uk, "us": us}
    except Exception:
        return {"uk": "", "us": ""}
