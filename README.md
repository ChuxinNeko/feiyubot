# 飞鱼

基于 NoneBot2 的 QQ 陪伴机器人。它用 OneBot v11 收群消息，把人格提示词、长期记忆和较早对话摘要注入请求，再发给你自己配置的大模型 API，然后把回复发回原来的群。

功能对齐 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 里和「QQ 陪伴」直接相关的部分：OpenAI 兼容模型、多提供商失败转移、人格、自动上下文压缩、长期记忆、会话管理、WebUI、网页对话。实现是按 NoneBot2 新写的，不是 AstrBot 的源码拷贝。多平台适配、插件市场、MCP 沙箱和语音不在这个仓库里。

## 记忆为什么不会几句就断

- 每一条群消息和网页消息都写入 SQLite，重启后还在。
- 群里没 @ 它的话也会记下。下次被叫到时，这些话还在上下文里。
- 默认把最近 40 条原文放进模型请求。
- 再早的对话会压成摘要。模型压缩失败时，改用本地摘录，并保留开头和结尾。
- 每隔若干条用户消息更新一次长期记忆。句子里有「记住」会立刻写进去，不会被后来的摘要冲掉。
- 主模型超时或 5xx 时按优先级换下一家。

## 运行

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
python bot.py
```

浏览器打开 <http://127.0.0.1:8080/> 。`.env` 里的默认管理密码是 `feiyu-admin`，登录后请在「设置」里改掉。如果没设置密码，首次启动会把随机密码写到 `data/admin_password.txt`。

界面在 `frontend/`，用 Vite、React 和 shadcn/ui。仓库里已经带构建结果 `feiyubot/web/ui`。改完页面后重新构建：

```bash
cd frontend
npm install
npm run build
```

数据库在 `data/feiyu.sqlite`。

## 接 QQ

用 NapCat、Lagrange 或其他 OneBot v11 实现，反向 WebSocket 填：

`ws://<飞鱼地址>:8080/onebot/v11/ws`

令牌和飞鱼的 `ONEBOT_V11_ACCESS_TOKEN` 相同。也可以在 WebUI 的「连接 QQ」页写入 `data/runtime.env`，重启后生效。要让飞鱼主动连出去，在同一页展开正向 WebSocket。

机器人默认只在被 @、被回复，或收到 `/` 命令时开口，但其他群消息仍会记入该群的上下文。要每句都回，把唤醒改成「每句都回复」。

## 模型

在 WebUI「模型」里添加任何 OpenAI 兼容地址，例如 DeepSeek、Moonshot、通义、智谱、硅基流动、Ollama、LM Studio。可以加多条。优先级数字小的先用。

没有密钥时，可以先跑演示接口：

```bash
python scripts/mock_openai.py
```

然后添加 `http://127.0.0.1:8765/v1`，模型名随意。

## 命令

在群里或网页对话里：

- `/help` 说明
- `/ping` 确认进程还在
- `/memory` 查看长期记忆和摘要
- `/reset` 清空这段对话的上下文（人格和补充资料还在）
- `切换人格 名字`

## 测试

```bash
pytest
```

## Docker

```bash
docker compose up --build
```

数据在卷 `feiyu-data` 里，容器重启不会清空记忆。
