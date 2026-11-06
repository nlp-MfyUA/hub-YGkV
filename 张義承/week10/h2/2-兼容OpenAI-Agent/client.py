import os

# https://bailian.console.aliyun.com/?tab=model#/api-key
# os.environ["OPENAI_API_KEY"] = "sk-a581e3621c3c4f5d9429f8a2de31b860"
# os.environ["OPENAI_BASE_URL"] = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_api_key = os.environ.get("DEEPSEEK_API_KEY")
os.environ["OPENAI_API_KEY"] = _api_key
os.environ["OPENAI_BASE_URL"] = "https://api.deepseek.com"

import asyncio
from agents import Agent, Runner, AsyncOpenAI, OpenAIChatCompletionsModel
from agents.mcp import MCPServer
from agents.mcp.server import MCPServerSse
from agents import set_default_openai_api, set_tracing_disabled

set_default_openai_api("chat_completions")
set_tracing_disabled(True)


# 测试用例：每加一个用例，就加一行
TEST_MESSAGES = [
    "最近有什么新闻？",
    "摇3次骰子得到结果。",  # tool 11 17 13
    "现在北京时间几点？",
    "帮我算一下 12.5 乘以 8",
    "北京天气怎么样？",
    "查一下上海天气，再算 100 减 37",  # 一次触发两个工具
]


async def test_agent(agent: Agent) -> None:
    """逐个跑 TEST_MESSAGES，打印模型实际调用了哪些工具和最终回答。"""
    # 这一步就是下面注释里的 step1：向 mcp server 要工具清单
    for server in agent.mcp_servers:
        tools = await server.list_tools()
        print(f"\n[{server.name}] 注册了 {len(tools)} 个工具：")
        for t in tools:
            params = list((t.inputSchema or {}).get("properties", {}))
            print(f"  - {t.name}({', '.join(params)}) — {t.description}")

    for message in TEST_MESSAGES:
        print(f"\n{'=' * 60}")
        print(f"Running: {message}")
        result = await Runner.run(starting_agent=agent, input=message)
        # 等同于：工具选择、工具调用、工具回答的总结

        """
        step1，通过mcp client mcp list tool，得到mcp server 可选的工具、工具的参数、返回格式
        step2， 工具、工具的参数、返回格式 汇总为 tools / function call 的格式 通过大模型 选择一个工具 -》 传入参数
        step3, 通过mcp client 调用execute tool 在mcp server 执行这个工具 -》 返回结果
        step4， 返回结果汇总在提示词，调用大模型得到结果
        """

        # 中间过程：ToolCallItem = 模型发起工具调用，ToolCallOutputItem = 工具返回结果
        for item in result.new_items:
            print("  -", type(item).__name__, getattr(item, "raw_item", ""))
        print("=>", result.final_output)


async def run(mcp_server: MCPServer):
    external_client = AsyncOpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=os.environ["OPENAI_BASE_URL"],
    )

    # openai agent
    agent = Agent(
        name="Assistant",
        instructions="你是一个助手。凡是涉及时间、天气、计算的问题，必须先调用可用工具获取结果，不要凭记忆回答。",
        mcp_servers=[mcp_server],  # tools
        model=OpenAIChatCompletionsModel(
            model="deepseek-v4-flash",
            openai_client=external_client,
        ),
    )

    # 人传入tool，function call execute tool
    await test_agent(agent)


async def main():
    # 定义了远程 mcp server 链接方式
    async with MCPServerSse(
        name="SSE Python Server",
        params={
            "url": "http://localhost:8000/sse",  # mcp server 通过http 方式沟通
        },
    ) as server:
        await run(server)


if __name__ == "__main__":
    asyncio.run(main())
