.PHONY: help infra-up infra-down backend-install backend-dev backend-test backend-migrate admin-install admin-dev admin-build

help:
	@echo "AILOVE 项目常用命令:"
	@echo "  make infra-up         启动本地 MySQL + Redis (Docker)"
	@echo "  make infra-down       停止本地 MySQL + Redis"
	@echo "  make backend-install  使用 uv 安装后端依赖"
	@echo "  make backend-dev      启动 FastAPI 开发服务 (端口 8000)"
	@echo "  make backend-test     运行后端 pytest 测试"
	@echo "  make backend-migrate  执行 Alembic 数据库迁移"
	@echo "  make admin-install    安装管理端前端依赖"
	@echo "  make admin-dev        启动 Vue 3.5 管理端开发服务 (端口 5173)"
	@echo "  make admin-build      构建管理端生产产物"

infra-up:
	docker compose up -d

infra-down:
	docker compose down

backend-install:
	cd backend && uv sync

backend-dev:
	cd backend && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

backend-test:
	cd backend && uv run pytest -v

backend-migrate:
	cd backend && uv run alembic upgrade head

admin-install:
	cd admin-web && npm install

admin-dev:
	cd admin-web && npm run dev

admin-build:
	cd admin-web && npm run build
