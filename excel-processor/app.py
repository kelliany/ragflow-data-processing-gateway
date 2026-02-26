"""
app.py - 极速 Excel 处理器 v9.0 (终极集成版)
功能特性：
1. 物理溯源：保存原始文件至 /app/data/uploads。
2. 并行解析：使用 ProcessPoolExecutor 提升多表处理性能。
3. 锚点定位：支持 #sheet_xxxx 跳转，并带有高亮显示逻辑。
4. 语义注入：在 HTML 隐藏层注入 RAG 上下文。
5. 健康检查：提供 /health 接口供 Docker 探测。
"""

from flask import Flask, request, jsonify, send_from_directory
import pandas as pd
import io
import time
import logging
import warnings
import base64
import re
import uuid
import os
from urllib.parse import unquote
from concurrent.futures import ProcessPoolExecutor

# --- 基础配置 ---
warnings.filterwarnings('ignore')
app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 数据限制
MAX_RAG_ROWS = 1000 
MAX_PREVIEW_ROWS = 3000 
UPLOAD_FOLDER = "/app/data/uploads"

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# ── 基础服务路由 ──────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    """用于 Docker 存活探针"""
    return jsonify({"status": "healthy", "service": "excel-processor"}), 200

@app.route("/api/download/<path:filename>", methods=["GET"])
def download_file(filename):
    """
    物理文件下载：
    使用 <path:filename> 以兼容包含斜杠或复杂字符的文件名。
    """
    try:
        # 显式解码文件名，防止双重编码导致的 404
        decoded_name = unquote(filename)
        return send_from_directory(UPLOAD_FOLDER, decoded_name, as_attachment=True)
    except FileNotFoundError:
        return jsonify({"error": "File not found"}), 404

# ── 核心解析逻辑 ──────────────────────────────────────

def clean_dataframe(df):
    """清洗表格：处理合并单元格、空行、识别表头"""
    try:
        df = df.dropna(how='all', axis=0).dropna(how='all', axis=1)
        if df.empty: return df
        if len(df) > 1:
            row0_empty_ratio = df.iloc[0].isna().sum() / df.shape[1]
            if row0_empty_ratio < 0.5:
                df.columns = df.iloc[0].astype(str).fillna('')
                df = df.iloc[1:]
            else:
                headers_row0 = df.iloc[0].ffill()
                headers_row1 = df.iloc[1]
                new_headers = []
                for h0, h1 in zip(headers_row0, headers_row1):
                    h0 = str(h0) if pd.notna(h0) else ""
                    h1 = str(h1) if pd.notna(h1) else ""
                    new_headers.append(f"{h0}_{h1}" if h0 and h1 and h0 != h1 else (h1 if h1 else h0))
                df.columns = new_headers
                df = df.iloc[2:]
        if not df.empty and df.shape[1] > 0:
            df[df.columns[:min(2, df.shape[1])]] = df[df.columns[:min(2, df.shape[1])]].ffill()
        return df.fillna('')
    except Exception as e:
        logger.error(f"Clean Error: {e}")
        return df

def process_single_sheet_task(sheet_name, df, download_url, unique_filename):
    """子进程任务：生成 Sheet 的 HTML 片段"""
    try:
        df = clean_dataframe(df)
        if df is None or df.empty: return None

        # 锚点 ID：用于前端直接定位跳转
        unique_id = uuid.uuid4().hex[:8]
        safe_sheet_id = f"sheet_{unique_id}"

        # 1. RAG 语义注入层
        rag_df = df.head(MAX_RAG_ROWS)
        md_content = rag_df.to_markdown(index=False, tablefmt="pipe")
        summary_lines = []
        headers = [str(h) for h in df.columns.tolist()]
        for i, row in df.head(50).iterrows(): 
            parts = [f"{col}:{str(val).strip()}" for col, val in zip(headers, row) if str(val).strip()]
            if parts: summary_lines.append(f"来源:{sheet_name} | 行:{i+1} | " + " , ".join(parts))

        rag_layer_html = f"""
        <div id="rag-{safe_sheet_id}" style="display:none; height:0; overflow:hidden;">
            <p>Download: {download_url}</p>
            <p>Identity: {unique_filename}</p>
            {"".join([f"<p>{line}</p>" for line in summary_lines])}
            <pre>{md_content}</pre>
        </div>
        """

        # 2. 预览层 (Base64 处理以防乱码)
        preview_df = df.head(MAX_PREVIEW_ROWS)
        raw_html = preview_df.to_html(index=False, border=0, escape=False)
        raw_html = re.sub(r' (style|class)="[^"]*"', '', raw_html)
        base64_str = base64.b64encode(raw_html.encode('utf-8')).decode('utf-8')

        # 3. 组装片段，带 [下载原件] 链接
        sheet_fragment = f"""
        <div class="sheet-container" id="{safe_sheet_id}">
            <h2 class="sheet-title">
                {sheet_name} 
                <a href="{download_url}" class="download-btn">[下载原件]</a>
            </h2>
            {rag_layer_html}
            <div id="view-{safe_sheet_id}"><div class="loading-box">⚡ 正在解码表格数据...</div></div>
            <script>
                (function() {{
                    var b64 = "{base64_str}";
                    try {{
                        var html = decodeURIComponent(escape(window.atob(b64)));
                        setTimeout(function() {{ document.getElementById("view-{safe_sheet_id}").innerHTML = html; }}, 50);
                    }} catch(e) {{ console.error("解码失败", e); }}
                }})();
            </script>
        </div>
        """
        return sheet_name, sheet_fragment, safe_sheet_id
    except Exception as e:
        return sheet_name, f"<div>Error: {str(e)}</div>", "err"

def excel_to_html_fast(file_bytes, download_url, unique_filename):
    """并行调度器：处理所有 Sheet 并返回映射关系"""
    try:
        dfs = pd.read_excel(io.BytesIO(file_bytes), sheet_name=None, header=None)
    except Exception as e:
        logger.error(f"Excel 读取失败: {e}")
        return {}, {}

    results = {}
    sheet_mapping = {}
    with ProcessPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(process_single_sheet_task, name, df, download_url, unique_filename): name for name, df in dfs.items()}
        for f in futures:
            res = f.result()
            if res:
                results[res[0]] = (res[1], res[2])
                sheet_mapping[res[0]] = res[2] # 保存 {Sheet名: ID} 供 AI 跳转
    return results, sheet_mapping

# ── 主解析接口 ────────────────────────────────────────

@app.route("/process", methods=["POST"])
def process():
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400
    
    file = request.files["file"]
    file_id = uuid.uuid4().hex[:8]
    unique_filename = f"{file_id}_{file.filename}"
    save_path = os.path.join(UPLOAD_FOLDER, unique_filename)
    
    file_content = file.read()
    with open(save_path, "wb") as f:
        f.write(file_content)

    # 网关转发地址 (3001 为管理网关端口)
    download_url = f"http://10.215.208.79:3001/api/download/{unique_filename}"

    try:
        # 1. 启动解析
        sheets_data, sheet_mapping = excel_to_html_fast(file_content, download_url, unique_filename)
        
        # 2. 生成目录 TOC
        toc_html = "<div class='file-toc'><h3>📂 文件目录 (点击跳转)</h3><ul>"
        rag_toc = f"# 文件全书目录\n**溯源下载**: {download_url}\n"
        for name, (content, sheet_id) in sheets_data.items():
            toc_html += f"<li><a href='#{sheet_id}'>{name}</a></li>"
            rag_toc += f"- {name}\n"
        toc_html += f"</ul><div class='toc-footer'><a href='{download_url}'>📥 下载原始 Excel 文件</a></div></div>"

        # 3. 拼接 Body
        combined_body = "\n<hr class='sep'>\n".join([v[0] for v in sheets_data.values()])
        
        # 4. 最终 HTML 包装 (含 CSS 锚点高亮与自动滚动脚本)
        final_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>
    body {{ font-family: sans-serif; padding: 20px; background-color: #f8fafc; color: #334155; }}
    .file-toc {{ background: #fff; padding: 15px; border-radius: 8px; border: 1px solid #cbd5e1; margin-bottom: 25px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }}
    .toc-footer {{ margin-top:10px; padding-top:10px; border-top:1px solid #eee; font-weight:bold; }}
    .sheet-container {{ background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 30px; transition: 0.3s; }}
    /* 锚点跳转后的高亮效果 */
    .sheet-container:target {{ border: 2px solid #2563eb; background-color: #eff6ff; scroll-margin-top: 20px; }}
    .sheet-title {{ border-left: 4px solid #2563eb; padding-left: 12px; font-size: 18px; color: #0f172a; display: flex; justify-content: space-between; }}
    .download-btn {{ font-size: 12px; color: #2563eb; text-decoration: none; font-weight: normal; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 15px; font-size: 13px; }}
    th, td {{ border: 1px solid #e2e8f0; padding: 8px 12px; text-align: left; }}
    th {{ background-color: #f1f5f9; position: sticky; top: 0; }}
    .sep {{ border: 1px dashed #cbd5e1; margin: 40px 0; }}
</style>
</head>
<body>
    <div style="display:none">{rag_toc}</div>
    {toc_html}
    {combined_body}
    <script>
        // 自动定位逻辑：若 URL 含有 #sheet_xxx，页面加载后自动平滑滚动
        window.onload = function() {{
            if(window.location.hash) {{
                var el = document.getElementById(window.location.hash.substring(1));
                if(el) el.scrollIntoView({{behavior: "smooth"}});
            }}
        }};
    </script>
</body>
</html>"""

        return jsonify({
            "filename": file.filename,
            "download_url": download_url,
            "combined": final_html,
            "sheet_offsets": sheet_mapping # 关键：返回给 AI 的锚点字典
        })
    except Exception as e:
        logger.error(str(e))
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)