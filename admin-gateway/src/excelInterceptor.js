/**
 * Excel 上传拦截中间件 (v4.0 适配版)
 *
 * 职责：
 * - 监听所有发往 RAGFlow 的请求
 * - 识别文件上传接口：POST /api/v1/datasets/:datasetId/documents
 * - 如果上传的是 Excel，拦截 → 调 Python 服务转 HTML → 伪装成 HTML 文件 → 转发
 * - 目标：让浏览器能直接预览表格，让 RAGFlow 能解析 HTML 结构
 */

const Busboy = require('busboy');
const FormData = require('form-data');
const axios = require('axios');
const path = require('path');

// RAGFlow 文件上传接口的路径特征
const UPLOAD_PATH_REGEX = /^\/(api\/)?v1\/(document\/upload|datasets\/[^/]+\/documents)$/;

/**
 * 处理文件名编码，确保文件名在整个流程中保持一致
 */
function sanitizeFilename(filename) {
  try {
    return decodeURIComponent(encodeURIComponent(filename));
  } catch (error2) {
    return filename;
  }
}

function isExcel(filename) {
  const ext = path.extname(filename || '').toLowerCase();
  return ext === '.xlsx' || ext === '.xls';
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/**
 * 调用 Python 预处理服务，将 Excel Buffer 转为 HTML Buffer
 */
async function preprocessExcel(processorUrl, fileBuffer, filename) {
  const form = new FormData();
  form.append('file', fileBuffer, {
    filename,
    contentType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });

  // 【优化点 1】超时时间延长至 10 分钟，防止大文件超时
  const res = await axios.post(`${processorUrl}/process`, form, {
    headers: form.getHeaders(),
    timeout: 600000, 
    maxContentLength: Infinity,
    maxBodyLength: Infinity
  });

  const { combined, sheets } = res.data;
  
  // 兼容 Python 返回空 combined 的情况
  const content = combined || (sheets ? Object.values(sheets).join("\n<hr>\n") : "");

  if (!content || !content.trim()) {
    throw new Error('预处理结果为空，Excel 可能没有有效数据');
  }

  const sheetNames = sheets ? Object.keys(sheets) : [];
  
  const sanitizedFilename = sanitizeFilename(filename);
  const lastDotIndex = sanitizedFilename.lastIndexOf('.');
  const baseName = lastDotIndex > 0 ? sanitizedFilename.substring(0, lastDotIndex) : sanitizedFilename;
  
  // 【关键修改 2】后缀名改为 .html
  // 这样 RAGFlow 存储的文件名就是 xxx.html，浏览器才会尝试渲染它
  const newFilename = baseName + '.html';

  return {
    buffer: Buffer.from(content, 'utf-8'),
    filename: newFilename,
    sheetCount: sheetNames.length,
    sheetNames,
  };
}

/**
 * 解析 multipart 请求
 */
function parseMultipart(req) {
  return new Promise((resolve, reject) => {
    const bb = Busboy({ 
      headers: req.headers,
      defParamCharset: 'utf8' 
    });
    const fields = {};
    const files = []; // 这里用数组，因为 Busboy 可能多次触发 file 事件

    bb.on('field', (name, val) => {
      fields[name] = val;
    });

    bb.on('file', (fieldname, stream, info) => {
      const chunks = [];
      stream.on('data', chunk => chunks.push(chunk));
      stream.on('end', () => {
        files.push({
          fieldname,
          filename: info.filename,
          buffer: Buffer.concat(chunks),
          mimetype: info.mimeType,
        });
      });
    });

    bb.on('finish', () => resolve({ fields, files }));
    bb.on('error', reject);
    req.pipe(bb);
  });
}

/**
 * 将处理后的数据重新组装成 multipart，转发给 RAGFlow
 */
async function forwardToRagflow(ragflowUrl, req, files, fields) {
  const form = new FormData();

  // 附加所有普通字段
  for (const [key, val] of Object.entries(fields)) {
    form.append(key, val);
  }

  // 附加所有文件
  for (const file of files) {
    form.append(file.fieldname, file.buffer, {
      filename: file.filename,
      contentType: file.mimetype, // 这里会使用我们修改后的 text/html
    });
  }

  // 提取原始 headers (过滤掉 Content-Type 等由 FormData 自动生成的头)
  const forwardHeaders = {};
  for (const [key, val] of Object.entries(req.headers)) {
    const k = key.toLowerCase();
    if (k !== 'content-type' && k !== 'content-length' && k !== 'host' && k !== 'connection') {
      forwardHeaders[key] = val;
    }
  }

  const res = await axios.post(
    `${ragflowUrl}${req.path}`,
    form,
    {
      headers: { ...forwardHeaders, ...form.getHeaders() },
      params: req.query,
      timeout: 600000, // 转发也要加时
      maxBodyLength: Infinity,
    }
  );

  return res;
}

/**
 * 创建 Excel 拦截中间件
 */
function createExcelInterceptor(ragflowUrl, processorUrl) {
  return async function excelInterceptor(req, res, next) {
    // 1. 判断是否拦截
    const isUploadPath = UPLOAD_PATH_REGEX.test(req.path);
    const isPost = req.method === 'POST';
    const contentType = req.headers['content-type'] || '';
    const isMultipart = contentType.includes('multipart/form-data');

    if (!isUploadPath || !isPost || !isMultipart) {
      return next(); 
    }

    console.log(`[intercept] 捕获上传请求: ${req.path}`);

    // 2. 解析原始请求
    let parsed;
    try {
      parsed = await parseMultipart(req);
    } catch (err) {
      console.error('[intercept] multipart 解析失败:', err.message);
      return res.status(400).json({ error: '请求解析失败', detail: err.message });
    }

    const { fields, files } = parsed;
    const excelFiles = files.filter(f => isExcel(f.filename));
    const otherFiles = files.filter(f => !isExcel(f.filename));

    // 3. 无 Excel 直接透传
    if (excelFiles.length === 0) {
      console.log(`[intercept] 无 Excel 文件，直接转发`);
      try {
        const result = await forwardToRagflow(ragflowUrl, req, files, fields);
        return res.status(result.status).json(result.data);
      } catch (err) {
        const status = err.response?.status || 502;
        return res.status(status).json(err.response?.data || { error: err.message });
      }
    }

    // 4. 有 Excel，调 Python 服务处理
    console.log(`[intercept] 发现 ${excelFiles.length} 个 Excel 文件，开始转 HTML 处理`);
    const processedFiles = [...otherFiles];

    for (const file of excelFiles) {
      const sanitizedFilename = sanitizeFilename(file.filename);
      console.log(`[intercept] 处理: ${sanitizedFilename} (${formatSize(file.buffer.length)})`);
      
      try {
        // 调用预处理
        const result = await preprocessExcel(processorUrl, file.buffer, sanitizedFilename);
        
        console.log(
          `[intercept] ✓ ${sanitizedFilename} → ${result.filename}` +
          ` (类型: HTML, Sheet数: ${result.sheetCount})`
        );
        
        processedFiles.push({
          fieldname: file.fieldname,
          filename: result.filename, // xxx.html
          buffer: result.buffer,
          // 【关键修改 3】MIME类型必须是 text/html
          // 只有这样，浏览器在访问文件链接时，才会尝试渲染而不是下载
          mimetype: 'text/html', 
        });

      } catch (err) {
        console.error(`[intercept] ✗ ${file.filename} 预处理失败:`, err.message);
        return res.status(422).json({
          error: `Excel 预处理失败: ${file.filename}`,
          detail: err.message,
        });
      }
    }

    // 5. 转发给 RAGFlow
    try {
      console.log(`[intercept] 转发处理后文件到 RAGFlow`);
      const result = await forwardToRagflow(ragflowUrl, req, processedFiles, fields);
      console.log(`[intercept] ✓ RAGFlow 响应: ${result.status}`);
      return res.status(result.status).json(result.data);
    } catch (err) {
      console.error('[intercept] 转发失败:', err.message);
      const status = err.response?.status || 502;
      return res.status(status).json(err.response?.data || { error: err.message });
    }
  };
}

module.exports = { createExcelInterceptor };