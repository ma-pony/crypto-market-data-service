#!/bin/bash
# 服务器端部署脚本 - 首次部署使用（适用于 1Panel 环境）

set -e

echo "=== Crypto Market Data Service 部署脚本 (1Panel 环境) ==="

# 配置变量
DEPLOY_DIR="/opt/crypto-market-data-service"
REPO_URL="https://github.com/your-username/your-repo.git"  # 替换为你的 GitHub 仓库地址

# 检查 Docker 是否安装
if ! command -v docker &> /dev/null; then
    echo "❌ Docker 未安装！"
    echo "请通过 1Panel 面板安装 Docker，或手动安装："
    echo "  curl -fsSL https://get.docker.com | sh"
    exit 1
fi

# 检查 Docker Compose 是否安装
if ! command -v docker-compose &> /dev/null; then
    echo "Docker Compose 未安装，正在安装..."
    curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose
    echo "✅ Docker Compose 安装完成"
fi

# 创建部署目录
echo "创建部署目录: $DEPLOY_DIR"
mkdir -p $DEPLOY_DIR
cd $DEPLOY_DIR

# 克隆或更新代码（首次部署）
if [ ! -d ".git" ]; then
    echo "克隆代码仓库..."
    git clone $REPO_URL .
else
    echo "更新代码..."
    git pull
fi

# 创建配置文件（如果不存在）
if [ ! -f ".env" ]; then
    echo "创建 .env 配置文件..."
    cat > .env << 'ENVEOF'
# 数据库配置（1Panel 安装的 PostgreSQL）
# 请根据 1Panel 中的实际配置修改
DATABASE_URL=postgresql://postgres:your_password@localhost:5432/market_data
DATABASE_POOL_SIZE=10

# Redis 配置（1Panel 安装的 Redis）
REDIS_URL=redis://localhost:6379/0
OHLCV_CACHE_SIZE=500
TICKER_TTL_SECONDS=10

# API 配置
API_HOST=0.0.0.0
API_PORT=8000

# 数据采集配置
GAP_FILL_ENABLED=true
GAP_FILL_DAYS=7
ENVEOF
    echo "⚠️  请编辑 .env 文件，配置数据库连接信息"
    echo "   1. 在 1Panel 中查看 PostgreSQL 的用户名、密码、端口"
    echo "   2. 在 1Panel 中查看 Redis 的端口（默认 6379）"
    echo "   3. 编辑命令: vim .env"
fi

if [ ! -f "config.yaml" ]; then
    echo "创建 config.yaml 配置文件..."
    cp config.yaml.example config.yaml
    echo "⚠️  请编辑 config.yaml 文件，配置交易所和交易对"
fi

# 创建日志目录
mkdir -p logs

# 检查数据库是否存在，不存在则创建
echo "检查数据库..."
DB_EXISTS=$(docker exec -i $(docker ps -qf "name=postgres" -qf "name=1panel") psql -U postgres -tAc "SELECT 1 FROM pg_database WHERE datname='market_data'" 2>/dev/null || echo "")
if [ -z "$DB_EXISTS" ]; then
    echo "创建数据库 market_data..."
    docker exec -i $(docker ps -qf "name=postgres" -qf "name=1panel") psql -U postgres -c "CREATE DATABASE market_data;" 2>/dev/null || echo "⚠️  请手动在 1Panel 中创建数据库: market_data"
else
    echo "✅ 数据库已存在"
fi

# 构建并启动服务
echo "构建 Docker 镜像..."
docker-compose build app

echo "启动应用服务..."
docker-compose up -d app

# 等待服务启动
echo "等待服务启动..."
sleep 5

# 运行数据库迁移
echo "运行数据库迁移..."
docker-compose exec -T app alembic upgrade head || echo "⚠️  数据库迁移失败，请检查数据库连接配置"

# 显示服务状态
echo ""
echo "=== 服务状态 ==="
docker-compose ps

echo ""
echo "=== 部署完成 ==="
echo "服务地址: http://$(hostname -I | awk '{print $1}'):8000"
echo "API 文档: http://$(hostname -I | awk '{print $1}'):8000/docs"
echo "健康检查: http://$(hostname -I | awk '{print $1}'):8000/health"
echo ""
echo "⚠️  重要提示："
echo "1. 请确保在 1Panel 中已创建数据库: market_data"
echo "2. 请确保 .env 中的数据库连接信息正确"
echo "3. 如需配置 OpenResty 反向代理，请参考 DEPLOYMENT.md"
echo ""
echo "常用命令:"
echo "  查看日志: docker-compose logs -f app"
echo "  重启服务: docker-compose restart app"
echo "  停止服务: docker-compose stop app"
echo "  更新代码: git pull && docker-compose up -d --build app"
