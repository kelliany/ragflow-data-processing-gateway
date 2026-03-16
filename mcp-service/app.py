import sys
import os
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from starlette.responses import Response as StarletteResponse
from mcp.server import Server
from mcp.server.sse import SseServerTransport
import mcp.types as types
import uvicorn
from fastapi.middleware.cors import CORSMiddleware

# 在 app = FastAPI() 之后立即添加
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
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
            name="quiz_helper",
            description="ACP 答题助手：支持审题、归类知识点和出相似题。",
            inputSchema={
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "题目内容"},
                },
                "required": ["question"]
            }
        ),
        types.Tool(
            name="tvcms_guide",
            description="TVCMS 操作指南：查询后台功能、操作流程和故障排查。",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "操作疑问，如：如何发布内容？"}
                },
                "required": ["query"]
            }
        )
    ]
@server.call_tool()
async def call_tool(name: str, arguments: dict):
    # 1. 业务分发逻辑
    if name == "quiz_helper":
        target_id = os.getenv("RAGFLOW_ACP_QUIZ_ID")
        # 构造带有任务指令的 prompt
        # query = f"任务类型:{arguments.get('task_type')}。内容:{arguments['question']}"
        query = arguments.get("question", "")
    elif name == "tvcms_guide":
        target_id = os.getenv("RAGFLOW_TVCMS_CHAT_ID")
        query = arguments.get("query", "")
    
    else:
        return []
    print(f"[DEBUG] 准备发送给 RAGFlow. ID: {target_id}, 内容: {query}")
    
    if not query:
        return [types.TextContent(type="text", text="错误：未能从工具调用中获取有效的问题内容。")]
    # 2. 处理流式输出
    full_response_chunks = []
    print(f"\n[DEBUG] 开始请求 RAGFlow, 目标 ID: {target_id}") # 确认 ID 是否拿对
    
    async for chunk in handle_rag_chat(query, chat_id=target_id):
        full_response_chunks.append(chunk)
        # ⚡ 关键调试：在服务端控制台打印收到的每一个碎片
        print(f"{chunk}", end="", flush=True) 

    final_text = "".join(full_response_chunks)
    print(f"\n[DEBUG] 请求完成，总字符数: {len(final_text)}")
    return [types.TextContent(type="text", text=final_text)]
    


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
        return Response(content=b"", status_code=202)
        # 这样 FastAPI 就不会再尝试发送默认响应了。
    except Exception as e:
        print(f"Error: {e}")
        return Response(status_code=500)

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5000)