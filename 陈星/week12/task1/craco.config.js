const CopyPlugin = require("copy-webpack-plugin");

const API_TARGET = process.env.API_TARGET || "http://127.0.0.1:3001";
const API_PORT = new URL(API_TARGET).port || "80";
/* 代理转发时打上的标记，用来识别“请求被代理回了自己” */
const PROXY_HOP_HEADER = "x-dev-proxy-hop";

module.exports = {
  webpack: {
    plugins: {
      add: [
        new CopyPlugin({
          // onnxruntime-web 需要把 wasm 文件复制到构建产物中
          patterns: [
            { from: "node_modules/onnxruntime-web/dist/*.wasm", to: "static/js/[name][ext]" },
          ],
        }),
      ],
    },
  },

  devServer: (devServerConfig) => {
    const next = { ...devServerConfig };

    next.allowedHosts = 'all';
    
    // 显式声明 /api 代理，并带上标记头，方便下面检测自我代理
    next.proxy = [
      {
        context: ["/api"],
        target: API_TARGET,
        changeOrigin: true,
        onProxyReq: (proxyReq) => {
          proxyReq.setHeader(PROXY_HOP_HEADER, "1");
        },
      },
    ];

    const previousBefore = next.onBeforeSetupMiddleware;
    next.onBeforeSetupMiddleware = (devServer) => {
      // 端口被占用时 CRA 会自动顺延端口。如果顺延到了 3001（后端 API 端口），
      // /api 请求会被代理回自己，形成无限代理循环，最终 Node 返回 431。
      // 这里提前拦下并给出明确提示，而不是让前端显示“无法获取服务配置”。
      devServer.app.use((req, res, middlewareNext) => {
        if (!req.url.startsWith("/api") || !req.headers[PROXY_HOP_HEADER]) {
          return middlewareNext();
        }

        const port = devServer.options?.port ?? process.env.PORT ?? "?";
        res.statusCode = 503;
        res.setHeader("Content-Type", "application/json; charset=utf-8");
        res.end(
          JSON.stringify({
            error:
              `开发服务器端口（${port}）与后端 API 端口（${API_PORT}）相同，` +
              `/api 请求被代理回自己。请先停掉占用 ${API_PORT} 的进程再 npm start，` +
              `或用 PORT=3002 npm start 换一个前端端口。`,
          })
        );
      });

      if (typeof previousBefore === "function") previousBefore(devServer);
    };

    return next;
  },
};
