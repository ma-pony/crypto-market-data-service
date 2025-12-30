#!/bin/bash
# API 认证测试脚本

# 配置
BASE_URL="${BASE_URL:-http://localhost:8000}"
API_TOKEN="${API_TOKEN:-}"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=== API 认证测试 ==="
echo "Base URL: $BASE_URL"
echo ""

# 检查是否设置了 API_TOKEN
if [ -z "$API_TOKEN" ]; then
    echo -e "${YELLOW}警告: API_TOKEN 未设置${NC}"
    echo "请设置环境变量: export API_TOKEN='your-token-here'"
    echo ""
fi

# 测试函数
test_endpoint() {
    local name="$1"
    local method="$2"
    local endpoint="$3"
    local auth="$4"
    local data="$5"
    
    echo "测试: $name"
    echo "  方法: $method $endpoint"
    
    if [ "$auth" = "yes" ]; then
        if [ -z "$API_TOKEN" ]; then
            echo -e "  ${YELLOW}跳过（未设置 API_TOKEN）${NC}"
            echo ""
            return
        fi
        AUTH_HEADER="-H \"Authorization: Bearer $API_TOKEN\""
    else
        AUTH_HEADER=""
    fi
    
    if [ "$method" = "POST" ]; then
        CMD="curl -s -w \"\nHTTP_STATUS:%{http_code}\" -X POST $AUTH_HEADER -H \"Content-Type: application/json\" -d '$data' \"$BASE_URL$endpoint\""
    else
        CMD="curl -s -w \"\nHTTP_STATUS:%{http_code}\" $AUTH_HEADER \"$BASE_URL$endpoint\""
    fi
    
    RESPONSE=$(eval $CMD)
    HTTP_CODE=$(echo "$RESPONSE" | grep "HTTP_STATUS:" | cut -d: -f2)
    BODY=$(echo "$RESPONSE" | sed '/HTTP_STATUS:/d')
    
    if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "201" ]; then
        echo -e "  ${GREEN}✓ 成功 (HTTP $HTTP_CODE)${NC}"
    elif [ "$HTTP_CODE" = "401" ]; then
        echo -e "  ${RED}✗ 认证失败 (HTTP $HTTP_CODE)${NC}"
    else
        echo -e "  ${YELLOW}! 其他状态 (HTTP $HTTP_CODE)${NC}"
    fi
    
    # 显示响应体（截断）
    if [ ${#BODY} -gt 200 ]; then
        echo "  响应: ${BODY:0:200}..."
    else
        echo "  响应: $BODY"
    fi
    echo ""
}

echo "=== 1. 无需认证的端点 ==="
test_endpoint "根端点" "GET" "/" "no"
test_endpoint "健康检查" "GET" "/health" "no"

echo "=== 2. 需要认证的端点（无 Token）==="
API_TOKEN="" test_endpoint "Ticker（无Token）" "GET" "/api/v1/ticker/binance/BTC/USDT" "no"
API_TOKEN="" test_endpoint "OHLCV（无Token）" "GET" "/api/v1/ohlcv/binance/BTC/USDT?timeframe=1h&limit=10" "no"

if [ -n "$API_TOKEN" ]; then
    echo "=== 3. 需要认证的端点（有 Token）==="
    test_endpoint "Ticker（有Token）" "GET" "/api/v1/ticker/binance/BTC/USDT" "yes"
    test_endpoint "OHLCV（有Token）" "GET" "/api/v1/ohlcv/binance/BTC/USDT?timeframe=1h&limit=10" "yes"
    test_endpoint "Tickers（有Token）" "GET" "/api/v1/tickers/binance" "yes"
    
    echo "=== 4. POST 请求测试 ==="
    BATCH_DATA='{"exchange":"binance","symbols":["BTC/USDT"],"timeframe":"1h","limit":10}'
    test_endpoint "批量查询（有Token）" "POST" "/api/v1/ohlcv/batch" "yes" "$BATCH_DATA"
    
    echo "=== 5. 错误 Token 测试 ==="
    ORIGINAL_TOKEN="$API_TOKEN"
    API_TOKEN="wrong-token-12345"
    test_endpoint "Ticker（错误Token）" "GET" "/api/v1/ticker/binance/BTC/USDT" "yes"
    API_TOKEN="$ORIGINAL_TOKEN"
fi

echo "=== 测试完成 ==="
echo ""
echo "说明："
echo "  - ✓ 绿色：请求成功"
echo "  - ✗ 红色：认证失败（预期行为）"
echo "  - ! 黄色：其他状态"
echo ""
echo "使用方法："
echo "  export API_TOKEN='your-token-here'"
echo "  ./test_auth.sh"
