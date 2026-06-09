# 🤖 Telegram Group Guard Bot

一个轻量级的 Telegram 群组管理机器人，支持入群验证、垃圾信息拦截、违禁词在线管理和管理员命令。

## ✨ 功能特性

- **🛡️ 入群验证** — 新成员入群时自动发送数学验证题（私聊），答对才能解除禁言
- **🚫 垃圾信息拦截** — 自动检测并删除广告、引流、博彩、色情等违规内容
- **📊 管理统计** — 查看验证通过人数、违规拦截次数、验证超时次数
- **📝 违禁词在线管理** — Web 后台实时添加/删除/启用/禁用违禁词，即时生效无需重启
- **⚡ 轻量部署** — 基于 Python + SQLite，docker单容器即可运行
- **✏️ 关键词自动回复** — 可以自定义设置关键词，自动回复群消息

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
ADMIN_PASSWORD=你的管理密码
```

> 获取你的 Telegram 数字 ID：[@userinfobot](https://t.me/userinfobot)

### 3. Docker 部署
新建一个目录,进入此目录
```bash
mkdir tg-group-guard ; cd tg-group-guard
```
新建docker-compose.yml文件
```
vim docker-compose.yml
```
```bash
services:  # 定义服务
  bot:  # 服务名称为 bot
    image: ywsj/tg-group-guard:latest  # 使用你上传到 Docker Hub 的镜像
    container_name: tg-group-guard  # 容器名称
    restart: always  # 容器重启策略，总是重启
    ports:  # 映射端口
      - "8080:8080"  # 将宿主机的 8080 端口映射到容器的 8080 端口
    volumes:  # 挂载数据卷
      - ./data:/data  # 将当前目录下的 data 文件夹挂载到容器的 /data
    environment:  # 定义环境变量
      BOT_TOKEN: "你的Bot Token"  # 机器人 Token,不填会报错
      ADMIN_IDS: "你的电报数字ID"  # 管理员 Telegram ID，可以用逗号分隔多个，不填会报错
      VERIFY_TIMEOUT: "60"  # 新成员验证超时时间，单位秒
      MAX_WARNINGS: "3"  # 最大警告次数
      MUTE_DURATION: "300"  # 警告后禁言时长，单位秒
      DB_PATH: "/data/bot.db"  # 数据库存放路径
      ADMIN_PASSWORD: "admin"  # 管理员密码
```

以上为使用我构建的镜像

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
  -p 8080:8080 \
  tg-group-guard
```

### 4. 设置机器人权限

将机器人加入群组，并设置为**管理员**，权限需要：
- 删除消息
- 限制用户
- 封禁用户
- 通过邀请链接加入的用户（用于读取入群事件）

## 🌐 Web 管理后台

部署后访问：`http://服务器IP:8080`

| 页面 | 功能 |
|------|------|
| **📊 仪表盘** | 数据概览、违规趋势、高频违规用户 |
| **🚫 违规记录** | 分页查看所有被拦截的消息，支持搜索 |
| **📝 违禁词管理** | 在线添加/删除/启用/禁用违禁词，即时生效 |
| **👤 用户列表** | 查看所有群成员，显示验证状态、警告次数 |
| **⚙️ 系统设置** | 修改配置参数、管理密码 |

### 🔐 默认登录
- 地址：`http://服务器IP:8080`
- 密码：`.env` 中设置的 `ADMIN_PASSWORD`（默认 `admin`）

## 📝 违禁词管理

### 在线管理

进入 Web 后台 **违禁词管理** 页面：

- **➕ 添加**：输入关键词 → 点击添加 → 立即生效，无需重启
- **🔴 禁用**：临时关闭某个词的拦截，保留记录
- **🟢 启用**：重新开启拦截
- **🗑️ 删除**：彻底移除该违禁词
- **📈 命中统计**：自动统计每个词被触发的次数

### 即时生效原理

Bot 的消息拦截逻辑每次都会**实时查询数据库**获取启用的违禁词列表，Web 上修改后下一次消息检测就会立刻生效。

### 默认违禁词

系统初始化时自动导入以下默认违禁词：
- 中文：博彩、彩票、投注、兼职、日赚、月入、刷单、加微信、加QQ、推广、引流、代理、包赚、稳赚、暴利、杀猪盘、资金盘、空投、薅羊毛...
- 英文：casino、bet、gambling、earn money、make money fast、porn、sex...

## 🛠️ 拦截规则

当前支持拦截的内容类型：

- **关键词**：基于数据库动态管理的违禁词列表
- **联系方式**：微信号、QQ号、手机号
- **链接**：短链接（bit.ly、t.cn 等）、过多链接（≥3条）
- **英文关键词**：casino、gambling、porn、dating site 等

违规处理流程：
1. 删除违规消息
2. 记录违规次数
3. 达到 `MAX_WARNINGS` 次后永久封禁
4. 否则禁言 `MUTE_DURATION` 秒

## 📝 管理员命令

| 命令 | 说明 |
|------|------|
| `/ban [用户ID]` 或 回复消息 | 封禁用户 |
| `/unban [用户ID]` | 解封用户 |
| `/stats` | 查看群组统计 |

## 📁 项目结构

```
.
├── app/
│   ├── __init__.py
│   ├── __main__.py
│   ├── main.py              # 入口（启动 Bot + Web 后台）
│   ├── config.py            # 配置读取
│   ├── database.py          # SQLite 数据库（含违禁词表）
│   ├── handlers/
│   │   ├── __init__.py
│   │   ├── join_request.py  # 入群验证逻辑
│   │   ├── group_messages.py # 消息拦截逻辑（动态读取违禁词）
│   │   └── admin_commands.py # 管理员命令
│   └── web/
│       ├── server.py        # Flask Web 服务
│       └── templates/       # HTML 模板
│           ├── base.html
│           ├── login.html
│           ├── dashboard.html
│           ├── violations.html
│           ├── users.html
│           ├── keywords.html  # 违禁词管理页面
│           └── settings.html
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── README.md
```

## 🧰 技术栈与依赖

本项目基于以下开源库构建：

| 依赖 | 版本 | 说明 | 许可证 |
|------|------|------|--------|
| [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) | ≥20.0 | Telegram Bot API 的 Python 封装，处理消息、入群事件与群管操作 | BSD-3-Clause |
| [Flask](https://github.com/pallets/flask) | ≥2.3.0 | Web 管理后台框架 | BSD-3-Clause |

数据库使用内置的 **SQLite**，无需额外安装。

## ⚙️ 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `BOT_TOKEN` | — | **必填**，Bot Token |
| `ADMIN_IDS` | — | **必填**，管理员数字 ID，多个用逗号分隔 |
| `VERIFY_TIMEOUT` | `60` | 入群验证超时时间（秒） |
| `MAX_WARNINGS` | `3` | 最大警告次数，超过则封禁 |
| `MUTE_DURATION` | `300` | 违规禁言时长（秒） |
| `DB_PATH` | `/data/bot.db` | SQLite 数据库路径 |
| `ADMIN_PASSWORD` | `admin` | Web 后台登录密码 |

## 📄 License

MIT License
