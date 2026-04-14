# NueroNote Dockerfile
# 多阶段构建：开发/生产

FROM python:3.11-slim as base

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# =============================================================================
# 开发阶段
# =============================================================================
FROM base as development

COPY --from=base /app /app

# 复制依赖文件
COPY nueronote_server/requirements.txt /app/nueronote_server/

# 安装Python依赖
RUN pip install --no-cache-dir -r /app/nueronote_server/requirements.txt

# 复制源代码
COPY . /app/

# 暴露端口
EXPOSE 5000

# 开发模式启动
CMD ["python3", "nueronote_server/app_modern.py"]

# =============================================================================
# 生产阶段
# =============================================================================
FROM base as production

# 创建非root用户
RUN groupadd -r appuser && useradd -r -g appuser appuser

COPY --from=base /app /app

# 复制依赖文件
COPY nueronote_server/requirements.txt /app/nueronote_server/

# 安装Python依赖（生产级别）
RUN pip install --no-cache-dir --prefix=/install -r /app/nueronote_server/requirements.txt && \
    mv /install/* /usr/local/ && \
    rm -rf /install

# 复制源代码
COPY --chown=appuser:appuser . /app/

# 设置权限
RUN chown -R appuser:appuser /app

USER appuser

# 暴露端口
EXPOSE 5000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

# 生产模式启动
CMD ["python3", "nueronote_server/app_modern.py"]
