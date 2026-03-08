from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# 为保持与现有逻辑一致，这里使用与 main.py 相同的默认值
DEFAULT_SRC = "auto"
DEFAULT_TGT = "zh"
DEFAULT_MODE = "bing"
DEFAULT_COUNT = True
DEFAULT_AUTO_CUT = False

ENGINES = ["bing", "google", "deepseek"]
ENGINE_NAMES = {
    "bing": "必应",
    "google": "谷歌",
    "deepseek": "DeepSeek"
}

async def setlang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """设置目标语言：/setlang zh 或 /setlang en；默认 zh"""
    lang = context.args[0] if context.args else "zh"
    context.user_data["translate_tgt"] = lang
    await update.message.reply_text(f"已设置目标语言为：{lang}（推荐使用 /settings）")

async def setmode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """设置翻译引擎，仅支持 google 或 bing"""
    m = context.args[0].lower() if context.args else "bing"
    if m not in ENGINES:
        await update.message.reply_text(f"仅支持：{', '.join(ENGINES)}")
        return
    context.user_data["translate_mode"] = m
    await update.message.reply_text(f"已设置翻译引擎为：{m}")

async def setcount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """设置是否显示耗时：true/on/1/开/开启 为真"""
    val = True
    if context.args:
        a = context.args[0].lower()
        val = a in ("1", "true", "on", "yes", "y", "开", "开启")
    context.user_data["translate_count"] = val
    await update.message.reply_text(f"已{'开启' if val else '关闭'}计时")

async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """打开设置面板"""
    if "translate_tgt" not in context.user_data and "translate_lang" in context.user_data:
        context.user_data["translate_tgt"] = context.user_data.get("translate_lang", DEFAULT_TGT)
    text = _settings_text(context)
    keyboard = _get_settings_keyboard(context)
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

def _settings_text(context):
    src = context.user_data.get("translate_src", DEFAULT_SRC)
    tgt = context.user_data.get("translate_tgt", DEFAULT_TGT)
    engine = context.user_data.get("translate_mode", DEFAULT_MODE)
    show_time = context.user_data.get("translate_count", DEFAULT_COUNT)
    auto_cut = context.user_data.get("auto_cut", DEFAULT_AUTO_CUT)
    
    return (
        f"当前设置：\n"
        f"- 源语言: {src}\n"
        f"- 目标语言: {tgt}\n"
        f"- 引擎: {engine}\n"
        f"- 计时: {'开' if show_time else '关'}\n"
        f"- 自动切词: {'开' if auto_cut else '关'}\n\n"
        "点击下方按钮修改。"
    )

def _get_settings_keyboard(context):
    engine = context.user_data.get("translate_mode", DEFAULT_MODE)
    engine_name = ENGINE_NAMES.get(engine, engine)
    auto_cut = context.user_data.get("auto_cut", DEFAULT_AUTO_CUT)
    
    return [
        [InlineKeyboardButton("源: auto", callback_data="set_src:auto"),
         InlineKeyboardButton("源: en", callback_data="set_src:en"),
         InlineKeyboardButton("源: zh", callback_data="set_src:zh")],
        [InlineKeyboardButton("目标: en", callback_data="set_tgt:en"),
         InlineKeyboardButton("目标: zh", callback_data="set_tgt:zh")],
        [InlineKeyboardButton(f"引擎: {engine_name} (点击切换)", callback_data="toggle_engine")],
        [
            InlineKeyboardButton(f"回应计时: {'开' if context.user_data.get('translate_count', DEFAULT_COUNT) else '关'}", callback_data="toggle_count"),
            InlineKeyboardButton(f"自动切词: {'开' if auto_cut else '关'}", callback_data="toggle_cut")
        ],
    ]

async def on_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理设置面板按钮"""
    query = update.callback_query
    data = (query.data or "")
    if data.startswith("set_src:"):
        context.user_data["translate_src"] = data.split(":", 1)[1]
    elif data.startswith("set_tgt:"):
        context.user_data["translate_tgt"] = data.split(":", 1)[1]
    elif data.startswith("toggle_engine"):
        # Cycle engines
        current_engine = context.user_data.get("translate_mode", DEFAULT_MODE)
        try:
            idx = ENGINES.index(current_engine)
            next_idx = (idx + 1) % len(ENGINES)
        except ValueError:
            next_idx = 0
        new_engine = ENGINES[next_idx]
        context.user_data["translate_mode"] = new_engine
        # No answer text needed, button updates
        
    elif data.startswith("set_engine:"): # Keep backward compatibility if needed, or remove
        context.user_data["translate_mode"] = data.split(":", 1)[1]
        
    elif data.startswith("toggle_count"):
        cur = context.user_data.get("translate_count", DEFAULT_COUNT)
        context.user_data["translate_count"] = not cur
        
    elif data.startswith("toggle_cut"):
        cur = context.user_data.get("auto_cut", DEFAULT_AUTO_CUT)
        context.user_data["auto_cut"] = not cur
        
    await query.answer()
    
    try:
        await query.edit_message_text(
            _settings_text(context), 
            reply_markup=InlineKeyboardMarkup(_get_settings_keyboard(context))
        )
    except Exception:
        pass
