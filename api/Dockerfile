# 后端 API 镜像
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

# 使用阿里云 Debian 镜像源，安装系统依赖
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    || (apt-get clean && apt-get update && apt-get install -y --no-install-recommends gcc) && \
    rm -rf /var/lib/apt/lists/*

# 先复制 requirements.txt
COPY requirements.txt /app/api/requirements.txt

# 安装 Python 依赖
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com \
    -r /app/api/requirements.txt

# 复制应用代码
COPY . /app/api/

# 创建运行时目录
RUN mkdir -p /app/api/runtime/logs /app/api/runtime/cache /app/api/runtime/files

# 暴露端口
EXPOSE 9999

# 启动命令
CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "9999", "--reload", "--reload-dir", "/app/api"]
