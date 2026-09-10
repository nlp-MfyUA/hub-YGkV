"""隔离同步检索，主进程可在预算耗尽时终止，不留下后台检索线程。"""
import json
import sys


def main():
    from ddgs import DDGS
    from ddgs.exceptions import DDGSException, RatelimitException, TimeoutException

    request = json.loads(sys.stdin.buffer.read())
    try:
        results = DDGS(timeout=10).text(request["query"], max_results=5, backend="auto")
        result = {"results": [
            {"url": r["href"], "title": r.get("title", "")} for r in results[:5]
        ]}
    except (RatelimitException, TimeoutException):
        result = {"error": "检索暂不可用", "transient": True}
    except DDGSException:
        result = {"error": "检索失败或无结果", "transient": False}
    except Exception:
        result = {"error": "检索组件异常", "transient": False}
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))


if __name__ == "__main__":
    main()
