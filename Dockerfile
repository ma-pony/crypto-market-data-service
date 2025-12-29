# 多阶段构建 - 减小镜像体积
FROM python:3.11-slim as builder

# 安装 uv
RUN pip install uv

WORKDIR /app

# 复制所有文件（通过 .dockerignore 排除不需要的）
COPY . .

# 安装依赖到虚拟环境
RUN uv sync --frozen --no-dev

# 最终镜像
FROM python:3.11-slim

WORKDIR /app

# 安装运行时依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制虚拟环境
COPY --from=builder /app/.venv /app/.venv

# 复制应用代码（通过 .dockerignore 排除不需要的）
COPY . .

# 设置环境变量
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

# 暴露端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# 启动命令
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
