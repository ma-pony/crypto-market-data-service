#!/bin/bash
# 检查环境变量配置脚本

echo "=== 检查 .env 文件 ==="
if [ -f ".env" ]; then
    echo "✅ .env 文件存在"
    echo ""
    echo "内容预览（隐藏密码）："
    cat .env | sed 's/\(PASSWORD\|password\|SECRET\|secret\)=.*/\1=***HIDDEN***/g'
else
    echo "❌ .env 文件不存在！"
    echo "请创建 .env 文件："
    echo "  cp .env.example .env"
    echo "  vim .env"
    exit 1
fi

echo ""
echo "=== Docker Compose 解析后的配置 ==="
echo "（这是 Docker Compose 读取 .env 后的最终配置）"
docker-compose config 2>/dev/null | grep -A 15 "environment:" || echo "❌ 无法解析配置，请检查 docker-compose.yml"

echo ""
echo "=== 容器内的环境变量（如果容器正在运行）==="
if docker-compose ps | grep -q "Up"; then
    echo "✅ 容器正在运行，查看环境变量："
    echo ""
    docker-compose exec -T app env | grep -E "DATABASE_URL|REDIS_URL|OHLCV_CACHE_SIZE|TICKER_TTL_SECONDS|API_PORT|GAP_FILL" | sed 's/\(PASSWORD\|password\)=[^@]*/\1=***HIDDEN***/g'
else
    echo "⚠️  容器未运行，无法查看容器内环境变量"
    echo "启动容器: docker-compose up -d app"
fi

echo ""
echo "=== 测试数据库连接（如果容器正在运行）==="
if docker-compose ps | grep -q "Up"; then
    docker-compose exec -T app python -c "
import os
import sys

print('读取到的环境变量：')
print(f'  DATABASE_URL: {os.getenv(\"DATABASE_URL\", \"未设置\")[:50]}...')
print(f'  REDIS_URL: {os.getenv(\"REDIS_URL\", \"未设置\")}')
print(f'  OHLCV_CACHE_SIZE: {os.getenv(\"OHLCV_CACHE_SIZE\", \"未设置\")}')
print(f'  API_PORT: {os.getenv(\"API_PORT\", \"未设置\")}')
" 2>/dev/null || echo "⚠️  无法在容器中运行 Python"
fi

echo ""
echo "=== 总结 ==="
echo "1. .env 文件在宿主机上（不在容器内）"
echo "2. Docker Compose 读取 .env 并注入到容器的环境变量"
echo "3. 应用通过 os.getenv() 读取环境变量"
echo "4. 修改 .env 后需要重启容器: docker-compose restart app"
