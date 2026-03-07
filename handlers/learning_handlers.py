import vocab_manager
import ai_service
import database as db
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

async def daily_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """获取今日学习词汇
    
    调用 vocab_manager 生成新词，并以 Markdown 列表形式返回。
    """
    user_id = update.effective_user.id
    await update.message.reply_text("正在为你生成今日词汇，请稍候...")
    try:
        words = await vocab_manager.generate_daily_task(user_id)
        msg = "📅 **今日词汇**\n\n"
        for w, definition in words:
            msg += f"• **{w}**: {definition}\n"
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"生成失败: {e}")

async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看学习进度总结
    
    调用 ai_service 分析最近 7 天的学习数据。
    """
    user_id = update.effective_user.id
    await update.message.reply_text("正在分析你的学习进度...")
    try:
        summary = await ai_service.summarize_learning_progress(user_id)
        await update.message.reply_text(summary)
    except Exception as e:
        await update.message.reply_text(f"分析失败: {e}")

async def review_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """开始复习生词
    
    获取到期单词，显示第一个单词（正面），并提供“显示答案”按钮。
    """
    user_id = update.effective_user.id
    due_words = vocab_manager.get_due_words(user_id)
    if not due_words:
        await update.message.reply_text("🎉 你已经完成了所有的复习任务！")
        return
    
    # Show first word
    word_data = due_words[0]
    # word_data structure: (id, word, phonetic, def, diff, tags, review_count, last_review) from DB query
    
    vocab_id = word_data[0]
    word = word_data[1]
    phonetic = word_data[2]
    # definition = word_data[3] # 此时不显示释义
    
    msg = f"📝 **复习**\n\n**{word}**\n{phonetic}\n\n(思考一下含义...)"
    keyboard = [[InlineKeyboardButton("显示答案", callback_data=f"review:show:{vocab_id}")]]
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def on_vocab_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理词汇相关的按钮回调
    
    包括：
    - add_vocab: 添加生词
    - review:show: 显示单词释义与评分按钮
    - review:rate: 记录评分并进入下一个词
    """
    query = update.callback_query
    data = query.data
    user_id = update.effective_user.id
    
    if data.startswith("add_vocab:"):
        word = data.split(":", 1)[1]
        try:
            await vocab_manager.add_word(user_id, word)
            await query.answer(f"已添加 '{word}' 到生词本")
            # Disable button
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception as e:
            await query.answer(f"添加失败: {e}")
            
    elif data.startswith("review:show:"):
        vocab_id = int(data.split(":")[-1])
        vocab = db.get_vocabulary(vocab_id)
        if not vocab:
            await query.answer("词汇不存在")
            return
            
        definition = vocab[3]
        msg = f"📖 **{vocab[1]}**\n{vocab[2]}\n\n释义：{definition}\n\n请评价你的记忆情况："
        keyboard = [
            [
                InlineKeyboardButton("忘记 (1)", callback_data=f"review:rate:{vocab_id}:1"),
                InlineKeyboardButton("困难 (2)", callback_data=f"review:rate:{vocab_id}:2"),
            ],
            [
                InlineKeyboardButton("一般 (3)", callback_data=f"review:rate:{vocab_id}:3"),
                InlineKeyboardButton("容易 (4)", callback_data=f"review:rate:{vocab_id}:4"),
                InlineKeyboardButton("极好 (5)", callback_data=f"review:rate:{vocab_id}:5"),
            ]
        ]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        
    elif data.startswith("review:rate:"):
        parts = data.split(":")
        vocab_id = int(parts[2])
        rating = int(parts[3])
        
        vocab_manager.process_review(user_id, vocab_id, rating)
        await query.answer("已记录")
        
        # Next word
        due_words = vocab_manager.get_due_words(user_id)
        if not due_words:
            await query.edit_message_text("🎉 复习完成！")
        else:
            word_data = due_words[0]
            vocab_id = word_data[0]
            word = word_data[1]
            phonetic = word_data[2]
            
            msg = f"📝 **复习**\n\n**{word}**\n{phonetic}\n\n(思考一下含义...)"
            keyboard = [[InlineKeyboardButton("显示答案", callback_data=f"review:show:{vocab_id}")]]
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
