import json
import vocab_manager
import ai_service
import database as db
import telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

async def daily_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """获取今日学习词汇 (支持自定义数量)
    
    用法：/daily [数量]
    例如：/daily 10
    
    调用 vocab_manager 生成新词，并以 Markdown 列表形式返回。
    """
    user_id = update.effective_user.id
    count = 5
    if context.args:
        try:
            count = int(context.args[0])
            if count < 1: count = 1
            if count > 20: count = 20 # Limit to avoid timeouts
        except ValueError:
            pass

    await update.message.reply_text(f"正在为你生成 {count} 个今日词汇，请稍候...")
    try:
        words = await vocab_manager.generate_daily_task(user_id, count=count)
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

async def plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """获取/生成 7 日学习计划"""
    user_id = update.effective_user.id
    
    # Try to get existing plan
    plan_record = db.get_user_plan(user_id)
    # If plan exists and is recent (< 24 hours), show it? Or always regenerate if user asks?
    # User requirement: "/plan/week 接口可实时刷新" -> implies generation on demand or check.
    # Let's check if user explicitly asked for refresh or just view.
    # Since command is simple /plan, let's regenerate if old (>1 day) or not exists.
    
    need_refresh = True
    if plan_record:
        plan_json, updated_at = plan_record
        # Check time... simplified logic: always refresh for now as it's an AI feature
        # Or better, show existing and offer "Refresh" button.
        pass

    await update.message.reply_text("正在为你生成/刷新 7 日学习计划...")
    try:
        plan = await ai_service.generate_learning_plan(user_id)
        if plan:
            db.save_user_plan(user_id, json.dumps(plan))
            
            # Format output
            msg = "📅 **7 日学习计划**\n\n"
            if "days" in plan:
                for day in plan["days"]:
                    msg += f"**Day {day.get('day')}**\n"
                    msg += f"• 新词: {day.get('new_words')} | 复习: {day.get('review')}\n"
                    msg += f"• 预计: {day.get('minutes')}分钟\n"
                    msg += f"• 重点: {day.get('focus')}\n\n"
            else:
                msg = str(plan)
                
            await update.message.reply_text(msg, parse_mode="Markdown")
        else:
            await update.message.reply_text("生成计划失败，AI 未返回有效格式。")
    except Exception as e:
        await update.message.reply_text(f"计划生成出错: {e}")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看详细单词统计"""
    user_id = update.effective_user.id
    total, items = db.get_user_word_stats(user_id, limit=10)
    
    msg = f"📊 **单词统计 (Total: {total})**\n\n"
    if not items:
        msg += "暂无学习记录。"
    else:
        for word, last_review, review_count, mastery in items:
            # last_review might be a string or datetime object depending on sqlite adapter
            # assuming string for simplicity in display or let's slice it
            last_date = str(last_review)[:10]
            msg += f"• **{word}**: 熟练度 {mastery:.1f} | 复习 {review_count}次 | 上次 {last_date}\n"
            
    await update.message.reply_text(msg, parse_mode="Markdown")

async def words_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看历史单词列表"""
    user_id = update.effective_user.id
    # Default page 1
    page = 1
    if context.args:
        try:
            page = int(context.args[0])
            if page < 1: page = 1
        except ValueError:
            pass
            
    await _show_words_page(update, user_id, page)

async def _show_words_page(update, user_id, page):
    limit = 20
    offset = (page - 1) * limit
    total, items = db.get_user_word_stats(user_id, offset=offset, limit=limit)
    
    total_pages = (total + limit - 1) // limit
    if total_pages == 0: total_pages = 1
    if page > total_pages: page = total_pages
    
    msg = f"📚 **历史单词本 (第 {page}/{total_pages} 页)**\nTotal: {total}\n\n"
    if not items:
        msg += "本页无数据。"
    else:
        for word, last_review, review_count, mastery in items:
            last_date = str(last_review)[:10] if last_review else "New"
            msg += f"• **{word}**: Lv.{mastery:.1f} ({last_date})\n"
            
    # Pagination Buttons
    buttons = []
    if page > 1:
        buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"words_page:{page-1}"))
    if page < total_pages:
        buttons.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"words_page:{page+1}"))
    
    keyboard = InlineKeyboardMarkup([buttons]) if buttons else None
    
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=keyboard, parse_mode="Markdown")
    else:
        await update.message.reply_text(msg, reply_markup=keyboard, parse_mode="Markdown")

async def import_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/import 智能提取重点词汇
    
    用法：
    1. /import <text>
    2. Reply to a message with /import
    
    调用 AI 提取难词，并以按钮形式展示供用户添加。
    """
    text = ""
    if context.args:
        text = " ".join(context.args)
    elif update.message.reply_to_message and update.message.reply_to_message.text:
        text = update.message.reply_to_message.text
    else:
        await update.message.reply_text("请在命令后输入文本，或回复一条消息使用 /import")
        return
        
    user_id = update.effective_user.id
    await update.message.reply_text("正在分析并提取重点词汇...")
    
    try:
        # Re-use extract_difficult_words from ai_service
        # But we don't want to auto-add to DB yet (vocab_manager.process_text_for_difficult_words does add)
        # So we call ai_service directly
        words_data, _ = await ai_service.extract_difficult_words(text)
        
        if not words_data:
            await update.message.reply_text("未提取到重点词汇。")
            return
            
        # Create buttons for extracted words
        # words_data is list of dict: {'word': '...', 'phonetic': '...', 'definition': '...', 'difficulty': ...}
        
        buttons = []
        row = []
        for w_obj in words_data:
            w = w_obj['word']
            row.append(InlineKeyboardButton(w, callback_data=f"add_vocab:{w}"))
            if len(row) == 2: # 2 buttons per row for longer words potentially
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
            
        await update.message.reply_text(
            f"🔍 **已提取 {len(words_data)} 个重点词汇**：\n点击下方按钮添加至生词本。",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="Markdown"
        )
        
    except Exception as e:
        await update.message.reply_text(f"提取失败: {e}")

async def review_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """开始复习生词
    
    获取到期单词，显示第一个单词（正面），并提供“显示答案”按钮。
    支持参数 /review [order] (asc/desc) - though logic is mostly fixed by priority
    """
    user_id = update.effective_user.id
    
    order = 'asc'
    if context.args and context.args[0].lower() == 'desc':
        order = 'desc'
        
    due_words = vocab_manager.get_due_words(user_id, order=order)
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
    
    # 先快速 ACK，避免后续耗时或多次 answer 导致的 BadRequest
    try:
        await query.answer()
    except Exception:
        pass
    
    if data.startswith("add_vocab:"):
        word = data.split(":", 1)[1]
        try:
            await vocab_manager.add_word(user_id, word)
            # 不再移除键盘，仅弹出提示
            # await query.edit_message_reply_markup(reply_markup=None)
        except Exception as e:
            # 避免重复 answer 导致 BadRequest
            try:
                await query.edit_message_text(f"添加失败：{e}")
            except Exception:
                pass
            
    elif data == "close_keyboard":
        # 关闭键盘
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except telegram.error.BadRequest:
            # 回退方案：直接重发相同文本，不带键盘
            try:
                original = (query.message.text or "").strip()
                if original:
                    await query.edit_message_text(original)
            except Exception:
                pass
            
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
            try: await query.edit_message_text("🎉 复习完成！")
            except telegram.error.BadRequest: pass
        else:
            word_data = due_words[0]
            vocab_id = word_data[0]
            word = word_data[1]
            phonetic = word_data[2]
            
            msg = f"📝 **复习**\n\n**{word}**\n{phonetic}\n\n(思考一下含义...)"
            keyboard = [[InlineKeyboardButton("显示答案", callback_data=f"review:show:{vocab_id}")]]
            try: await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            except telegram.error.BadRequest: pass
                
    elif data.startswith("words_page:"):
        page = int(data.split(":")[1])
        await _show_words_page(update, user_id, page)
