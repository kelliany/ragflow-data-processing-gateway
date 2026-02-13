# 使用轻量级的 Python 基础镜像
FROM python:3.10-slim

# 设置工作目录
WORKDIR /app

# 安装必要的系统依赖（如果某些库需要编译）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 拷贝依赖文件并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝项目所有代码
COPY . .

# 暴露网关端口
EXPOSE 5001

# 使用 Gunicorn 启动生产环境服务
# -w 4: 开启4个工作进程
# --timeout 120: 考虑到大型Excel解析耗时，增加超时时间
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5001", "--timeout", "120", "app:app"]