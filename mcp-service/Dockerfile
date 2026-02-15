# 使用官方轻量级 Python 镜像
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量，确保 Python 输出直接打印到日志
ENV PYTHONUNBUFFERED=1

# 安装基础依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝项目文件
COPY . .

# 启动命令：由于是 MCP 服务，它通过标准输入输出通信
CMD ["python", "app.py"]