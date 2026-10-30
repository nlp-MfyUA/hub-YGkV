import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./style/index.css";

// 注意：不要用 StrictMode 包裹。
// React 18 的开发模式会重复挂载组件，导致 getUserMedia 被并发调用两次，
// 部分浏览器/系统会把第二次请求挂住，表现为“打开摄像头后一直转圈”。
const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(<App />);
