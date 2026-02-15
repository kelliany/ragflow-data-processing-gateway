import sys
import os
from pathlib import Path

# --- 必须放在所有 import 之前 ---
# 1. 获取 mcp-service 的绝对路径
current_file = Path(__file__).resolve()
mcp_service_dir = current_file.parent

# 2. 将 mcp-service 目录插入到路径最前端
# 这样当 api.routes 执行 "from services..." 时，Python 会在 mcp-service 下找到 services
if str(mcp_service_dir) not in sys.path:
    sys.path.insert(0, str(mcp_service_dir))

# 3. (可选) 如果你的 services 依赖根目录的其他内容，也可以加入根目录
root_dir = mcp_service_dir.parent
if str(root_dir) not in sys.path:
    sys.path.append(str(root_dir))

# --- 现在开始正常的 import ---
import asyncio
from dotenv import load_dotenv
from mcp.server.stdio import stdio_server
from mcp.server import Server
from mcp.server.models import InitializationOptions, ServerCapabilities
import mcp.types as types

# 加载环境变量
load_dotenv(mcp_service_dir / ".env")
load_dotenv(root_dir / ".env")
# 强制禁用代理，防止请求局域网 IP 时被转发到外部代理服务器
os.environ["HTTP_PROXY"] = ""
os.environ["HTTPS_PROXY"] = ""
os.environ["NO_PROXY"] = "*"

# 导入业务逻辑
from api.routes import handle_rag_chat, handle_excel_transform

server = Server("ragflow-mcp-bridge")

@server.list_tools()
async def list_tools():
    """暴露 RAGFlow 对话和 Excel 处理工具"""
    return [
        types.Tool(
            name="rag_query",
            description="基于 RAGFlow 知识库回答问题。",
            inputSchema={
                "type": "object",
                "properties": {"question": {"type": "string"}},
                "required": ["question"]
            }
        ),
        types.Tool(
            name="process_excel",
            description="通过 admin-gateway 处理本地 Excel 文件并入库。",
            inputSchema={
                "type": "object",
                "properties": {"file_path": {"type": "string"}},
                "required": ["file_path"]
            }
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "rag_query":
        ans = await handle_rag_chat(arguments["question"])
        return [types.TextContent(type="text", text=ans)]
    
    if name == "process_excel":
        res = await handle_excel_transform(arguments["file_path"])
        return [types.TextContent(type="text", text=res)]

async def main():
    async with stdio_server() as (read, write):
        # 为最新版本的 mcp 包更新初始化选项
        await server.run(
            read, write, 
            InitializationOptions(
                server_name="ragflow-mcp", 
                server_version="1.0.0",
                capabilities=ServerCapabilities(
                    runnableToolCount=2,  # 我们有两个工具
                    maxConcurrentRunnableToolCount=2,
                    supportsToolCalls=True,
                    supportsStreaming=False,
                    supportedToolTypes=["function"],
                    supportedContentTypes=["text"],
                    supportsBinaryToolResponses=False
                )
            )
        )

if __name__ == "__main__":
    asyncio.run(main())