require('dotenv').config();

const express = require('express');
const { createProxyMiddleware } = require('http-proxy-middleware');
const { createExcelInterceptor } = require('./excelInterceptor');

const app = express();
const PORT = process.env.ADMIN_GATEWAY_PORT || 3001;
const RAGFLOW_URL = process.env.RAGFLOW_BASE_URL;
const PROCESSOR_URL = process.env.EXCEL_PROCESSOR_URL;

if (!RAGFLOW_URL) {
  console.error('[gateway] 错误: 缺少 RAGFLOW_BASE_URL 环境变量');
  process.exit(1);
}

// ── 1. Excel 拦截中间件（优先于反向代理）──────────────
// 只处理 POST /api/v1/datasets/:id/documents 且包含 Excel 的请求
app.use(createExcelInterceptor(RAGFLOW_URL, PROCESSOR_URL));

// ── 2. 其余所有请求透传给 RAGFlow ────────────────────
app.use(
  '/',
  createProxyMiddleware({
    target: RAGFLOW_URL,
    changeOrigin: true,
    // WebSocket 支持（RAGFlow 对话流式输出用到）
    ws: true,
    on: {
      error: (err, req, res) => {
        console.error('[proxy] 转发错误:', err.message);
        if (res && !res.headersSent) {
          res.status(502).json({ error: '代理转发失败', detail: err.message });
        }
      },
    },
  })
);

const server = app.listen(PORT, () => {
  console.log(`
╔══════════════════════════════════════════════════╗
║         RAGFlow 反向代理网关已启动                 ║
╠══════════════════════════════════════════════════╣
║  访问地址:   http://localhost:${PORT}               ║
║  代理目标:   ${RAGFLOW_URL}
║  预处理服务: ${PROCESSOR_URL || '(未配置，Excel将直接透传)'}
╚══════════════════════════════════════════════════╝

使用方式:
  把浏览器访问地址从 ${RAGFLOW_URL}
  改为              http://localhost:${PORT}
  其他操作完全不变，Excel 上传会自动拦截预处理
  `);
});

// WebSocket 代理支持
server.on('upgrade', (req, socket, head) => {
  const proxy = createProxyMiddleware({
    target: RAGFLOW_URL,
    changeOrigin: true,
    ws: true,
  });
  proxy.upgrade(req, socket, head);
});

module.exports = app;
