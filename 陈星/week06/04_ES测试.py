import requests
import json

# 替换为你的 Elasticsearch 地址
ELASTICSEARCH_URL = "http://127.0.0.1:9200"

# 如果启用了安全认证，请填写用户名和密码
# AUTH = ('elastic', 'your_password')
AUTH = None

# 如果使用 HTTPS 且证书未验证，可以关闭证书验证 (仅用于开发和测试)
VERIFY_SSL = False


def make_request(method, endpoint, data=None):
    """通用请求函数，处理 URL、认证和异常"""
    url = f"{ELASTICSEARCH_URL}/{endpoint}"
    headers = {'Content-Type': 'application/json'}
    try:
        if data:
            response = requests.request(
                method, url, headers=headers, json=data, auth=AUTH, verify=VERIFY_SSL
            )
        else:
            response = requests.request(
                method, url, headers=headers, auth=AUTH, verify=VERIFY_SSL
            )
        response.raise_for_status()  # 如果请求失败（非2xx），抛出 HTTPError 异常
        return response.json()
    except requests.exceptions.HTTPError as err:
        print(f"HTTP 错误：{err}")
        print(f"响应内容：{err.response.text}")
    except requests.exceptions.RequestException as err:
        print(f"请求失败：{err}")
    return None


def test_connection():
    """测试 Elasticsearch 连接和 Ping"""
    print("--- 正在测试 Elasticsearch 连接 ---")
    response = make_request('GET', '')
    if response:
        print("连接成功！")
        print(json.dumps(response, indent=2, ensure_ascii=False))


def test_common_analyzers():
    """测试常见的 Elasticsearch 内置分词器"""
    print("\n--- 正在测试常见的 Elasticsearch 内置分词器 ---")
    test_text = "Hello, world! This is a test."
    analyzers = ["standard", "simple", "whitespace", "english"]

    for analyzer in analyzers:
        print(f"\n使用分词器：{analyzer}")
        data = {
            "analyzer": analyzer,
            "text": test_text
        }
        response = make_request('POST', '_analyze', data=data)
        if response and 'tokens' in response:
            tokens = [token['token'] for token in response['tokens']]
            print(f"原始文本: '{test_text}'")
            print(f"分词结果: {tokens}")


def test_ik_analyzers():
    """测试 IK 分词器"""
    print("\n--- 正在测试 IK 分词器 ---")
    test_text_zh = "我在使用Elasticsearch，这是我的测试。"
    ik_analyzers = ["ik_smart", "ik_max_word"]

    for analyzer in ik_analyzers:
        print(f"\n使用 IK 分词器：{analyzer}")
        data = {
            "analyzer": analyzer,
            "text": test_text_zh
        }
        response = make_request('POST', '_analyze', data=data)
        if response and 'tokens' in response:
            tokens = [token['token'] for token in response['tokens']]
            print(f"原始文本: '{test_text_zh}'")
            print(f"分词结果: {tokens}")


if __name__ == "__main__":
    # 执行所有测试
    test_connection()
    print("\n" + "=" * 50)
    test_common_analyzers()
    print("\n" + "=" * 50)
    test_ik_analyzers()