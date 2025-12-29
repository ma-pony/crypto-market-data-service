# 多阶段构建 - 减小镜像体积
FROM python:3.11-slim as builder

# 安装 uv
RUN pip install uv

WORKDIR /app

# 复制依赖文件
COPY pyproject.toml uv.lock ./

# 安装依赖到虚拟环境
RUN uv sync --frozen --no-dev

# 最终镜像
FROM python:3.11-slim

WORKDIR /app

# 复制虚拟环境
COPY --from=builder /app/.venv /app/.venv

# 复制应用代码
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./

# 设置环境变量
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

# 暴露端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:8000/health')" || exit 1

# 启动命令
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
