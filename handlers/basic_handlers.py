import time
import database as db
import ai_service
import translators as ts
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# 默认设置
DEFAULT_SRC = "auto"
DEFAULT_TGT = "zh"
DEFAULT_MODE = "bing"
DEFAULT_COUNT = True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start 命令处理器：收到 /start 时发送欢迎语"""
    await update.message.reply_text(
        "你好！我是你的 Telegram 翻译机器人。\n"
        "你可以直接发送消息进行翻译。\n\n"
        "📚 **学习功能**：\n"
        "/daily - 获取今日学习词汇\n"
        "/review - 开始复习生词\n"
        "/summary - 查看学习进度总结\n\n"
        "⚙️ **设置**：\n"
        "/settings - 打开详细设置面板\n"
        "(包含：语言、引擎、计时开关)\n\n"
        "提示：在翻译结果下点击按钮可将单词加入生词本。"
    )

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """文本消息处理器：对非命令的纯文本进行回声回复（翻译）"""
    text = update.message.text or ""
    user_id = update.effective_user.id
    
    # Ensure user exists in DB
    db.create_user(user_id, update.effective_user.username or "User")
    
    src = context.user_data.get("translate_src", DEFAULT_SRC)
    tgt = context.user_data.get("translate_tgt", context.user_data.get("translate_lang", DEFAULT_TGT))
    engine = context.user_data.get("translate_mode", DEFAULT_MODE)
    show_time = context.user_data.get("translate_count", DEFAULT_COUNT)
    
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
        
        # Add 'Add to Vocab' button if translation is English or source is English (assuming learning English)
        keyboard = None
        # Simple heuristic: if result is English or input is English-like
        if tgt == "en" or (src == "en") or (len(res.split()) < 5 and res.isascii()):
            word_to_add = res if tgt == "en" else text
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton(f"Add '{word_to_add}' to Vocabulary", callback_data=f"add_vocab:{word_to_add}")
            ]])
            
        await update.message.reply_text(msg, reply_markup=keyboard)
    except Exception as e:
        await update.message.reply_text(f"翻译失败，请稍后再试: {str(e)}")
