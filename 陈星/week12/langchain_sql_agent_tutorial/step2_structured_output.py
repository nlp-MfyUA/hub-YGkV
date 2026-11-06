"""第 2 步：用 LangChain + Pydantic 做一次最小的结构化 Agent 调用。"""
import os
from pathlib import Path
from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from db_tools import SQLiteTools

load_dotenv(Path(__file__).with_name(".env"))


class TableChoice(BaseModel):
    tables: list[str] = Field(description="需要查询的真实数据库表名")
    reason: str = Field(description="为什么选择这些表")


if not os.getenv("OPENAI_API_KEY"):
    raise RuntimeError("请先在 .env 文件中配置 OPENAI_API_KEY")

db = SQLiteTools(Path(__file__).with_name("chinook.db"))
llm = ChatOpenAI(
    model=os.getenv("LLM_MODEL", "qwen-plus"),
    base_url=os.getenv(
        "OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
    ),
    temperature=0,
)
prompt = ChatPromptTemplate.from_messages([
    ("system", "你负责选表，不写 SQL。只从给定 schema 选择表。"
               "请调用 TableChoice 工具返回结果。"),
    ("human", "数据库结构：\n{schema}\n\n用户问题：{question}"),
])

# 这是 OpenAI Agents 的 output_type 在 LangChain 里的核心替代写法：
chain = prompt | llm.bind_tools([TableChoice], tool_choice="auto")
message = chain.invoke({
    "schema": db.catalog_text(),
    "question": "哪位歌手拥有最多专辑？",
})

for tool_call in message.tool_calls:
    if tool_call["name"] == "TableChoice":
        plan = TableChoice.model_validate(tool_call["args"])
        print("选中的表:", plan.tables)
        print("理由:", plan.reason)
        break
else:
    print("模型没有发起工具调用，原始输出:", message.content)
