#!/usr/bin/env bash
set -euo pipefail

# AILOVE 云服务器一键 Docker 部署脚本（已针对 2C2G 低内存主机优化）
# 用法：cd /opt/ailove && bash deploy/deploy.sh

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_DIR}"

echo "==> [1/6] 检查 Docker 与 Docker Compose..."
if ! command -v docker >/dev/null 2>&1; then
  echo "未检测到 Docker，正在安装 Docker..."
  curl -fsSL https://get.docker.com | sh -s -- --mirror Aliyun
  systemctl enable --now docker
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "错误：未检测到 docker compose 插件，请安装 docker-compose-plugin 后重试。"
  exit 1
fi

echo "==> [2/6] 检查 2C2G 内存保护（按需自动配置 2GB Swap，防止构建期 OOM）..."
TOTAL_MEM_MB="$(free -m | awk '/^Mem:/ {print $2}')"
TOTAL_SWAP_MB="$(free -m | awk '/^Swap:/ {print $2}')"
if [ "${TOTAL_MEM_MB:-0}" -le 2560 ] && [ "${TOTAL_SWAP_MB:-0}" -lt 512 ] && [ "$(id -u)" -eq 0 ]; then
  if [ ! -f /swapfile ]; then
    echo "检测到主机内存 ${TOTAL_MEM_MB}MB 且未启用 Swap，正在创建 2GB /swapfile..."
    fallocate -l 2G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
    chmod 600 /swapfile
    mkswap /swapfile >/dev/null
    swapon /swapfile
    grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
    sysctl -w vm.swappiness=15 >/dev/null 2>&1 || true
    echo "2GB Swap 已启用（vm.swappiness=15）。"
  fi
fi

echo "==> [3/6] 配置国内 Docker 镜像加速与日志限额（若尚未配置）..."
mkdir -p /etc/docker
if [ ! -f /etc/docker/daemon.json ]; then
  cat > /etc/docker/daemon.json <<'EOF'
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://docker.1ms.run"
  ],
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
EOF
  systemctl daemon-reload || true
  systemctl restart docker || true
fi

echo "==> [4/6] 初始化 backend/.env（若不存在）..."
if [ ! -f backend/.env ]; then
  cp backend/.env.example backend/.env
  JWT_SECRET="$(openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
  sed -i "s|^JWT_SECRET_KEY=.*|JWT_SECRET_KEY=${JWT_SECRET}|" backend/.env
  sed -i "s|^MYSQL_HOST=.*|MYSQL_HOST=mysql|" backend/.env
  sed -i "s|^REDIS_HOST=.*|REDIS_HOST=redis|" backend/.env
  echo "已生成 backend/.env，并自动配置随机 JWT_SECRET_KEY。"
fi

echo "==> [5/6] 构建并启动 MySQL + Redis + FastAPI 后端 + Nginx（管理端与小程序统一网关）..."
docker compose --env-file backend/.env -f docker-compose.prod.yml up -d --build
docker image prune -f >/dev/null 2>&1 || true

echo "==> [6/6] 检查容器运行状态、资源占用与健康接口..."
docker compose --env-file backend/.env -f docker-compose.prod.yml ps

echo ""
echo "等待后端健康检查就绪..."
for i in $(seq 1 25); do
  if curl -fsS http://127.0.0.1/api/v1/health >/dev/null 2>&1; then
    echo "部署成功！健康检查返回："
    curl -fsS http://127.0.0.1/api/v1/health
    echo ""
    docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}"
    exit 0
  fi
  sleep 3
done

echo "警告：健康检查暂未返回 200，请查看日志：docker compose -f docker-compose.prod.yml logs --tail=100"
exit 1
