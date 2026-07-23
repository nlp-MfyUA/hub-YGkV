import json
from openai import OpenAI
from dotenv import load_dotenv
import os
from pathlib import Path

K_ENV_PATH=Path(__file__).resolve().cwd() / "llm.deepseek.env"
K_LLM_API_KEY="LLM_API_KEY"
K_LLM_BASE_URL="LLM_BASE_URL"
K_LLM_MODEL="LLM_MODEL"

load_dotenv(K_ENV_PATH)

K_SYSTEM_PROMPT="""
你是一个情感分析专家，你需要根据输入的内容分析各种情感，并将对应的情感关系输出为json格式

输入：小明喜欢小姚，但是小姚喜欢小王。
输出：人物关系图谱
{
    [
        {
            "source": "小明",
            "relation": "爱慕",
            "target": "小姚"
        }
    ]
}
"""

# ── 工具函数（被 LLM 调用的实际 Python 函数） ────────────────

def ParseFile(file_path: str) -> str:
    """
    读取文件内容并返回文本字符串。

    Args:
        file_path: 文件路径

    Returns:
        文件内容的字符串形式
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()

def ConvertToJson(content: str) -> str:
    """
    将文本数据转换为标准JSON格式字符串。

    - 若输入已是合法 JSON，则格式化后返回
    - 否则将原文本包装在 {"raw_text": "..."} 中返回

    Args:
        content: 需要转换为JSON的文本内容

    Returns:
        标准JSON格式字符串
    """
    try:
        data = json.loads(content)
        return json.dumps(data, ensure_ascii=False, indent=4)
    except json.JSONDecodeError:
        result = {"raw_text": content}
        return json.dumps(result, ensure_ascii=False, indent=4)

# ── 工具定义（LLM 看到的函数描述 / Function Calling 声明） ──

K_TOOLSET_JSONMODE = [
    {
        "type": "function",
        "function": {
            "name": "ParseFile",
            "description": "读取指定路径的文件内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "要读取的文件路径"
                    }
                },
                "required": ["file_path"]
            }
        }
    }
]

K_TOOLSET_TOOLSMODE = [
    {
        "type": "function",
        "function": {
            "name": "ParseFile",
            "description": "读取指定路径的文件内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "要读取的文件路径"
                    }
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "ConvertToJson",
            "description": "将文本数据转换为标准JSON格式",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "需要转换为JSON的文本内容"
                    }
                },
                "required": ["content"]
            }
        }
    }
]

# 函数名称 → 实际 Python 可调用对象的映射
K_FUNCTION_MAP = {
    "ParseFile": ParseFile,
    "ConvertToJson": ConvertToJson,
}

class LLMClient:
    """
    情感分析智能体
    """
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None
    ):
        self.api_key = api_key or os.getenv(K_LLM_API_KEY, "")
        self.base_url = base_url or os.getenv(K_LLM_BASE_URL, "")
        self.model = model or os.getenv(K_LLM_MODEL, "")

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )

        self.memory = [
            {"role":"user", "content": K_SYSTEM_PROMPT}
        ]

    def MakeMessage(self, prompt: str | list[dict]) -> list[dict]:
        """统一将用户输入转为 messages 列表。"""
        if isinstance(prompt, str):
            return [{"role": "user", "content": prompt}]
        return prompt

    def ChatJsonMode(self, prompt: str | list[dict]):
        """JSON模式：强制模型输出JSON格式，约束输出结构。

        Args:
            prompt: 字符串（单轮）或 messages 列表（多轮/系统消息）。

        Returns:
            模型回复的JSON字符串。
        """
        # 注意MakeMessage返回的是list[dict],不能使用append
        self.memory.extend(self.MakeMessage(prompt))

        resp = self.client.chat.completions.create(
            model=self.model,
            messages=self.memory,
            response_format={"type":"json_object"},
            tools=K_TOOLSET_JSONMODE
        )

        self.memory.append({"role":"assistant", "content": resp.choices[0].message.content})
        return resp.choices[0].message.content or ""

    def ChatToolsMode(self, prompt: str | list[dict]):
        """工具模式：将 K_TOOLSET_TOOLSMODE 传递给 API，模型可选择调用工具或直接回复。

        Args:
            prompt: 字符串（单轮）或 messages 列表（多轮/系统消息）。

        Returns:
            模型回复文本。
        """
        self.memory.extend(self.MakeMessage(prompt))

        resp = self.client.chat.completions.create(
            model=self.model,
            messages=self.memory,
            tools=K_TOOLSET_TOOLSMODE
        )

        content = resp.choices[0].message.content or ""
        self.memory.append({"role": "assistant", "content": content})
        return content

    def chat(self, prompt: str | list[dict]):
        """通用对话方法（不使用强制JSON模式和工具模式）。

        Args:
            prompt: 用户输入

        Returns:
            模型回复文本。
        """
        messages = self.MakeMessage(prompt)
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
        )
        return resp.choices[0].message.content or ""

def Run(llm: LLMClient):
    try:
        while True:
            # ── 交互菜单 ────────────────────────────────────────
            print("\n" + "=" * 40)
            print("  情感分析智能体 — 请选择模式")
            print("=" * 40)
            print("  1. 通用对话模式 (chat)")
            print("  2. JSON 模式 (ChatJsonMode)")
            print("  3. 工具模式 (ChatToolsMode)")
            print("  4. 退出")
            print("=" * 40)
            mode_choice = input("请输入编号 (1/2/3/4): ").strip()

            if mode_choice == "4":
                print("\n👋 再见！")
                return

            mode_map = {"1": "chat", "2": "json", "3": "tools"}
            mode = mode_map.get(mode_choice)
            if not mode:
                print("\n⚠️  无效选择，请重试。")
                continue

            # ── 输入方式 ────────────────────────────────────────
            print("\n" + "-" * 40)
            print("  选择输入方式")
            print("-" * 40)
            print("  1. 文件输入（输入文件路径）")
            print("  2. 手动输入（直接输入文本）")
            print("-" * 40)
            input_choice = input("请输入编号 (1/2): ").strip()

            if input_choice == "1":
                file_path = input("请输入文件路径: ").strip()
                try:
                    prompt = ParseFile(file_path)
                    print(f"\n📄 已读取文件 ({len(prompt)} 字符)")
                except Exception as e:
                    print(f"\n❌ 读取文件失败: {e}")
                    continue
            elif input_choice == "2":
                prompt = input("请输入文本: ").strip()
                if not prompt:
                    print("\n⚠️  输入不能为空，请重试。")
                    continue
            else:
                print("\n⚠️  无效选择，请重试。")
                continue

            # ── 调用 ────────────────────────────────────────────
            print(f"\n🔹 使用模式: {mode}\n")

            try:
                if mode == "chat":
                    reply = llm.chat(prompt)
                elif mode == "json":
                    reply = llm.ChatJsonMode(prompt)
                else:  # tools
                    reply = llm.ChatToolsMode(prompt)

                print(f"\n📝 回复:\n{reply}")
            except Exception as e:
                print(f"\n❌ API 调用失败: {e}")

    except KeyboardInterrupt:
        print("\n\n👋 再见！")


if __name__ == "__main__":
    llm = LLMClient()

    print(f"模型: {llm.model}")
    print(f"Base: {llm.base_url}")

    # 检测占位 key，跳过实际调用
    if "sk-your" in llm.api_key:
        print(f"\n⚠️  检测到占位 API key，请修改 {K_ENV_PATH} 中的 LLM_API_KEY 后重试。")
    else:
        Run(llm)