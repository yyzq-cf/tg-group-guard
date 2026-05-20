# 🤖 Telegram Group Guard Bot

一个轻量级的 Telegram 群组管理机器人，支持入群验证、垃圾信息拦截、违禁词在线管理和管理员命令。

## ✨ 功能特性

- **🛡️ 入群验证** — 新成员入群时自动发送数学验证题（私聊），答对才能解除禁言
- **🚫 垃圾信息拦截** — 自动检测并删除广告、引流、博彩、色情等违规内容
- **📊 管理统计** — 查看验证通过人数、违规拦截次数、验证超时次数
- **📝 违禁词在线管理** — Web 后台实时添加/删除/启用/禁用违禁词，即时生效无需重启
- **🔒 防暴力破解** — Web 后台连续 5 次密码错误自动锁定 IP 15 分钟，支持手动解锁
- **💬 入群欢迎语** — 验证通过后自动在群内发送欢迎消息，支持 Web 后台自定义
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
BOT_TOKEN=***
ADMIN_IDS=你的Telegram数字ID（多个用逗号分隔）
VERIFY_TIMEOUT=60
MAX_WARNINGS=3
MUTE_DURATION=300
DB_PATH=/data/bot.db
ADMIN_PASSWORD=***
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
| **🔒 安全日志** | 查看登录失败记录，手动解锁被锁定的 IP |
| **⚙️ 系统设置** | 修改配置参数、管理密码、入群欢迎语 |

### 🔐 默认登录
- 地址：`http://服务器IP:8080`
- 密码：`.env` 中设置的 `ADMIN_PASSWORD`（默认 `admin`）

> ⚠️ **建议立即修改默认密码**，并妥善保管。连续 5 次输入错误将自动锁定该 IP 15 分钟。

## 💬 入群欢迎语

验证通过后，机器人会自动在群组内发送欢迎消息。

### 自定义欢迎语

进入 Web 后台 **系统设置** 页面，编辑"入群欢迎语"：

- 支持 HTML 格式
- 可插入变量自动替换：
  - `{mention}` — @用户名（可点击跳转）
  - `{name}` — 用户全名
  - `{first_name}` — 用户名字
  - `{username}` — @username（无用户名则显示全名）
  - `{user_id}` — 用户数字 ID

### 示例欢迎语

```
🎉 欢迎 {mention} 加入群组！

✅ 验证已通过，你现在可以正常发言了。
请遵守群规，文明交流~
```

> 留空则不发送欢迎语。

## 🔒 防暴力破解

Web 后台内置了防暴力破解机制：

- **失败计数**：记录每个 IP 的登录失败次数
- **自动锁定**：连续 5 次密码错误后，该 IP 将被锁定 15 分钟
- **倒计时提示**：锁定页面显示剩余解锁时间的倒计时
- **手动解锁**：管理员可在 **安全日志** 页面手动解锁任意 IP
- **IP 识别**：支持 `X-Forwarded-For` 和 `X-Real-Ip` 头，适配反向代理环境

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
│   ├── database.py          # SQLite 数据库（含违禁词表、登录记录表、配置表）
│   ├── handlers/
│   │   ├── __init__.py
│   │   ├── join_request.py  # 入群验证逻辑 + 欢迎语发送
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
│           ├── keywords.html    # 违禁词管理页面
│           ├── security.html    # 安全日志页面
│           └── settings.html    # 系统设置（含欢迎语编辑）
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
| `ADMIN_PASSWORD` | `admin` | Web 后台登录密码 |

## 📄 License

MIT License
