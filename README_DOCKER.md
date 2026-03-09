# Docker 部署指南

## 前置要求
1. 安装 Docker 和 Docker Compose
2. 确保项目根目录下存在 `.env` 文件，并包含 `BOT_TOKEN` 和 `AI_API_KEY`
3. **重要**：确保根目录下存在 `vocab_learning.db` 文件（如果是全新部署，可以创建一个空文件，或者先运行一次本地代码生成数据库）

## 快速开始

1. **构建并启动**
   ```bash
   docker-compose up -d --build
   ```

2. **查看日志**
   ```bash
   docker-compose logs -f
   ```

3. **停止服务**
   ```bash
   docker-compose down
   ```

## 注意事项
- **数据持久化**：数据库文件 `vocab_learning.db` 和日志目录 `logs/` 已挂载到宿主机，重启容器数据不会丢失。
- **文件权限**：如果遇到权限问题，请检查宿主机文件的读写权限。
- **时区**：默认设置为 `Asia/Shanghai`。

## 故障排查
- 如果报错 `Is a directory: '/app/vocab_learning.db'`，说明宿主机缺少 `vocab_learning.db` 文件，Docker 自动创建了一个同名目录。请删除该目录并创建一个空文件，或从备份恢复数据库文件。
