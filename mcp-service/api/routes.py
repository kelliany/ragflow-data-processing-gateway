import os
import httpx
import json

async def handle_rag_chat(question: str, chat_id: str = None):
    """
    请求 RAGFlow OpenAI 兼容接口
    优化点：显式禁用代理，防止局域网请求被系统代理拦截导致 502
    """
    # 1. 获取基础配置
    base_url = os.getenv("RAGFLOW_BASE_URL", "http://10.215.208.79:80").rstrip("/")
    api_key = os.getenv("RAGFLOW_API_KEY")
    
    # 优先使用配置的 CHAT_ID
    effective_chat_id = chat_id or os.getenv("RAGFLOW_CHAT_ID", "fa0edc9006e811f184ba3286f9b0ccd1")
    
    # 构造标准路径
    url = f"{base_url}/api/v1/chats_openai/{effective_chat_id}/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "ragflow",
        "messages": [{"role": "user", "content": question}],
        "stream": False
    }

    try:
        # 核心：使用 proxy=None 和 trust_env=False 强制直连
        async with httpx.AsyncClient(
            timeout=60.0,
            proxy=None,       # 禁用代理，解决 502 问题的核心
            trust_env=False   # 不从系统读取环境变量中的代理设置
        ) as client:
            response = await client.post(url, json=payload, headers=headers)
            raw_text = response.text
            
            # 检查 HTTP 状态码
            if response.status_code != 200:
                return f"RAGFlow 返回错误 (HTTP {response.status_code})。内容: {raw_text[:150]}"

            # 尝试解析 JSON
            try:
                data = response.json()
            except json.JSONDecodeError:
                return f"响应不是有效的 JSON 格式。原始内容: {raw_text[:100]}"

            # 处理 RAGFlow 业务错误码 (如 102 权限问题)
            if data.get("code") and data.get("code") != 0:
                return f"RAGFlow 业务错误 (Code: {data['code']}): {data.get('message', '未知错误')}"

            # 提取回答内容
            if 'choices' in data and len(data['choices']) > 0:
                return data['choices'][0]['message']['content']
            
            return f"返回数据格式异常。完整响应: {str(data)[:200]}"

    except httpx.ConnectError:
        return f"物理连接失败：请确认服务器 {base_url} 是否在线，或防火墙是否放行 80 端口。"
    except Exception as e:
        return f"调用 RAGFlow 时发生异常: {str(e)}"

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