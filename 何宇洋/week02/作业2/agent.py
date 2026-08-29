import json

from schemas import RelationshipResult
from llm import chat


def run_agent(text: str):

    message = chat(text)


    # LLM选择调用工具
    if message.tool_calls:

        tool_call = message.tool_calls[0]


        arguments = json.loads(
            tool_call.function.arguments
        )


        graph = RelationshipResult(
            **arguments
        )


        return {
            "type": "relationship",
            "data": graph,
            "content":message.content  # 用于调试
        }


    # LLM认为无需调用工具
    else:

        return {
            "type": "no_relation",
            "content":message.content   # 用于调试
        }