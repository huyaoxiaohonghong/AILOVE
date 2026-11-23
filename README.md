# AILOVE 全栈工程（网站管理端 + 微信小程序）

本项目是一个面向 AI 应用场景的 Monorepo 全栈基础工程，包含 **统一后端服务**、**网站管理端前端** 与 **微信原生小程序** 三个独立模块。

## 技术栈概览

| 模块 | 目录 | 核心技术 |
| --- | --- | --- |
| 统一后端服务 | [`backend/`](./backend) | FastAPI、SQLAlchemy 2.0 (Async + aiomysql)、Alembic、MySQL 8、Redis、LangChain (OpenAI / Anthropic 双协议适配，内置 DeepSeek)、RBAC 细粒度权限、纯 ASGI 审计日志、Redis 限流、PyJWT、bcrypt |
| 网站管理端 | [`admin-web/`](./admin-web) | Vue 3.5、Vite 6、TypeScript、Element Plus、Pinia、Vue Router 4、Axios |
| 微信小程序 | [`miniprogram/`](./miniprogram) | 微信原生开发（WXML / WXSS / JS / JSON）、自定义组件、统一请求与 `wx.login` 鉴权封装 |
| 本地基础设施 | [`docker-compose.yml`](./docker-compose.yml) | MySQL 8.0 + Redis 7（含初始化建表脚本） |

---

## 目录结构

```text
AILOVE/
├── README.md
├── Makefile                     # 常用开发/构建/测试快捷命令
├── docker-compose.yml           # 一键拉起本地 MySQL + Redis
├── backend/                     # FastAPI + MySQL + Redis + LangChain 后端
│   ├── pyproject.toml           # uv / Python 3.12 依赖与工具配置
│   ├── requirements.txt         # pip 兼容依赖清单
│   ├── .env.example             # 环境变量模板
│   ├── alembic.ini              # Alembic 数据库迁移配置
│   ├── alembic/                 # 异步迁移脚本目录
│   ├── sql/init.sql             # MySQL 初始建表脚本
│   ├── app/
│   │   ├── main.py              # FastAPI 入口与 Lifespan
│   │   ├── core/                # 配置、日志、JWT/密码安全、全局异常处理
│   │   ├── db/                  # MySQL 异步连接池、Redis 异步客户端
│   │   ├── models/              # ORM 模型 (AdminUser / WechatUser / AIConversation / AIMessage)
│   │   ├── schemas/             # Pydantic 请求与统一响应结构
│   │   ├── services/            # 认证服务、LangChain LLM 对话与流式服务
│   │   └── api/v1/              # 分端路由: /admin/*、/miniapp/*、/ai/*、/health
│   └── tests/                   # pytest 异步接口测试
├── admin-web/                   # Vue 3.5 网站管理端
│   ├── package.json
│   ├── vite.config.ts           # 已配置 /api -> http://127.0.0.1:8000 代理
│   └── src/
│       ├── api/                 # 后端接口封装（含 SSE 流式对话）
│       ├── layout/              # 后台主布局（可折叠侧边栏 + 顶栏）
│       ├── router/              # 路由与登录鉴权守卫
│       ├── stores/              # Pinia 状态管理 (auth / app)
│       ├── utils/               # Axios 封装与拦截器
│       └── views/               # 登录、控制台、小程序用户管理、AI 调试台、系统配置
└── miniprogram/                 # 微信原生开发小程序
    ├── project.config.json      # 微信开发者工具工程配置
    ├── app.json / app.js / app.wxss
    ├── config/env.js            # 开发/生产接口地址配置
    ├── utils/                   # wx.request 封装、wx.login 登录态封装
    ├── services/api.js          # 业务接口集合
    ├── components/status-badge/ # 原生自定义组件示例
    ├── assets/icons/            # 底部 TabBar 图标
    └── pages/
        ├── index/               # 首页（含后端连通性探测）
        ├── chat/                # AI 多轮对话页（对接 LangChain）
        └── profile/             # 个人中心（微信一键登录/退出）
```

---

## 快速启动指南

### 1. 启动 MySQL 与 Redis（可选，有 Docker 时推荐）

```bash
docker compose up -d
```

> 若暂未安装本地 MySQL / Redis，后端在 `APP_ENV=development` 下支持优雅降级启动（管理端支持默认账号 `admin` / `Admin123456` 登录，LangChain 未配置 API Key 时以演示模式返回，AI 多轮记忆自动回退内存存储），可直接联调接口与页面。

### 2. 启动后端服务（FastAPI + LangChain）

```bash
cd backend
cp .env.example .env          # 按需修改 MySQL / Redis / LLM_API_KEY / 微信配置
uv sync                       # 安装 Python 依赖
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

启动后访问：
- Swagger 文档：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/api/v1/health`

运行测试：

```bash
cd backend
uv run pytest -v
```

### 3. 启动网站管理端（Vue 3.5）

```bash
cd admin-web
npm install
npm run dev
```

访问 `http://localhost:5173`，使用默认管理员账号登录：
- 用户名：`admin`
- 密码：`Admin123456`

### 4. 打开微信小程序（微信原生开发）

1. 打开 **微信开发者工具**，点击「导入项目」。
2. 项目目录选择本仓库下的 `miniprogram/`。
3. 将 `miniprogram/project.config.json` 中的 `appid` 替换为你的真实微信小程序 AppID（或先使用默认 `touristappid` 游客模式预览）。
4. 本地联调时，在微信开发者工具右上角「详情 -> 本地设置」中勾选 **不校验合法域名、web-view（业务域名）、TLS 版本以及 HTTPS 证书**。
5. 后端启动在 `http://127.0.0.1:8000` 后，即可在小程序内检测后端连通性、体验一键登录与 AI 多轮对话。

---

## 接入真实大模型与微信登录

推荐使用管理后台 **「AI 模型配置」** 页面可视化配置大模型（支持 OpenAI `https://api.deepseek.com` 与 Anthropic `https://api.deepseek.com/anthropic` 双协议、内置 `deepseek-flash` / `deepseek-v4-pro`，API Key 自动使用 Fernet 加密入库并经 Redis 热生效，无需重启服务）。

也可在 `backend/.env` 中配置默认回退参数：

```env
# DeepSeek 默认回退配置（后台动态配置优先）
LLM_PROVIDER=deepseek
LLM_API_KEY=sk-xxxxxxxx
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-flash

# 微信小程序真实登录（填写后自动调用微信 jscode2session）
WECHAT_APP_ID=wx1234567890abcdef
WECHAT_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

---

## 云服务器 Docker 一键部署（管理端前后端 + MySQL + Redis）

工程根目录提供 [`docker-compose.prod.yml`](./docker-compose.prod.yml) 与 [`deploy/deploy.sh`](./deploy/deploy.sh)，可在 Linux 服务器上一键启动完整服务栈（Nginx 托管 Vue 3.5 前端并反向代理 `/api` 与 `/docs` 至 FastAPI 后端）：

```bash
# 在服务器项目目录（如 /opt/ailove）执行：
bash deploy/deploy.sh

# 查看容器状态与日志：
docker compose --env-file backend/.env -f docker-compose.prod.yml ps
docker compose --env-file backend/.env -f docker-compose.prod.yml logs -f backend
```

---

## 核心 API 规划

- `GET /api/v1/health` — 系统与 MySQL / Redis / LangChain 健康检查
- `POST /api/v1/captcha/slider/create` — 动态生成防机器人拼图滑动验证码
- `POST /api/v1/captcha/slider/verify` — 7 维行为轨迹校验并签发一次性票据
- `POST /api/v1/auth/check-email` — 六层正规邮箱识别与域名/临时邮箱风控检测
- `POST /api/v1/auth/register` — 正规邮箱自助注册（需弹窗滑动验证）
- `POST /api/v1/auth/login` — 统一账号密码登录（支持邮箱或管理员用户名，需弹窗滑动验证）
- `GET /api/v1/auth/me` — 获取当前登录用户信息及 24 小时会话剩余有效期
- `PATCH /api/v1/auth/profile` — 修改用户个人资料（昵称）
- `POST /api/v1/auth/change-password` — 自助修改密码（可选自动下线其他在线设备）
- `GET /api/v1/auth/sessions` / `DELETE /api/v1/auth/sessions/{session_id}` / `POST /api/v1/auth/sessions/revoke-others` — 多点在线设备管理、远程踢下线与一键下线其他端
- `GET /api/v1/auth/login-logs` — 查看近期登录安全审计日志
- `GET /api/v1/admin/accounts` / `POST /api/v1/admin/accounts` — 平台账号列表（含实时在线设备数）与管理员分配创建用户
- `PATCH /api/v1/admin/accounts/{user_id}/status` / `POST /api/v1/admin/accounts/{user_id}/reset-password` / `POST /api/v1/admin/accounts/{user_id}/kick` — 账号启停、重置密码与管理员强制踢下线
- `GET /api/v1/admin/dashboard/overview` — 后台仪表盘统计与服务状态
- `GET /api/v1/admin/users` — 小程序用户分页查询
- `PATCH /api/v1/admin/users/{user_id}/status` — 启用/禁用小程序用户
- `POST /api/v1/miniapp/auth/wx-login` — 微信小程序 `code` 换取 JWT Token
- `GET /api/v1/miniapp/user/profile` — 获取当前小程序用户信息
- `GET /api/v1/admin/ai/providers` / `GET /api/v1/admin/ai/configs` / `POST /api/v1/admin/ai/configs` / `PUT /api/v1/admin/ai/configs/{id}` — AI 提供商注册表与 DeepSeek 模型动态配置（Fernet 加密 API Key + Redis 热生效）
- `POST /api/v1/admin/ai/configs/{id}/set-default` / `POST /api/v1/admin/ai/configs/{id}/test` — 切换全局默认模型与一键连通性延迟探针
- `GET /api/v1/system/public-config` — 公开运行时站点配置、注册/滑块开关与密码强度策略（热生效）
- `GET /api/v1/admin/system/configs` / `PUT /api/v1/admin/system/configs` / `POST /api/v1/admin/system/configs/reset` — 5 分组 17 项动态系统配置查询、批量热更新与默认值重置
- `GET /api/v1/admin/rbac/permissions` / `GET / POST / PUT / DELETE /api/v1/admin/rbac/roles` — 全站 15 项细粒度权限点树、内置与自定义角色管理及 `PATCH /api/v1/admin/accounts/{id}/role` 授权变更
- `GET /api/v1/admin/logs/summary` / `GET /api/v1/admin/logs/audit` / `GET /api/v1/admin/logs/login` / `POST /api/v1/admin/logs/cleanup` — 24h 安全概览、脱敏操作审计分页、全站登录审计与日志清理
- `GET /api/v1/ai/models` / `POST /api/v1/ai/chat` / `POST /api/v1/ai/chat/stream` — 获取可用模型与 LangChain 同步 / SSE 流式多轮对话（支持 OpenAI / Anthropic 双协议、实时系统时钟注入、思考链流与 Token 统计）
- `GET /api/v1/ai/conversations` / `GET /api/v1/ai/conversations/{session_id}/messages` / `PATCH / DELETE /api/v1/ai/conversations/{session_id}` — 持久化 AI 历史会话列表、上下文恢复、重命名与删除（按账号严格隔离）
- `GET /api/v1/ai/sessions/{session_id}/history` — 查询当前账号本人的会话上下文（按账号隔离）
- `DELETE /api/v1/ai/sessions/{session_id}` — 清空当前账号本人的会话记忆
