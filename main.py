"""Telegram 翻译与词汇学习机器人
本模块作为应用的入口（Entry Point）：
- 负责初始化 Application
- 注册来自 handlers 包的各种处理器
- 启动长轮询

业务逻辑已拆分至 handlers/ 目录下的子模块中。
"""
import logging
import os
import asyncio
from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler
from telegram import BotCommand
import database as db
from logger_config import setup_logger

# 初始化 Logger
logger = setup_logger("Main")

# 导入拆分后的处理器
from handlers.basic_handlers import start, echo, cut_command
from handlers.settings_handlers import (
    settings, 
    setlang, 
    setmode, 
    setcount, 
    on_settings_callback
)
from handlers.learning_handlers import (
    daily_command, 
    review_command, 
    summary_command, 
    plan_command,
    stats_command,
    words_command,
    import_command,
    on_vocab_callback,
    detail_command,
    clean_command
)
from handlers.basic_handlers import chat_command

# Initialize Database
db.init_db()

# 从 .env 或系统环境变量加载配置
load_dotenv()
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

async def main():
    """应用主入口
    
    1. 构建 Application 并注册所有处理器
    2. 初始化并启动 Bot，与 Telegram 建立连接
    3. 启动长轮询保持常驻
    """
    # 构建应用容器并注入 Token
    app = Application.builder().token(TOKEN).build()
    
    # 注册基础命令
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("cut", cut_command))
    app.add_handler(CommandHandler("chat", chat_command))
    
    # 注册设置相关命令与回调
    app.add_handler(CommandHandler("settings", settings))
    app.add_handler(CommandHandler("setlang", setlang))
    app.add_handler(CommandHandler("setmode", setmode))
    app.add_handler(CommandHandler("setcount", setcount))
    app.add_handler(CallbackQueryHandler(on_settings_callback, pattern="^(set_src|set_tgt|set_engine|toggle_engine|toggle_count|toggle_cut)"))
    
    # 注册学习相关命令与回调
    app.add_handler(CommandHandler("daily", daily_command))
    app.add_handler(CommandHandler("review", review_command))
    app.add_handler(CommandHandler("summary", summary_command))
    app.add_handler(CommandHandler("plan", plan_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("words", words_command))
    app.add_handler(CommandHandler("import", import_command))
    app.add_handler(CommandHandler("detail", detail_command))
    app.add_handler(CommandHandler("clean", clean_command))
    app.add_handler(CallbackQueryHandler(on_vocab_callback, pattern="^(add_vocab|close_keyboard|review:|words_page:|corr:|ipa:)"))
    
    # 注册文本消息处理器（最后注册，避免拦截命令）
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    
    # 初始化与启动
    await app.initialize()
    
    # 设置 Bot 菜单
    commands = [
        BotCommand("start", "开始使用 / 帮助"),
        BotCommand("daily", "获取今日学习词汇"),
        BotCommand("review", "开始复习生词"),
        BotCommand("words", "查看单词本与统计"),
        BotCommand("plan", "查看学习计划"),
        BotCommand("summary", "查看学习进度总结"),
        BotCommand("detail", "查看单词详情"),
        BotCommand("cut", "切分文本为按钮"),
        BotCommand("import", "智能提取重点词汇"),
        BotCommand("clean", "清理无效或旧词汇"),
        BotCommand("chat", "询问 AI 助手"),
        BotCommand("settings", "打开设置面板"),
    ]
    await app.bot.set_my_commands(commands)
    
    await app.start()
    logger.info("Bot started. Press Ctrl+C to stop.")
    
    # 启动长轮询
    await app.updater.start_polling()
    # 阻塞主协程
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
