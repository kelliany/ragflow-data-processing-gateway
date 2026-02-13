# 使用 Python 3.12 基础镜像
FROM python:3.12

# 设置工作目录
WORKDIR /app

# 【核心修改】更换为阿里云 Debian 镜像源 (适用于 Debian Trixie/13)
# 如果你的基础镜像版本不同，这一步会自动适配
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources || \
    sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list

# 现在执行更新和安装就会非常快了
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 拷贝依赖并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt

# 拷贝代码
COPY . .

EXPOSE 5001

CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5001", "--timeout", "120", "app:app"]