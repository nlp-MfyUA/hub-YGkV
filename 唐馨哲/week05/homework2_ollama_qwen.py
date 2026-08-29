"""
第五周作业2: 本地安装Ollama，运行 qwen3:0.6b 并完成 SDK 调用
"""

from openai import OpenAI

# Ollama 配置
OLLAMA_BASE_URL = "http://localhost:11434/v1"
OLLAMA_API_KEY = "1111"
MODEL_NAME = "qwen3:0.6b"


def initialize_client():
    """初始化 OpenAI 客户端，指向 Ollama 的本地服务"""
    client = OpenAI(
        base_url=OLLAMA_BASE_URL,
        api_key=OLLAMA_API_KEY
    )
    return client


def chat_with_qwen(client, user_message: str, system_message: str = "你是一个有帮助的助手。") -> str:
    """
    使用 Qwen3 模型进行对话

    Args:
        client: OpenAI客户端
        user_message: 用户消息
        system_message: 系统消息

    Returns:
        模型回复内容
    """
    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message}
        ],
        temperature=0.7,  # 控制生成多样性
        max_tokens=512    # 最大生成 token 数
    )

    return response.choices[0].message.content


def test_model_list(client):
    """测试获取模型列表"""
    try:
        models = client.models.list()
        print("可用的模型列表:")
        for model in models.data:
            print(f"  - {model.id}")
    except Exception as e:
        print(f"获取模型列表失败: {e}")


def main():
    print("=" * 50)
    print("作业2: Ollama + Qwen3:0.6b SDK 调用")
    print("=" * 50)

    # 初始化客户端
    print("\n正在初始化 Ollama 客户端...")
    try:
        client = initialize_client()
        print(f"客户端初始化成功!")
        print(f"  - Base URL: {OLLAMA_BASE_URL}")
        print(f"  - Model: {MODEL_NAME}")
    except Exception as e:
        print(f"客户端初始化失败: {e}")
        return

    # 测试：显示可用模型
    print("\n检查 Ollama 服务状态...")
    test_model_list(client)

    # 执行对话测试
    print("\n" + "=" * 50)
    print("对话测试")
    print("=" * 50)

    # 测试1: 简单的问候
    print("\n【测试1】用户: 你好")
    try:
        reply = chat_with_qwen(client, "你好")
        print(f"Qwen3: {reply}")
    except Exception as e:
        print(f"调用失败: {e}")
        print("\n请确保你已经:")
        print("1. 安装了 Ollama: https://ollama.com/download")
        print("2. 启动了 Ollama 服务: ollama serve")
        print("3. 下载了 qwen3:0.6b 模型: ollama pull qwen3:0.6b")
        return

    # 测试2: 使用中文对话
    print("\n【测试2】用户: 请用一句话介绍人工智能")
    try:
        reply = chat_with_qwen(client, "请用一句话介绍人工智能")
        print(f"Qwen3: {reply}")
    except Exception as e:
        print(f"调用失败: {e}")

    # 测试3: 指定不同的系统消息
    print("\n【测试3】用户: 今天天气真好")
    try:
        system_msg = "你是一位诗人，用诗意的语言回复用户。"
        reply = chat_with_qwen(client, "今天天气真好", system_message=system_msg)
        print(f"Qwen3 (诗人模式): {reply}")
    except Exception as e:
        print(f"调用失败: {e}")

    # 测试4: 代码生成
    print("\n【测试4】用户: 用Python写一个Hello World程序")
    try:
        reply = chat_with_qwen(client, "用Python写一个Hello World程序")
        print(f"Qwen3: {reply}")
    except Exception as e:
        print(f"调用失败: {e}")

    print("\n" + "=" * 50)
    print("所有测试完成!")
    print("=" * 50)


if __name__ == "__main__":
    main()