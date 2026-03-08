import time
import re
import database as db
import ai_service
import vocab_manager
import translators as ts
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import asyncio
from handlers.settings_handlers import DEFAULT_SRC, DEFAULT_TGT, DEFAULT_MODE, DEFAULT_COUNT, DEFAULT_AUTO_CUT
from logger_config import logger

# Auth Key
AUTH_KEY = "芝麻开门"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start 命令处理器：收到 /start 时发送欢迎语"""
    user_id = update.effective_user.id
    db.create_user(user_id, update.effective_user.username or "User")
    status, _ = db.check_auth_status(user_id)
    if status != 1:
        await update.message.reply_text("🔒 欢迎使用！首次使用请输入访问密钥：")
        return

    await update.message.reply_text(
        "你好！我是你的 Telegram 翻译机器人。\n"
        "你可以直接发送消息进行翻译。\n\n"
        "📚 **学习功能**：\n"
        "/daily - 获取今日学习词汇\n"
        "/review - 开始复习生词\n"
        "/words - 查看历史单词\n"
        "/plan - 查看学习计划\n"
        "/summary - 查看学习进度总结\n"
        "/cut [text] - 切分句子为单词按钮\n"
        "/import [text] - 智能提取重点词汇\n\n"
        "⚙️ **设置**：\n"
        "/settings - 打开详细设置面板\n"
        "(包含：语言、引擎、计时开关、自动切词)\n\n"
        "提示：在翻译结果下点击按钮可将单词加入生词本。"
    )

import database as db
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# Auth Key
AUTH_KEY = "芝麻开门"

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """文本消息处理器：对非命令的纯文本进行回声回复（翻译）"""
    text = update.message.text or ""
    user_id = update.effective_user.id
    
    # Ensure user exists in DB
    db.create_user(user_id, update.effective_user.username or "User")
    
    # Check Auth Status
    status, attempts = db.check_auth_status(user_id)
    if status == -1: # Banned
        return # Ignore banned users
        
    if status == 0: # Unauthenticated
        if text.strip() == AUTH_KEY:
            db.update_auth_status(user_id, 1, 0) # Authenticated
            await update.message.reply_text("🎉 认证成功！欢迎使用翻译机器人。")
            return
        else:
            attempts += 1
            if attempts >= 5:
                db.update_auth_status(user_id, -1, attempts)
                await update.message.reply_text("⛔️ 错误次数过多，您已被封禁。")
            else:
                db.update_auth_status(user_id, 0, attempts)
                await update.message.reply_text(f"🔒 请输入访问密钥（剩余机会：{5-attempts} 次）：")
            return

    src = context.user_data.get("translate_src", DEFAULT_SRC)
    tgt = context.user_data.get("translate_tgt", context.user_data.get("translate_lang", DEFAULT_TGT))
    engine = context.user_data.get("translate_mode", DEFAULT_MODE)
    show_time = context.user_data.get("translate_count", DEFAULT_COUNT)
    auto_cut = context.user_data.get("auto_cut", DEFAULT_AUTO_CUT)
    
    try:
        start_time = time.perf_counter()
        if engine == "deepseek":
            res = await ai_service.ai_translate(text, target_lang=tgt)
        elif engine == "google":
            res = ts.translate_text(text, from_language=src, to_language=tgt)
        elif engine == "bing":
            res = ts.translate_text(text, from_language=src, to_language=tgt, translator="bing")
        else:
            res = ts.translate_text(text, from_language=src, to_language=tgt, translator=engine)
        elapsed = time.perf_counter() - start_time
        
        msg = res if not show_time else f"{res}\n\n[{engine} {elapsed:.3f}s]"
        
        keyboard = None
        
        # 自动切词逻辑：
        # 如果 auto_cut 开启，或者用户显式调用 /cut（虽然这是 echo，但逻辑可以复用）
        # 优化逻辑：优先切分英文内容（无论是源文还是译文）
        
        target_is_en = (tgt == "en")
        source_is_en = (src == "en") or (len(text.split()) > 0 and text.isascii()) # 简单判断源文是否英文
        result_is_en = (len(res.split()) > 0 and res.isascii())

        # 确定潜在的英文文本
        english_text = None
        if target_is_en or result_is_en:
            english_text = res
        elif source_is_en:
            english_text = text
            
        keyboard = None
        if auto_cut and english_text:
            keyboard = _generate_word_buttons(english_text)
        else:
            # 只有当翻译结果是英文，或者原句是英文时，才显示“添加整句”按钮
            if english_text:
                # 只有比较短的才显示添加整句，太长的句子建议用 /cut
                if len(english_text.split()) <= 10:
                    keyboard = InlineKeyboardMarkup([[
                        InlineKeyboardButton(f"Add '{english_text}' to Vocabulary", callback_data=f"add_vocab:{english_text}")
                    ]])
            
        await update.message.reply_text(msg, reply_markup=keyboard)
        
        # AI 难词筛选机制 (异步执行，不阻塞翻译返回)
        if english_text and len(english_text.split()) > 3:
             # 使用 asyncio.create_task 在后台运行，不等待结果
            asyncio.create_task(_process_difficult_words(user_id, english_text, update))
            
    except Exception as e:
        await update.message.reply_text(f"翻译失败，请稍后再试: {str(e)}")

async def cut_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/cut 命令：手动切分句子为单词按钮"""
    text = ""
    if context.args:
        text = " ".join(context.args)
    elif update.message.reply_to_message and update.message.reply_to_message.text:
        text = update.message.reply_to_message.text
    else:
        await update.message.reply_text("请在命令后输入文本，或回复一条消息使用 /cut")
        return

    # 简单判断是否包含英文，主要切分英文
    # 这里不做严格限制，尝试切分空格分隔的语言
    keyboard = _generate_word_buttons(text)
    if keyboard:
        await update.message.reply_text(f"已切分句子：\n{text}", reply_markup=keyboard)
    else:
        await update.message.reply_text("未找到可切分的单词（可能是纯中文或无空格）。")

def _generate_word_buttons(text):
    """辅助函数：将文本切分为单词按钮"""
    # 简单的正则切分，保留英文单词和连字符
    words = re.findall(r'\b[a-zA-Z\-\']+\b', text)
    # 去重并保持顺序
    seen = set()
    unique_words = []
    for w in words:
        w_lower = w.lower()
        if w_lower not in seen and len(w) > 1: # 忽略单字母（如 I, a 除外? 这里简单处理）
            seen.add(w_lower)
            unique_words.append(w)
    
    if not unique_words:
        return None
        
    # 生成按钮，每行 3 个
    buttons = []
    row = []
    for w in unique_words:
        row.append(InlineKeyboardButton(w, callback_data=f"add_vocab:{w}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
        
    # 添加“关闭”按钮
    buttons.append([InlineKeyboardButton("✖️ 关闭", callback_data="close_keyboard")])
        
    return InlineKeyboardMarkup(buttons)

async def _process_difficult_words(user_id, text, update):
    """后台处理难词提取"""
    try:
        count = await vocab_manager.process_text_for_difficult_words(user_id, text)
        if count > 0:
            # 可选：通知用户提取了多少个难词，或者静默处理
            # 避免打扰用户，这里选择静默，或者在 debug 模式下输出
            pass
    except Exception as e:
        logger.error(f"Error processing difficult words: {e}", exc_info=True)
