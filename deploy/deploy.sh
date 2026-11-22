#!/usr/bin/env bash
set -euo pipefail

# AILOVE 云服务器一键 Docker 部署脚本（在目标 Linux 服务器上执行）
# 用法：cd /opt/ailove && bash deploy/deploy.sh

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_DIR}"

echo "==> [1/5] 检查 Docker 与 Docker Compose..."
if ! command -v docker >/dev/null 2>&1; then
  echo "未检测到 Docker，正在安装 Docker..."
  curl -fsSL https://get.docker.com | sh -s -- --mirror Aliyun
  systemctl enable --now docker
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "错误：未检测到 docker compose 插件，请安装 docker-compose-plugin 后重试。"
  exit 1
fi

echo "==> [2/5] 配置国内 Docker 镜像加速（若尚未配置）..."
mkdir -p /etc/docker
if [ ! -f /etc/docker/daemon.json ]; then
  cat > /etc/docker/daemon.json <<'EOF'
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://docker.1ms.run"
  ]
}
EOF
  systemctl daemon-reload || true
  systemctl restart docker || true
fi

echo "==> [3/5] 初始化 backend/.env（若不存在）..."
if [ ! -f backend/.env ]; then
  cp backend/.env.example backend/.env
  JWT_SECRET="$(openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
  sed -i "s|^JWT_SECRET_KEY=.*|JWT_SECRET_KEY=${JWT_SECRET}|" backend/.env
  sed -i "s|^MYSQL_HOST=.*|MYSQL_HOST=mysql|" backend/.env
  sed -i "s|^REDIS_HOST=.*|REDIS_HOST=redis|" backend/.env
  echo "已生成 backend/.env，并自动配置随机 JWT_SECRET_KEY。"
fi

echo "==> [4/5] 构建并启动 MySQL + Redis + FastAPI 后端 + Vue 3.5 管理端容器..."
docker compose --env-file backend/.env -f docker-compose.prod.yml up -d --build

echo "==> [5/5] 检查容器运行状态与健康接口..."
docker compose --env-file backend/.env -f docker-compose.prod.yml ps

echo ""
echo "等待后端健康检查就绪..."
for i in $(seq 1 20); do
  if curl -fsS http://127.0.0.1/api/v1/health >/dev/null 2>&1; then
    echo "部署成功！健康检查返回："
    curl -fsS http://127.0.0.1/api/v1/health
    echo ""
    exit 0
  fi
  sleep 3
done

echo "警告：健康检查暂未返回 200，请查看日志：docker compose -f docker-compose.prod.yml logs --tail=100"
exit 1
