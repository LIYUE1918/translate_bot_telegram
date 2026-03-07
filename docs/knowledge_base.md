# 项目开发知识点归类

## 1. 技术栈与环境

*   **编程语言**: Python 3.10+
*   **核心框架**: `python-telegram-bot` (异步版本)
*   **异步编程**: `asyncio`, `aiohttp`
*   **数据库**: SQLite3 (原生支持)
*   **AI 服务**: 302.AI (兼容 OpenAI API 格式)
*   **环境管理**: `python-dotenv` (管理 .env 环境变量)
*   **翻译库**: `translators` (集成 Google, Bing 等多种翻译接口)

## 2. 项目架构 (MVC 模式)

虽然项目采用模块化函数式编程，但逻辑上遵循 MVC 分层：

*   **Controller (View/Interaction)**: `main.py`
    *   负责处理 Telegram 的 Update (消息、命令、按钮回调)。
    *   解析用户输入，调用 Service 层逻辑。
    *   将结果渲染为文本或按钮反馈给用户。
*   **Service (Business Logic)**: 
    *   `ai_service.py`: 封装 AI 接口调用、限流、缓存、Prompt 工程。
    *   `vocab_manager.py`: 处理词汇学习的核心业务（生词生成、复习算法）。
*   **Model (Data Access)**: `database.py`
    *   封装 SQL 操作。
    *   管理 User, Vocabulary, LearningRecord 等数据实体。

## 3. 核心概念与逻辑

### 3.1 消息处理管道 (Pipeline)
1.  **Update**: 接收 Telegram 推送的事件。
2.  **Filter**: 区分 Command (如 `/start`) 和 Text 消息。
3.  **Handler**: 
    *   `CommandHandler`: 处理 `/command`。
    *   `MessageHandler`: 处理普通文本（触发翻译）。
    *   `CallbackQueryHandler`: 处理内联键盘（Inline Keyboard）点击事件。

### 3.2 记忆算法 (Spaced Repetition)
*   项目实现了一个简化的 **间隔重复** 算法（类似 SM2/Anki）。
*   逻辑位置：`vocab_manager.py` -> `process_review`。
*   核心参数：
    *   `last_review`: 上次复习时间。
    *   `next_review`: 下次复习时间。
    *   `mastery_level`: 掌握程度。
    *   `quality`: 用户自评的记忆质量 (1-5)。

### 3.3 异步并发
*   使用 `async/await` 确保 Bot 在等待 IO（数据库查询、AI 请求、网络翻译）时不会阻塞主线程。
*   `Application.run_polling()` 启动事件循环。

## 4. 数据库设计 (ER 模型)

*   **users**: 存储用户 ID、用户名、偏好设置（JSON）。
*   **vocabulary**: 存储单词库（去重），包含单词、音标、释义。
*   **learning_records**: 关联表（User <-> Vocabulary），存储个人的学习进度（复习时间、状态）。
*   **ai_logs**: 审计日志，记录 AI 调用情况。

## 5. 配置管理

*   所有敏感信息（API Keys, Tokens）通过环境变量注入。
*   `.env` 文件模板：
    ```ini
    BOT_TOKEN=your_telegram_bot_token
    AI_API_KEY=your_302ai_key
    ```
