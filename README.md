# RAGFlow Excel 反向代理网关

## 原理

管理员把浏览器访问地址从 RAGFlow 原始地址改为网关地址，其他操作完全不变。
网关透传所有请求，仅在检测到 Excel 上传时自动拦截预处理。

```
管理员浏览器
  │  访问 http://localhost:3001（网关，而不是直接访问 RAGFlow）
  ▼
admin-gateway（Node 反向代理）
  │
  ├─ 普通请求（页面、对话、搜索...）→ 直接透传给 RAGFlow
  │
  └─ POST /api/v1/datasets/:id/documents + Excel 文件
       ↓
     excel-processor（Python）
       展开合并单元格 / 多级表头处理 / 生成 Markdown + 自然语言摘要
       ↓
     替换为 .md 文件后转发给 RAGFlow
```

## 快速启动

### 1. 配置环境变量

```bash
cd admin-gateway
cp .env.example .env
# 编辑 .env，填入你的 RAGFLOW_BASE_URL
```

### 2. Docker 启动（推荐）

```bash
docker-compose up -d
```

### 3. 本地启动

```bash
# 终端1：Python 预处理服务
cd excel-processor
pip install -r requirements.txt
python app.py

# 终端2：Node 反向代理网关
cd admin-gateway
npm install
npm start
```

## 使用方式

启动后，把浏览器访问地址改为网关地址即可：

| 原来 | 改为 |
|------|------|
| `http://your-ragflow:80` | `http://localhost:3001` |

上传 Excel 文件的操作和之前完全一样，网关自动在背后处理。

## 目录结构

```
excel-gateway/
├── docker-compose.yml
├── excel-processor/          # Python 预处理服务（端口 5001）
│   ├── app.py                # Excel → Markdown 转换逻辑
│   ├── requirements.txt
│   └── Dockerfile
└── admin-gateway/            # Node 反向代理网关（端口 3001）
    ├── package.json
    ├── Dockerfile
    ├── .env.example
    └── src/
        ├── index.js              # 入口，挂载拦截器和反向代理
        └── excelInterceptor.js   # Excel 拦截核心逻辑
```
