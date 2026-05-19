# 🤖 Telegram Group Guard Bot

一个轻量级的 Telegram 群组管理机器人，支持入群验证、垃圾信息拦截和管理员命令。

## ✨ 功能特性

- **🛡️ 入群验证** — 新成员入群时自动发送数学验证题（私聊），答对才能解除禁言
- **🚫 垃圾信息拦截** — 自动检测并删除广告、引流、博彩、色情等违规内容
- **📊 管理统计** — 查看验证通过人数、违规拦截次数、验证超时次数
- **⚡ 轻量部署** — 基于 Python + SQLite，单容器即可运行

## 🚀 快速开始

### 1. 获取 Bot Token

在 [@BotFather](https://t.me/BotFather) 创建机器人，获取 `BOT_TOKEN`。

### 2. 配置环境变量

复制示例配置并修改：

```bash
cp .env.example .env
```

编辑 `.env`：

```env
BOT_TOKEN=你的BotToken
ADMIN_IDS=你的Telegram数字ID（多个用逗号分隔）
VERIFY_TIMEOUT=60
MAX_WARNINGS=3
MUTE_DURATION=300
DB_PATH=/data/bot.db
```

> 获取你的 Telegram 数字 ID：[@userinfobot](https://t.me/userinfobot)

### 3. Docker 部署

```bash
docker-compose up -d
```

或手动构建：

```bash
docker build -t tg-group-guard .
docker run -d \
  --name tg-group-guard \
  --env-file .env \
  -v $(pwd)/data:/data \
  tg-group-guard
```

### 4. 设置机器人权限

将机器人加入群组，并设置为**管理员**，权限需要：
- 删除消息
- 限制用户
- 封禁用户
- 通过邀请链接加入的用户（用于读取入群事件）

## 📝 管理员命令

| 命令 | 说明 |
|------|------|
| `/ban [用户ID]` 或 回复消息 | 封禁用户 |
| `/unban [用户ID]` | 解封用户 |
| `/stats` | 查看群组统计 |

## 🛠️ 拦截规则

当前支持拦截的内容类型：

- **关键词**：博彩、彩票、投注、兼职、日赚、刷单、推广、引流、杀猪盘、资金盘等
- **联系方式**：微信号、QQ号、手机号
- **链接**：短链接（bit.ly、t.cn 等）、过多链接（≥3条）
- **英文关键词**：casino、gambling、porn、dating site 等

违规处理流程：
1. 删除违规消息
2. 记录违规次数
3. 达到 `MAX_WARNINGS` 次后永久封禁
4. 否则禁言 `MUTE_DURATION` 秒

## 📁 项目结构

```
.
├── app/
│   ├── __init__.py
│   ├── __main__.py
│   ├── main.py              # 入口
│   ├── config.py            # 配置读取
│   ├── database.py          # SQLite 数据库
│   └── handlers/
│       ├── __init__.py
│       ├── join_request.py  # 入群验证逻辑
│       ├── group_messages.py # 消息拦截逻辑
│       └── admin_commands.py # 管理员命令
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── README.md
```

## ⚙️ 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `BOT_TOKEN` | — | **必填**，Bot Token |
| `ADMIN_IDS` | — | **必填**，管理员数字 ID，多个用逗号分隔 |
| `VERIFY_TIMEOUT` | `60` | 入群验证超时时间（秒） |
| `MAX_WARNINGS` | `3` | 最大警告次数，超过则封禁 |
| `MUTE_DURATION` | `300` | 违规禁言时长（秒） |
| `DB_PATH` | `/data/bot.db` | SQLite 数据库路径 |

## 📄 License

MIT License
