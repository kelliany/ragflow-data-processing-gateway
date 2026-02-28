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
// ── 1. 最优先：强制拦截下载请求 ────────────────────────
// 放在所有中间件的最前面，确保流量第一时间被分流到 5001
app.use('/api/download', createProxyMiddleware({
    target: PROCESSOR_URL || 'http://excel-processor:5001',
    changeOrigin: true,
    pathRewrite: {
        '^/api/download': '/',  // 将 /api/download 改写为 /download 发给后端
    },
    onProxyReq: (proxyReq, req, res) => {
        console.log(`[Gateway] 转发中: ${req.originalUrl} -> ${proxyReq.path}`);
    }
}));

// ── 2. 其次：Excel 上传拦截中间件 ──────────────────────
// 确保这个中间件内部只对 POST /v1/document/upload 动作做处理
// 并且在其他所有情况下都必须执行 next()
app.use(createExcelInterceptor(RAGFLOW_URL, PROCESSOR_URL));

// ── 3. 最后：兜底透传 RAGFlow ────────────────────────
app.use(
  '/',
  createProxyMiddleware({
    target: RAGFLOW_URL,
    changeOrigin: true,
    ws: true,
    onProxyReq: (proxyReq, req, res) => {
        // 如果漏到了这里，说明前面的 /api/download 没接住
        if (req.url.includes('/api/download')) {
            console.warn(`[Proxy-Warning] 下载请求漏到了 RAGFlow 层: ${req.url}`);
        }
    }
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
