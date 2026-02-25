"""
app.py - 极速 Excel 处理器 v6.0 (Base64双模 + 全局TOC + 完美UTF-8)
核心逻辑：
1. RAG端：通过 display:none 提供带上下文的 Markdown，解决多表混淆。
2. 浏览器端：通过 Base64 + JS 动态渲染 HTML 表格，完美还原样式且不消耗 Token。
3. 架构优化：采用 Fragment 模式，主进程统一封装 HTML 头，彻底根除乱码。
"""
from flask import Flask, request, jsonify
import pandas as pd
import io
import time
import logging
import warnings
import base64
import re
import uuid
from concurrent.futures import ProcessPoolExecutor

# 忽略 pandas 的一些警告
warnings.filterwarnings('ignore')

app = Flask(__name__)
# 【关键配置】确保 JSON 返回中文时不乱码
app.config['JSON_AS_ASCII'] = False

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 配置
MAX_RAG_ROWS = 1000       # RAG 读取的行数限制 (Markdown)
MAX_PREVIEW_ROWS = 3000   # 浏览器预览的行数限制 (HTML)
# ── 新增：健康检查接口 ──────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    """用于 Docker Healthcheck 探测服务状态"""
    return jsonify({
        "status": "healthy",
        "timestamp": time.time(),
        "service": "excel-processor"
    }), 200

# ── 核心逻辑 ──────────────────────────────────────────

def clean_dataframe(df):
    """
    智能清洗 DataFrame：处理合并单元格、空行、多级表头
    """
    try:
        # 1. 移除全空的行和列
        df = df.dropna(how='all', axis=0).dropna(how='all', axis=1)
        if df.empty: return df

        # 2. 处理表头 (Heuristic)
        if len(df) > 1:
            try:
                row0_empty_ratio = df.iloc[0].isna().sum() / df.shape[1]
                if row0_empty_ratio < 0.5:
                    # 策略 A: 单行表头
                    df.columns = df.iloc[0].astype(str).fillna('')
                    df = df.iloc[1:]
                else:
                    # 策略 B: 复杂表头合并
                    headers_row0 = df.iloc[0].ffill()
                    headers_row1 = df.iloc[1]
                    new_headers = []
                    for h0, h1 in zip(headers_row0, headers_row1):
                        h0 = str(h0) if pd.notna(h0) else ""
                        h1 = str(h1) if pd.notna(h1) else ""
                        if h0 and h1 and h0 != h1:
                            new_headers.append(f"{h0}_{h1}")
                        else:
                            new_headers.append(h1 if h1 else h0)
                    df.columns = new_headers
                    df = df.iloc[2:]
            except Exception:
                pass 

        # 3. 对左侧关键列做向下填充 (解决合并单元格)
        if not df.empty and df.shape[1] > 0:
            cols_to_fill = df.columns[:min(2, df.shape[1])]
            df[cols_to_fill] = df[cols_to_fill].ffill()

        # 4. 全局清洗
        df = df.fillna('')
        return df
    except Exception as e:
        logger.error(f"Data Cleaning Error: {e}")
        return df

def process_single_sheet_task(sheet_name, df):
    """
    子进程任务：生成 Sheet 内容片段 (Fragment)
    """
    try:
        df = clean_dataframe(df)
        if df is None or df.empty: return None

        # 生成唯一 ID，防止 JS 变量冲突
        unique_id = uuid.uuid4().hex[:8]
        safe_sheet_id = f"sheet_{unique_id}"

        # ---------------------------------------------------------
        # 🟢 层级 1: RAG 专用层 (Context Injection)
        # ---------------------------------------------------------
        
        # A. 生成 Markdown 表格 (给 AI 看)
        rag_df = df.head(MAX_RAG_ROWS)
        md_content = rag_df.to_markdown(index=False, tablefmt="pipe")
        
        # B. 生成强上下文语义摘要
        summary_lines = []
        try:
            headers = [str(h) for h in df.columns.tolist()]
            # 取前 50 行做高密度摘要
            for i, row in df.head(50).iterrows(): 
                parts = []
                for col, val in zip(headers, row):
                    if str(val).strip():
                        parts.append(f"{col}:{str(val).strip()}")
                if parts:
                    # 【核心】每一行注入 Sheet 名，防止切片后上下文丢失
                    row_context = f"来源表:{sheet_name} | 行号:{i+1} | "
                    summary_lines.append(row_context + " , ".join(parts))
        except Exception:
            pass

        rag_summary_block = ""
        if summary_lines:
            rag_summary_block = (
                f"\n\n### 【{sheet_name}】关键数据语义摘要：\n" + 
                "\n".join(summary_lines)
            )

        # 组合 RAG 片段 (Markdown + 摘要)
        # 用 hidden div 包裹，浏览器隐藏，RAG 解析器抓取
        rag_layer_html = f"""
        <div id="rag-{safe_sheet_id}" style="display:none; height:0; overflow:hidden;">
            <h1>数据表：{sheet_name}</h1>
            {rag_summary_block}
            \n\n
            ### 表格原文 (Markdown)：
            {md_content}
        </div>
        """

        # ---------------------------------------------------------
        # 🟢 层级 2: 浏览器预览层 (Base64 Trojan)
        # ---------------------------------------------------------
        
        # 生成 HTML 表格
        preview_df = df.head(MAX_PREVIEW_ROWS)
        raw_html_table = preview_df.to_html(index=False, border=0, classes=None, escape=False)
        
        # 清洗 Pandas 样式
        raw_html_table = re.sub(r' style="[^"]*"', '', raw_html_table)
        raw_html_table = re.sub(r' class="[^"]*"', '', raw_html_table)
        
        # 转 Base64
        html_bytes = raw_html_table.encode('utf-8')
        base64_str = base64.b64encode(html_bytes).decode('utf-8')

        # 截断提示
        warning_msg = ""
        if len(df) > MAX_PREVIEW_ROWS:
            warning_msg = f"<p class='warning-text'>(注：数据过长，仅展示前 {MAX_PREVIEW_ROWS} 行，AI 已读取更多数据)</p>"

        # ---------------------------------------------------------
        # 🟢 层级 3: 组装 Sheet 片段 (不含 html/head/body 标签)
        # ---------------------------------------------------------
        sheet_fragment = f"""
        <div class="sheet-container" id="{safe_sheet_id}">
            <h2 class="sheet-title">{sheet_name}</h2>
            {warning_msg}

            {rag_layer_html}

            <div id="view-{safe_sheet_id}">
                <div class="loading-box">⚡ 正在解码表格...</div>
            </div>

            <script>
                (function() {{
                    var b64Data = "{base64_str}";
                    var targetId = "view-{safe_sheet_id}";
                    try {{
                        var decodedHtml = decodeURIComponent(escape(window.atob(b64Data)));
                        setTimeout(function() {{
                            var el = document.getElementById(targetId);
                            if(el) el.innerHTML = decodedHtml;
                        }}, 50);
                    }} catch (e) {{
                        console.error("Decode error", e);
                        var el = document.getElementById(targetId);
                        if(el) el.innerHTML = "<p style='color:red'>解码失败</p>";
                    }}
                }})();
            </script>
        </div>
        """
        return sheet_name, sheet_fragment, safe_sheet_id

    except Exception as e:
        return sheet_name, f"<div class='error'>Sheet: {sheet_name} 处理失败: {str(e)}</div>", f"error_{uuid.uuid4().hex[:8]}"

def excel_to_html_fast(file_bytes, filename):
    start_time = time.time()
    
    # 强制使用 calamine 引擎
    try:
        dfs = pd.read_excel(io.BytesIO(file_bytes), sheet_name=None, header=None, engine='calamine')
    except ImportError:
        logger.error("缺少 python-calamine，回退到 openpyxl")
        dfs = pd.read_excel(io.BytesIO(file_bytes), sheet_name=None, header=None)
    except Exception as e:
        logger.error(f"读取失败: {e}")
        try:
            dfs = pd.read_excel(io.BytesIO(file_bytes), sheet_name=None, header=None)
        except Exception as final_e:
            raise ValueError(f"无法读取 Excel 文件: {final_e}")

    # 并行处理
    results = {}
    if len(dfs) > 1:
        with ProcessPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(process_single_sheet_task, name, df): name for name, df in dfs.items()}
            for future in futures:
                try:
                    name, content, sheet_id = future.result()
                    if content: results[name] = (content, sheet_id)
                except Exception: pass
    else:
        for name, df in dfs.items():
            _, content, sheet_id = process_single_sheet_task(name, df)
            if content: results[name] = (content, sheet_id)

    logger.info(f"转换耗时: {time.time() - start_time:.2f}s")
    return results

# ── 路由 ──────────────────────────────────────────────

@app.route("/process", methods=["POST"])
def process():
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400
    file = request.files["file"]
    
    try:
        sheets_data = excel_to_html_fast(file.read(), file.filename)
        
        # 🟢 1. 生成全局目录 (TOC)
        toc_html = "<div class='file-toc'>"
        toc_html += "<h3>📂 文件目录 (点击跳转)</h3><ul>"
        rag_toc = "# 文件全书目录\n" # 给 RAG 用的
        
        for name, sheet_info in sheets_data.items():
            sheet_fragment, safe_sheet_id = sheet_info
            toc_html += f"<li><a href='#{safe_sheet_id}' style='text-decoration: none; color: #2563eb;'>{name}</a></li>"
            rag_toc += f"- {name}\n"
        
        toc_html += "</ul></div>"
        
        # 🟢 2. 拼接所有 Sheet 片段
        separator = "\n<hr class='sheet-separator'>\n"
        combined_body = separator.join([sheet_info[0] for sheet_info in sheets_data.values()])
        
        # 🟢 3. 构建唯一的全局 HTML 外壳 (解决乱码的关键！)
        final_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{file.filename} - 预览</title>
<style>
    /* 全局重置与基础样式 */
    body {{ font-family: "Microsoft YaHei", -apple-system, sans-serif; padding: 20px; background-color: #f8fafc; color: #334155; }}
    
    /* 目录样式 */
    .file-toc {{ background: #fff; padding: 15px 20px; border-radius: 8px; border: 1px solid #cbd5e1; margin-bottom: 30px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }}
    .file-toc h3 {{ margin-top: 0; font-size: 16px; color: #1e293b; border-bottom: 1px solid #e2e8f0; padding-bottom: 10px; }}
    .file-toc ul {{ padding-left: 20px; margin-bottom: 0; }}
    .file-toc li {{ margin-bottom: 4px; color: #2563eb; }}

    /* Sheet 容器样式 */
    .sheet-container {{ background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 30px; }}
    .sheet-title {{ border-left: 4px solid #2563eb; padding-left: 12px; margin-top: 0; font-size: 18px; color: #0f172a; }}
    .sheet-separator {{ border: 0; border-top: 2px dashed #cbd5e1; margin: 40px 0; }}
    .warning-text {{ color: #ef4444; font-size: 12px; }}
    
    /* 动态表格样式 */
    table {{ border-collapse: collapse; width: 100%; margin-top: 15px; font-size: 13px; }}
    th, td {{ border: 1px solid #e2e8f0; padding: 8px 12px; text-align: left; }}
    th {{ background-color: #f1f5f9; font-weight: 600; color: #334155; position: sticky; top: 0; z-index: 10; }}
    tr:nth-child(even) {{ background-color: #f8fafc; }}
    tr:hover {{ background-color: #eff6ff; }}

    /* 加载动画 */
    .loading-box {{ padding: 20px; text-align: center; color: #64748b; background: #f1f5f9; border-radius: 4px; font-size: 13px; }}
</style>
</head>
<body>

    <div style="display:none">
    {rag_toc}
    </div>

    {toc_html}

    {combined_body}

</body>
</html>
"""
        
        if not sheets_data:
            final_html = "<html><head><meta charset='utf-8'></head><body><h3>空文件或解析失败</h3></body></html>"

        # 4. 返回 JSON (强制 UTF-8)
        response = jsonify({
            "filename": file.filename,
            "sheets": sheets_data,
            "combined": final_html
        })
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        return response

    except Exception as e:
        logger.error(str(e))
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)