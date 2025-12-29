# 部署指南 - GitHub Actions + 阿里云

本文档介绍如何使用 GitHub Actions 自动部署项目到阿里云 Linux 服务器。

## 一、服务器准备（首次部署）

### 1. 连接到阿里云服务器

```bash
ssh root@your-server-ip
```

### 2. 安装 Docker 和 Docker Compose

```bash
# 安装 Docker
curl -fsSL https://get.docker.com | sh

# 启动 Docker 服务
systemctl start docker
systemctl enable docker

# 安装 Docker Compose
curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

# 验证安装
docker --version
docker-compose --version
```

### 3. 安装 Git

```bash
yum install -y git  # CentOS/AliyunOS
# 或
apt-get install -y git  # Ubuntu/Debian
```

### 4. 创建部署目录并克隆代码

```bash
# 创建部署目录
mkdir -p /opt/crypto-market-data-service
cd /opt/crypto-market-data-service

# 克隆代码（替换为你的 GitHub 仓库地址）
git clone https://github.com/your-username/your-repo.git .

# 如果是私有仓库，需要配置 SSH 密钥或使用 Personal Access Token
```

### 5. 配置环境变量

```bash
# 创建 .env 文件
cat > .env << 'EOF'
# 数据库密码（请修改为强密码）
POSTGRES_PASSWORD=your_secure_password_here

# 缓存配置
OHLCV_CACHE_SIZE=500
TICKER_TTL_SECONDS=10

# 数据采集配置
GAP_FILL_ENABLED=true
GAP_FILL_DAYS=7
EOF

# 创建 config.yaml 文件
cp config.yaml.example config.yaml

# 编辑配置文件
vim config.yaml  # 配置交易所和交易对
```

### 6. 首次启动服务

```bash
# 启动所有服务
docker-compose up -d

# 查看服务状态
docker-compose ps

# 等待数据库启动
sleep 10

# 运行数据库迁移
docker-compose exec app alembic upgrade head

# 查看日志
docker-compose logs -f app
```

### 7. 配置防火墙（如果需要）

```bash
# 开放 8000 端口
firewall-cmd --permanent --add-port=8000/tcp
firewall-cmd --reload

# 或使用 iptables
iptables -A INPUT -p tcp --dport 8000 -j ACCEPT
```

### 8. 测试服务

```bash
# 健康检查
curl http://localhost:8000/health

# 访问 API 文档
# 浏览器打开: http://your-server-ip:8000/docs
```

## 二、配置 GitHub Actions

### 1. 生成 SSH 密钥对

在**本地电脑**上生成 SSH 密钥对：

```bash
# 生成新的 SSH 密钥对（不要设置密码）
ssh-keygen -t rsa -b 4096 -C "github-actions" -f ~/.ssh/github_actions_key

# 查看私钥（稍后添加到 GitHub Secrets）
cat ~/.ssh/github_actions_key

# 查看公钥（稍后添加到服务器）
cat ~/.ssh/github_actions_key.pub
```

### 2. 将公钥添加到服务器

```bash
# 在服务器上执行
mkdir -p ~/.ssh
chmod 700 ~/.ssh

# 将公钥内容添加到 authorized_keys
echo "你的公钥内容" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys

# 测试 SSH 连接（在本地执行）
ssh -i ~/.ssh/github_actions_key root@your-server-ip
```

### 3. 配置 GitHub Secrets

在 GitHub 仓库中配置以下 Secrets：

1. 进入仓库页面
2. 点击 **Settings** → **Secrets and variables** → **Actions**
3. 点击 **New repository secret**，添加以下 Secrets：

| Secret 名称 | 说明 | 示例值 |
|------------|------|--------|
| `DEPLOY_HOST` | 服务器 IP 地址 | `123.456.789.0` |
| `DEPLOY_USER` | SSH 用户名 | `root` |
| `SSH_PRIVATE_KEY` | SSH 私钥内容 | 完整的私钥内容（包括 BEGIN 和 END） |
| `DEPLOY_PORT` | SSH 端口（可选） | `22` |

**SSH_PRIVATE_KEY 格式示例：**
```
-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAABlwAAAAdzc2gtcn
...（完整的私钥内容）...
-----END OPENSSH PRIVATE KEY-----
```

### 4. 配置 Git 自动拉取（服务器上）

为了让 GitHub Actions 能够自动拉取代码，需要在服务器上配置 Git：

**方式一：使用 HTTPS + Personal Access Token（推荐）**

```bash
# 在服务器上配置 Git 凭证
cd /opt/crypto-market-data-service

# 设置远程仓库为 HTTPS（如果当前是 SSH）
git remote set-url origin https://github.com/your-username/your-repo.git

# 配置 Git 凭证存储
git config credential.helper store

# 手动拉取一次，输入 GitHub 用户名和 Personal Access Token
git pull origin main
# Username: your-github-username
# Password: ghp_xxxxxxxxxxxx (Personal Access Token)
```

**如何创建 Personal Access Token：**
1. GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
2. Generate new token
3. 勾选 `repo` 权限
4. 复制生成的 token（只显示一次）

**方式二：使用 SSH 密钥**

```bash
# 在服务器上生成 SSH 密钥
ssh-keygen -t rsa -b 4096 -C "server@aliyun"

# 查看公钥
cat ~/.ssh/id_rsa.pub

# 将公钥添加到 GitHub
# GitHub → Settings → SSH and GPG keys → New SSH key
```

## 三、触发自动部署

### 自动部署

当你推送代码到 `main` 分支时，GitHub Actions 会自动触发部署：

```bash
# 在本地开发
git add .
git commit -m "feat: 添加新功能"
git push origin main

# GitHub Actions 会自动：
# 1. 连接到服务器
# 2. 拉取最新代码
# 3. 重新构建 Docker 镜像
# 4. 重启应用服务
# 5. 运行数据库迁移
# 6. 执行健康检查
```

### 手动部署

1. 进入 GitHub 仓库
2. 点击 **Actions** 标签
3. 选择 **Deploy to Aliyun** workflow
4. 点击 **Run workflow** → **Run workflow**

## 四、监控和维护

### 查看部署日志

在 GitHub 仓库的 **Actions** 标签中可以查看每次部署的详细日志。

### 服务器上查看日志

```bash
# 查看应用日志
docker-compose logs -f app

# 查看最近 100 行日志
docker-compose logs --tail=100 app

# 查看所有服务日志
docker-compose logs -f
```

### 常用运维命令

```bash
# 进入部署目录
cd /opt/crypto-market-data-service

# 查看服务状态
docker-compose ps

# 重启服务
docker-compose restart app

# 停止服务
docker-compose stop

# 启动服务
docker-compose up -d

# 查看资源使用
docker stats

# 清理旧镜像
docker image prune -f

# 查看磁盘使用
df -h
du -sh /var/lib/docker
```

### 数据库备份

```bash
# 备份数据库
docker-compose exec postgres pg_dump -U postgres market_data > backup_$(date +%Y%m%d).sql

# 恢复数据库
docker-compose exec -T postgres psql -U postgres market_data < backup_20241229.sql
```

### 回滚到上一个版本

```bash
# 查看 Git 历史
git log --oneline -10

# 回滚到指定版本
git reset --hard <commit-hash>

# 重新构建并启动
docker-compose up -d --build app
```

## 五、故障排查

### 1. 部署失败：SSH 连接超时

**原因：** 防火墙阻止 SSH 连接或 IP 地址错误

**解决：**
```bash
# 检查 SSH 服务
systemctl status sshd

# 检查防火墙
firewall-cmd --list-all

# 开放 SSH 端口
firewall-cmd --permanent --add-service=ssh
firewall-cmd --reload
```

### 2. 部署失败：Git pull 失败

**原因：** Git 凭证未配置或已过期

**解决：**
```bash
# 重新配置 Git 凭证
cd /opt/crypto-market-data-service
git config credential.helper store
git pull origin main  # 重新输入凭证
```

### 3. 服务启动失败

**原因：** 端口被占用或配置错误

**解决：**
```bash
# 查看端口占用
netstat -tlnp | grep 8000

# 查看服务日志
docker-compose logs app

# 检查配置文件
cat .env
cat config.yaml
```

### 4. 数据库连接失败

**原因：** PostgreSQL 未启动或密码错误

**解决：**
```bash
# 检查 PostgreSQL 状态
docker-compose ps postgres

# 重启 PostgreSQL
docker-compose restart postgres

# 查看 PostgreSQL 日志
docker-compose logs postgres
```

## 六、性能优化建议

### 1. 使用 Nginx 反向代理

```bash
# 安装 Nginx
yum install -y nginx  # CentOS
apt-get install -y nginx  # Ubuntu

# 配置反向代理
cat > /etc/nginx/conf.d/market-data.conf << 'EOF'
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

# 启动 Nginx
systemctl start nginx
systemctl enable nginx
```

### 2. 配置 HTTPS（使用 Let's Encrypt）

```bash
# 安装 Certbot
yum install -y certbot python3-certbot-nginx

# 获取证书
certbot --nginx -d your-domain.com

# 自动续期
certbot renew --dry-run
```

### 3. 监控服务（可选）

```bash
# 安装 Prometheus + Grafana
# 或使用阿里云监控服务
```

## 七、安全建议

1. **修改 SSH 默认端口**
2. **禁用 root 登录**（创建普通用户）
3. **配置防火墙**（只开放必要端口）
4. **定期更新系统**（`yum update` 或 `apt-get update`）
5. **使用强密码**（数据库、Redis）
6. **定期备份数据**
7. **配置日志轮转**（避免磁盘占满）

## 八、成本优化

1. **使用阿里云抢占式实例**（成本更低）
2. **配置自动关机**（非工作时间）
3. **使用对象存储**（备份数据）
4. **监控资源使用**（避免浪费）

---

## 快速参考

```bash
# 服务器首次部署
bash deploy.sh

# 查看服务状态
docker-compose ps

# 查看日志
docker-compose logs -f app

# 重启服务
docker-compose restart app

# 手动更新
cd /opt/crypto-market-data-service
git pull origin main
docker-compose up -d --build app

# 健康检查
curl http://localhost:8000/health
```

## 联系支持

如有问题，请查看：
- GitHub Actions 日志
- 服务器日志：`docker-compose logs app`
- 健康检查：`curl http://localhost:8000/health`
