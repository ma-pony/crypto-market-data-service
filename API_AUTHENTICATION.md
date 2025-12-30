# API 认证文档

本服务所有 API 接口都需要通过 Bearer Token 进行认证。

## 配置 API Token

### 1. 生成安全的 Token

```bash
# 使用 Python 生成 32 字节的随机 Token
python -c "import secrets; print(secrets.token_urlsafe(32))"

# 输出示例:
# xK7mP9nQ2wR5tY8uI3oL6aS4dF1gH0jZ9cV2bN5mX8qW
```

### 2. 配置到 .env 文件

```bash
# 编辑 .env 文件
vim .env

# 添加或修改 API_TOKEN
API_TOKEN=xK7mP9nQ2wR5tY8uI3oL6aS4dF1gH0jZ9cV2bN5mX8qW
```

### 3. 重启服务使配置生效

```bash
docker-compose restart app
```

## 使用 API Token

### 方式 1：使用 curl

```bash
# 设置 Token 变量
export API_TOKEN="xK7mP9nQ2wR5tY8uI3oL6aS4dF1gH0jZ9cV2bN5mX8qW"

# 查询 Ticker 数据
curl -H "Authorization: Bearer $API_TOKEN" \
  http://localhost:8000/api/v1/ticker/binance/BTC/USDT

# 查询 OHLCV 数据
curl -H "Authorization: Bearer $API_TOKEN" \
  "http://localhost:8000/api/v1/ohlcv/binance/BTC/USDT?timeframe=1h&limit=100"

# 批量查询
curl -X POST \
  -H "Authorization: Bearer $API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "exchange": "binance",
    "symbols": ["BTC/USDT", "ETH/USDT"],
    "timeframe": "1h",
    "limit": 100
  }' \
  http://localhost:8000/api/v1/ohlcv/batch
```

### 方式 2：使用 Python requests

```python
import requests

# API 配置
BASE_URL = "http://localhost:8000"
API_TOKEN = "xK7mP9nQ2wR5tY8uI3oL6aS4dF1gH0jZ9cV2bN5mX8qW"

# 设置认证头
headers = {
    "Authorization": f"Bearer {API_TOKEN}"
}

# 查询 Ticker
response = requests.get(
    f"{BASE_URL}/api/v1/ticker/binance/BTC/USDT",
    headers=headers
)
print(response.json())

# 查询 OHLCV
response = requests.get(
    f"{BASE_URL}/api/v1/ohlcv/binance/BTC/USDT",
    headers=headers,
    params={
        "timeframe": "1h",
        "limit": 100
    }
)
print(response.json())

# 批量查询
response = requests.post(
    f"{BASE_URL}/api/v1/ohlcv/batch",
    headers=headers,
    json={
        "exchange": "binance",
        "symbols": ["BTC/USDT", "ETH/USDT"],
        "timeframe": "1h",
        "limit": 100
    }
)
print(response.json())
```

### 方式 3：使用 JavaScript/TypeScript

```javascript
// API 配置
const BASE_URL = 'http://localhost:8000';
const API_TOKEN = 'xK7mP9nQ2wR5tY8uI3oL6aS4dF1gH0jZ9cV2bN5mX8qW';

// 设置认证头
const headers = {
    'Authorization': `Bearer ${API_TOKEN}`,
    'Content-Type': 'application/json'
};

// 查询 Ticker
fetch(`${BASE_URL}/api/v1/ticker/binance/BTC/USDT`, {
    headers: headers
})
.then(response => response.json())
.then(data => console.log(data));

// 查询 OHLCV
fetch(`${BASE_URL}/api/v1/ohlcv/binance/BTC/USDT?timeframe=1h&limit=100`, {
    headers: headers
})
.then(response => response.json())
.then(data => console.log(data));

// 批量查询
fetch(`${BASE_URL}/api/v1/ohlcv/batch`, {
    method: 'POST',
    headers: headers,
    body: JSON.stringify({
        exchange: 'binance',
        symbols: ['BTC/USDT', 'ETH/USDT'],
        timeframe: '1h',
        limit: 100
    })
})
.then(response => response.json())
.then(data => console.log(data));
```

### 方式 4：在 Swagger UI 中使用

1. 访问 API 文档：http://localhost:8000/docs
2. 点击右上角的 **Authorize** 按钮
3. 在弹出的对话框中输入 Token（不需要 "Bearer " 前缀）
4. 点击 **Authorize**
5. 现在可以直接在 Swagger UI 中测试 API

## 错误处理

### 1. 未提供 Token

**请求：**
```bash
curl http://localhost:8000/api/v1/ticker/binance/BTC/USDT
```

**响应：**
```json
{
  "detail": "Not authenticated"
}
```

**状态码：** 401 Unauthorized

### 2. Token 无效

**请求：**
```bash
curl -H "Authorization: Bearer invalid-token" \
  http://localhost:8000/api/v1/ticker/binance/BTC/USDT
```

**响应：**
```json
{
  "detail": "Invalid authentication token"
}
```

**状态码：** 401 Unauthorized

### 3. Token 格式错误

**请求：**
```bash
curl -H "Authorization: invalid-format" \
  http://localhost:8000/api/v1/ticker/binance/BTC/USDT
```

**响应：**
```json
{
  "detail": "Not authenticated"
}
```

**状态码：** 401 Unauthorized

## 安全最佳实践

### 1. Token 管理

- ✅ 使用强随机 Token（至少 32 字节）
- ✅ 定期轮换 Token（建议每 3-6 个月）
- ✅ 不要在代码中硬编码 Token
- ✅ 使用环境变量存储 Token
- ✅ 不要将 Token 提交到 Git 仓库

### 2. 传输安全

- ✅ 生产环境使用 HTTPS
- ✅ 配置 OpenResty/Nginx 反向代理
- ✅ 启用 SSL/TLS 证书

### 3. 访问控制

- ✅ 限制 API 访问 IP（通过防火墙）
- ✅ 使用不同的 Token 给不同的客户端
- ✅ 记录 API 访问日志
- ✅ 监控异常访问模式

### 4. Token 泄露应对

如果 Token 泄露：

1. **立即更换 Token**
   ```bash
   # 生成新 Token
   python -c "import secrets; print(secrets.token_urlsafe(32)"
   
   # 更新 .env
   vim .env
   
   # 重启服务
   docker-compose restart app
   ```

2. **检查访问日志**
   ```bash
   # 查看最近的 API 访问
   docker-compose logs app | grep "Request processed"
   ```

3. **通知所有合法客户端更新 Token**

## 多 Token 支持（未来扩展）

当前版本使用单一 Token，如果需要多 Token 支持（不同客户端使用不同 Token），可以：

1. 修改 `.env` 支持多个 Token：
   ```bash
   API_TOKENS=token1,token2,token3
   ```

2. 修改 `src/auth.py` 验证逻辑：
   ```python
   def verify_token(credentials: HTTPAuthorizationCredentials) -> str:
       settings = get_settings()
       tokens = settings.api_tokens.split(',')
       
       token = credentials.credentials
       if not any(secrets.compare_digest(token, t) for t in tokens):
           raise HTTPException(status_code=401, detail="Invalid token")
       
       return token
   ```

## 健康检查端点

**注意：** `/health` 端点不需要认证，可以用于监控和负载均衡器健康检查。

```bash
# 无需 Token
curl http://localhost:8000/health
```

## 根端点

**注意：** `/` 根端点也不需要认证，返回服务基本信息。

```bash
# 无需 Token
curl http://localhost:8000/
```

## 测试认证

创建测试脚本 `test_auth.sh`：

```bash
#!/bin/bash

API_TOKEN="your-token-here"
BASE_URL="http://localhost:8000"

echo "=== 测试 API 认证 ==="

echo ""
echo "1. 测试无 Token 访问（应该失败）"
curl -s -w "\nHTTP Status: %{http_code}\n" \
  "$BASE_URL/api/v1/ticker/binance/BTC/USDT"

echo ""
echo "2. 测试错误 Token（应该失败）"
curl -s -w "\nHTTP Status: %{http_code}\n" \
  -H "Authorization: Bearer wrong-token" \
  "$BASE_URL/api/v1/ticker/binance/BTC/USDT"

echo ""
echo "3. 测试正确 Token（应该成功）"
curl -s -w "\nHTTP Status: %{http_code}\n" \
  -H "Authorization: Bearer $API_TOKEN" \
  "$BASE_URL/api/v1/ticker/binance/BTC/USDT"

echo ""
echo "4. 测试健康检查（无需 Token）"
curl -s -w "\nHTTP Status: %{http_code}\n" \
  "$BASE_URL/health"
```

运行测试：
```bash
chmod +x test_auth.sh
./test_auth.sh
```

## 常见问题

### Q1: 如何查看当前配置的 Token？

```bash
# 在服务器上查看（密码会被隐藏）
cat .env | grep API_TOKEN
```

### Q2: Token 可以包含特殊字符吗？

可以，但建议使用 URL 安全的字符（`secrets.token_urlsafe()` 生成的 Token 是 URL 安全的）。

### Q3: 如何在 CI/CD 中使用 Token？

在 GitHub Actions 中添加 Secret：
```yaml
- name: Test API
  env:
    API_TOKEN: ${{ secrets.API_TOKEN }}
  run: |
    curl -H "Authorization: Bearer $API_TOKEN" \
      http://your-server/api/v1/health
```

### Q4: 可以禁用认证吗？

不建议在生产环境禁用认证。如果确实需要（仅开发环境），可以：

1. 修改 `src/auth.py`，让 `verify_token` 直接返回
2. 或者在路由中移除 `token: AuthToken` 依赖

### Q5: 如何限制 Token 的有效期？

当前实现是永久有效的 Token。如果需要过期时间，建议使用 JWT Token：

```python
import jwt
from datetime import datetime, timedelta

# 生成 JWT Token
payload = {
    'exp': datetime.utcnow() + timedelta(days=30),
    'iat': datetime.utcnow(),
    'sub': 'client_id'
}
token = jwt.encode(payload, SECRET_KEY, algorithm='HS256')

# 验证 JWT Token
try:
    payload = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
except jwt.ExpiredSignatureError:
    raise HTTPException(status_code=401, detail="Token expired")
```

## 总结

- ✅ 所有 API 接口都需要 Bearer Token 认证
- ✅ Token 通过 `Authorization: Bearer <token>` 头传递
- ✅ Token 配置在 `.env` 文件的 `API_TOKEN` 变量中
- ✅ 使用 `secrets.token_urlsafe(32)` 生成安全的 Token
- ✅ `/health` 和 `/` 端点不需要认证
- ✅ 生产环境必须配置 Token 并使用 HTTPS
