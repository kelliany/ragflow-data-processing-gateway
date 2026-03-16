import os
import httpx
import json

async def handle_rag_chat(question: str, chat_id: str = None):
    """
    请求 RAGFlow OpenAI 兼容接口（流式版本）
    支持 SSE 推送，解决长文本生成等待焦虑
    """
    base_url = os.getenv("RAGFLOW_BASE_URL", "http://10.215.208.79:80").rstrip("/")
    api_key = os.getenv("RAGFLOW_API_KEY")
    
    # 动态选择智能体 ID：支持答题系统或 TVCMS 操作指南
    effective_chat_id = chat_id or os.getenv("RAGFLOW_CHAT_ID", "fa0edc9006e811f184ba3286f9b0ccd1")
    
    url = f"{base_url}/api/v1/chats_openai/{effective_chat_id}/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "ragflow",
        "messages": [{"role": "user", "content": question}],
        "stream": True  # ⚡ 核心修改：开启流式模式
    }

    try:
        async with httpx.AsyncClient(
            timeout=60.0,
            proxy=None,       # 强制直连，解决 502 问题
            trust_env=False 
        ) as client:
            # 使用 stream() 方法发起请求
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                print(f"[DEBUG] RAGFlow Response Code: {response.status_code}") # 确认是否为 200
                if response.status_code != 200:
                    error_detail = await response.text()
                    print(f"[CRITICAL] RAGFlow API 拒绝请求: {response.status_code} | 详情: {error_detail}")
                    yield f"RAGFlow 返回错误 (HTTP {response.status_code})"
                    return

                # 逐行读取 SSE 数据流
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    
                    # 移除 "data: " 前缀
                    data_str = line[5:].strip()
                    
                    if data_str == "[DONE]":
                        break
                    
                    try:
                        chunk = json.loads(data_str)
                        # 提取增量文本内容
                        if 'choices' in chunk and len(chunk['choices']) > 0:
                            content = chunk['choices'][0].get('delta', {}).get('content', '')
                            if content:
                                yield content # 逐字返回
                    except json.JSONDecodeError:
                        continue

    except Exception as e:
        yield f"流式调用异常: {str(e)}"

async def handle_excel_transform(file_path: str):
    """
    调用 Excel 网关处理服务
    对接您之前部署的 Docker 化的 excel-processor
    """
    # 获取网关地址
    gateway_url = os.getenv("EXCEL_GATEWAY_URL", "http://localhost:8080/transform")
    
    try:
        # 同样建议在内部网关调用时禁用代理
        async with httpx.AsyncClient(
            timeout=120.0,
            proxy=None,
            trust_env=False
        ) as client:
            if not os.path.exists(file_path):
                return f"错误：找不到文件 {file_path}"
                
            with open(file_path, 'rb') as f:
                files = {'file': f}
                # 对接 admin-gateway 或 excel-processor 接口
                response = await client.post(gateway_url, files=files)
                response.raise_for_status()
                return f"Excel 处理成功。结果: {response.text[:200]}"
                
    except Exception as e:
        return f"Excel 处理失败: {str(e)}"