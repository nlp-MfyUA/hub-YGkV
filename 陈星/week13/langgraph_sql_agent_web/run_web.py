"""一条命令启动前后端。默认只监听本机，不对公网开放。"""
import argparse
import os

import uvicorn


def main():
    parser = argparse.ArgumentParser(description="SQL Agent 网页")
    parser.add_argument("--mode", choices=("mock", "llm"), default="mock")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="开发时热更新")
    args = parser.parse_args()

    os.environ["SQL_AGENT_MODE"] = args.mode
    print(f"打开浏览器：http://{args.host}:{args.port}")
    print(f"模式：{args.mode}（mock 不需要 API Key；llm 使用 .env）")
    uvicorn.run(
        "web_app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
