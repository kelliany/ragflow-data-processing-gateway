import sys
import os
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from mcp.server import Server
from mcp.server.sse import SseServerTransport
import mcp.types as types
import uvicorn

# 路径修复
current_file = Path(__file__).resolve()
mcp_service_dir = current_file.parent
sys.path.insert(0, str(mcp_service_dir))
sys.path.append(str(mcp_service_dir.parent))

load_dotenv(mcp_service_dir / ".env")
from api.routes import handle_rag_chat, handle_excel_transform

# 初始化 MCP Server
server = Server("ragflow-mcp-bridge")
sse = SseServerTransport("/messages")

@server.list_tools()
async def list_tools():
    return [
        types.Tool(
            name="rag_query",
            description="基于 RAGFlow 知识库回答问题。",
            inputSchema={"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "rag_query":
        ans = await handle_rag_chat(arguments["question"])
        return [types.TextContent(type="text", text=str(ans))]
    return []

app = FastAPI()

@app.get("/sse")
async def sse_endpoint(request: Request):
    # 使用 connect_sse 建立连接
    async with sse.connect_sse(request.scope, request._receive, request._send) as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )

@app.post("/messages")
async def messages_endpoint(request: Request):
    try:
        await sse.handle_post_message(
            request.scope, 
            request._receive, 
            request._send
        )
        # 返回一个特殊的 Response 对象，不带任何内容，
        # 这样 FastAPI 就不会再尝试发送默认响应了。
        # return Response(status_code=202) 
    except Exception as e:
        print(f"Error: {e}")
        return Response(status_code=500)

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5000)