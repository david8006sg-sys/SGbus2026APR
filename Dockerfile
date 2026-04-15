# 使用官方轻量级 Python 镜像
FROM python:3.10-slim

# 设置工作目录
WORKDIR /app

# 运行时环境变量
ENV TZ=Asia/Singapore \
    PYTHONUNBUFFERED=1 \
    PORT=8000

# 复制依赖清单并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制所有源代码和 JSON 数据文件
COPY . .

# 暴露 Azure Web App / 容器使用的端口
EXPOSE 8000

# 使用 Gunicorn + Uvicorn Worker，适配 Azure Web App for Containers
CMD ["sh", "-c", "gunicorn -k uvicorn.workers.UvicornWorker main:app --bind 0.0.0.0:${PORT} --timeout 600"]