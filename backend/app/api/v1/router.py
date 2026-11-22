from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import auth, captcha, health
from app.api.v1.admin import accounts as admin_accounts
from app.api.v1.admin import ai_configs as admin_ai_configs
from app.api.v1.admin import auth as admin_auth
from app.api.v1.admin import dashboard as admin_dashboard
from app.api.v1.admin import users as admin_users
from app.api.v1.ai import chat as ai_chat
from app.api.v1.miniapp import auth as miniapp_auth
from app.api.v1.miniapp import user as miniapp_user

api_v1_router = APIRouter()

# 公共系统健康检查
api_v1_router.include_router(health.router)

# 风控滑动验证码 (/api/v1/captcha/*)
api_v1_router.include_router(captcha.router)

# 统一用户邮箱注册与登录 (/api/v1/auth/*)
api_v1_router.include_router(auth.router)

# 网站管理端路由 (/api/v1/admin/*)
admin_router = APIRouter(prefix="/admin")
admin_router.include_router(admin_auth.router)
admin_router.include_router(admin_dashboard.router)
admin_router.include_router(admin_accounts.router)
admin_router.include_router(admin_ai_configs.router)
admin_router.include_router(admin_users.router)
api_v1_router.include_router(admin_router)

# 微信小程序路由 (/api/v1/miniapp/*)
miniapp_router = APIRouter(prefix="/miniapp")
miniapp_router.include_router(miniapp_auth.router)
miniapp_router.include_router(miniapp_user.router)
api_v1_router.include_router(miniapp_router)

# AI / LangChain 路由 (/api/v1/ai/*)
api_v1_router.include_router(ai_chat.router)
