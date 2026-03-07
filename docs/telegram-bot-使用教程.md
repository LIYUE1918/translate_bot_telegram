# Telegram Bot 使用教程与示例（含菜单与回复）

本教程面向零基础上手 Telegram 机器人开发，提供可直接运行的示例代码，并包含「命令菜单」「回复键盘」「内联菜单」等常见交互方式。

适合场景：
- 需要快速搭建一个可用的 Telegram Bot
- 希望添加命令菜单、按钮菜单，接收并回复消息
- 了解轮询与 Webhook 部署差异

---

## 前置条件
- 一个 Telegram 账号（手机能接收验证码）
- 能访问 Telegram（必要时配置网络代理）
- 基本的命令行与编程环境（本文以 Python 示例为主）

---

## 获取机器人 Token（BotFather）
1. 在 Telegram 搜索 `@BotFather` 并开始聊天。
2. 发送 `/newbot`，按照提示为你的机器人设置名称与用户名（用户名须以 `bot` 结尾）。
3. 创建成功后，BotFather 会返回一段形如 `123456789:ABC-DEF...` 的 Token。请妥善保管。
4. 可选：通过 `/setdescription`、`/setabouttext`、`/setuserpic` 等完善资料。

---

## 技术选型与安装
本文示例使用 Python 的 `python-telegram-bot`（v21+ API）。

安装：

```bash
python -m pip install "python-telegram-bot>=21.0"
```

如果需要代理（例如在中国大陆），可以为请求设置 `httpx` 代理或在系统层配置网络代理。

---

## 最小可用示例：启动与基础回复
功能：
- 命令 `/start`：欢迎语
- 回声（Echo）：把用户说的话原样返回

将下面代码保存为 `bot_basic.py`，把 `YOUR_BOT_TOKEN` 替换成你的 Token：

```python
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

TOKEN = "YOUR_BOT_TOKEN"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "你好！我是你的 Telegram 机器人。\n发送任意消息，我会回声回复。"
    )

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    await update.message.reply_text(f"你说：{text}")

async def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    await app.initialize()
    await app.start()
    print("Bot started. Press Ctrl+C to stop.")
    await app.updater.start_polling()  # 轮询模式
    await asyncio.Event().wait()       # 保持运行

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped.")
```

运行：

```bash
python bot_basic.py
```

---

## 设置命令菜单（Bot Commands）
Telegram 客户端会在输入框的「菜单」中展示机器人支持的命令。可在启动时设置：

```python
from telegram import BotCommand

async def set_commands(app):
    commands = [
        BotCommand("start", "开始使用"),
        BotCommand("help", "查看帮助"),
        BotCommand("menu", "打开菜单示例"),
    ]
    await app.bot.set_my_commands(commands)

# 在 main() 构建 app 后调用：
# await set_commands(app)
```

---

## 回复键盘菜单（ReplyKeyboardMarkup）
回复键盘会替换用户输入区的键盘，适合快速选择。示例：

```python
from telegram import ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import CommandHandler, MessageHandler, filters

reply_keyboard = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📊 状态"), KeyboardButton("⚙️ 设置")],
        [KeyboardButton("❓ 帮助")]
    ],
    resize_keyboard=True,
    one_time_keyboard=False
)

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("请选择一个功能：", reply_markup=reply_keyboard)

async def handle_menu_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = (update.message.text or "").strip()
    if choice == "📊 状态":
        await update.message.reply_text("当前状态：一切正常 ✅")
    elif choice == "⚙️ 设置":
        await update.message.reply_text("进入设置：请发送你想修改的选项名称。")
    elif choice == "❓ 帮助":
        await update.message.reply_text("帮助：/start /menu 等。")
    else:
        await update.message.reply_text("未识别的选项，请从菜单选择。")

# 在 main() 中追加：
# app.add_handler(CommandHandler("menu", menu))
# app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_choice))
```

注意：如果你既想保留「回声」又想处理菜单选择，可以在 `handle_menu_choice` 中先判断是否属于菜单项，否则交给其它逻辑；也可以用更精细的状态机（见下节）。

---

## 内联按钮菜单（InlineKeyboardMarkup + 回调）
内联按钮会作为消息的一部分显示，点击按钮不会发送文本到聊天，而是触发回调数据（callback_data）。

```python
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CallbackQueryHandler

async def inline_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("查看状态", callback_data="status:view")],
        [
            InlineKeyboardButton("开启", callback_data="setting:on"),
            InlineKeyboardButton("关闭", callback_data="setting:off"),
        ],
    ])
    await update.message.reply_text("内联菜单：", reply_markup=keyboard)

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # 必须先答复以移除「加载中」
    data = query.data or ""
    if data == "status:view":
        await query.edit_message_text("状态：运行中 ✅")
    elif data == "setting:on":
        await query.edit_message_text("设置已开启 ✅")
    elif data == "setting:off":
        await query.edit_message_text("设置已关闭 ❌")
    else:
        await query.edit_message_text("未知操作")

# 在 main() 中追加：
# app.add_handler(CommandHandler("inline", inline_menu))
# app.add_handler(CallbackQueryHandler(on_callback))
```

---

## 基于状态的简单对话（ConversationHandler）
当交互需要多步输入时，可使用对话处理器管理状态（如收集用户名和邮箱）。

```python
from telegram.ext import ConversationHandler

ASK_NAME, ASK_EMAIL = range(2)

async def start_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("请输入你的姓名：")
    return ASK_NAME

async def ask_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text("好的，接下来请输入你的邮箱：")
    return ASK_EMAIL

async def finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = context.user_data.get("name", "未知")
    email = update.message.text.strip()
    await update.message.reply_text(f"提交成功！\n姓名：{name}\n邮箱：{email}")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("已取消流程。")
    return ConversationHandler.END

wizard = ConversationHandler(
    entry_points=[CommandHandler("wizard", start_wizard)],
    states={
        ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_email)],
        ASK_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, finish)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)

# 在 main() 中注册：
# app.add_handler(wizard)
```

---

## 轮询与 Webhook
- 轮询（Polling）：本地开发最简单，机器人主动去拉取更新。示例代码中使用 `app.updater.start_polling()`。
- Webhook：更适合生产部署，Telegram 主动推送更新到你的 HTTPS 端点，延迟更低、资源占用更小。需要公网可达的 HTTPS 服务与证书。

切换到 Webhook（示例）：

```python
await app.start()
await app.bot.set_webhook("https://your.domain.com/tg/webhook")
# 使用你框架（如 FastAPI/Flask 等）接收 POST 并交给 app.process_update(...)
```

---

## 常见问题
- 连接超时：检查网络是否可访问 Telegram；必要时配置系统代理或为 HTTP 客户端设置代理。
- 中文或表情乱码：确保文件保存为 UTF-8，并在终端使用支持 UTF-8 的字体。
- 长消息报错：Telegram 单条消息有长度限制，需拆分多条发送。
- 同时处理多种消息类型：组合 `filters`（例如 `filters.PHOTO`、`filters.VIDEO` 等）分别注册不同的 `MessageHandler`。

---

## 安全与最佳实践
- 不要把 Token 写死在仓库里。优先使用环境变量（如 `os.environ["BOT_TOKEN"]`）。
- 对回调与命令进行权限控制（例如仅允许管理员执行某些命令）。
- 对用户输入做校验与限流，防止滥用。
- 使用结构化日志记录关键事件，便于排查问题。

---

## 完整示例整合（骨架）
在一个文件中组合「启动、命令菜单、回复键盘、内联回调、回声」：

```python
import os
import asyncio
from telegram import Update, BotCommand, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("欢迎！输入 /menu 查看回复键盘，或 /inline 看内联按钮。")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("/start 开始\n/menu 回复键盘\n/inline 内联按钮")

async def setup_commands(app: Application):
    cmds = [
        BotCommand("start", "开始使用"),
        BotCommand("help", "查看帮助"),
        BotCommand("menu", "回复键盘菜单"),
        BotCommand("inline", "内联按钮菜单"),
    ]
    await app.bot.set_my_commands(cmds)

reply_keyboard = ReplyKeyboardMarkup(
    [[KeyboardButton("📊 状态"), KeyboardButton("⚙️ 设置")], [KeyboardButton("❓ 帮助")]],
    resize_keyboard=True
)

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("请选择：", reply_markup=reply_keyboard)

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text in ("📊 状态", "⚙️ 设置", "❓ 帮助"):
        if text == "📊 状态":
            await update.message.reply_text("状态：OK ✅")
        elif text == "⚙️ 设置":
            await update.message.reply_text("设置项示例：发送 1/2/3 进行选择。")
        else:
            await update.message.reply_text("帮助：/start /menu /inline。")
    else:
        await update.message.reply_text(f"回声：{text}")

async def inline_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("查看状态", callback_data="status:view")],
        [InlineKeyboardButton("开启", callback_data="setting:on"),
         InlineKeyboardButton("关闭", callback_data="setting:off")],
    ])
    await update.message.reply_text("内联菜单：", reply_markup=kb)

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data or ""
    if d == "status:view":
        await q.edit_message_text("状态：运行中 ✅")
    elif d == "setting:on":
        await q.edit_message_text("设置：已开启 ✅")
    elif d == "setting:off":
        await q.edit_message_text("设置：已关闭 ❌")
    else:
        await q.edit_message_text("未知操作")

async def main():
    app = Application.builder().token(TOKEN).build()
    await setup_commands(app)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("inline", inline_menu))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    await app.initialize()
    await app.start()
    print("Bot started. Ctrl+C 退出。")
    await app.updater.start_polling()
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("已退出。")
```

你现在已经拥有一个可用的 Telegram Bot，并掌握了命令菜单、回复键盘、内联按钮和基础消息处理。接下来可以按业务需要扩展指令、接入数据库或部署为 Webhook。

