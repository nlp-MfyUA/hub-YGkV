import os
import re
import json
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
os.environ["OPENAI_BASE_URL"] = os.getenv("OPENAI_API_URL", "")

import asyncio
from pydantic import BaseModel
from agents import Agent, Runner, ModelSettings

from agents import set_default_openai_api, set_tracing_disabled
set_default_openai_api("chat_completions")
set_tracing_disabled(True)

# 关闭推理模型的思考过程（DeepSeek 风格）
NO_THINKING_SETTINGS = ModelSettings(extra_body={"thinking": {"type": "disabled"}})


# ─────────────────────────────────────────────
# 1. 定义最终输出结构
# ─────────────────────────────────────────────
class TranslateResult(BaseModel):
    """Agent 内部返回的翻译结果（语种 + 译文）"""
    language: str
    result: str


# ─────────────────────────────────────────────
# 2. 翻译 Agent：根据用户输入判断语种并翻译，输出 JSON
# ─────────────────────────────────────────────
# 注意：不用 output_type=TranslateResult，因为国内推理模型对 structured outputs 支持不好。
# 改为让模型返回 JSON 文本，我们在外面手工解析。
translate_agent = Agent(
    name="Translate Agent",
    model="MiniMax-M3",
    instructions=(
        "你是一个翻译助手。判断用户输入文本的语种，然后进行翻译：\n"
        "1. 如果是中文（zh），翻译成英文；\n"
        "2. 如果是非中文（en/ja/ko/fr/...），翻译成中文。\n"
        "严格只输出一个 JSON 对象，格式为：\n"
        '{"language": "<语种，如 zh/en/ja>", "result": "<翻译结果>"}\n'
        "不要输出任何解释、思考过程、Markdown 代码块或其他多余内容。"
    ),
    model_settings=NO_THINKING_SETTINGS,
)


# ─────────────────────────────────────────────
# 3. 容错：从模型原始输出中抠 JSON
# ─────────────────────────────────────────────
# 语种代码 → 中文名称映射
LANG_CODE_TO_CN = {
    "zh": "中文", "chinese": "中文", "中文": "中文",
    "en": "英语", "english": "英语", "英文": "英语", "英语": "英语",
    "ja": "日语", "japanese": "日语", "日文": "日语", "日语": "日语",
    "ko": "韩语", "korean": "韩语", "韩文": "韩语", "韩语": "韩语",
    "fr": "法语", "french": "法语", "法文": "法语", "法语": "法语",
    "de": "德语", "german": "德语", "德文": "德语", "德语": "德语",
    "es": "西班牙语", "spanish": "西班牙语", "西文": "西班牙语",
    "ru": "俄语", "russian": "俄语", "俄文": "俄语", "俄语": "俄语",
    "ar": "阿拉伯语", "arabic": "阿拉伯语",
    "th": "泰语", "thai": "泰语",
    "vi": "越南语", "vietnamese": "越南语",
    "pt": "葡萄牙语", "portuguese": "葡萄牙语",
    "it": "意大利语", "italian": "意大利语",
}


def extract_translate_json(raw: str) -> TranslateResult:
    """从模型输出里抠出 {"language": "...", "result": "..."} 并解析。"""
    # 1) 去掉 <think>...</think> 思考链
    cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    # 2) 优先从 markdown 代码块中提取 ```json ... ```
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.DOTALL)
    if m:
        cleaned = m.group(1)
    else:
        # 3) 否则取第一个 {...} 子串
        m = re.search(r"\{.*?\}", cleaned, flags=re.DOTALL)
        if m:
            cleaned = m.group(0)

    try:
        data = json.loads(cleaned)
        # 把语种统一转换为中文名
        raw_lang = str(data.get("language", "")).strip()
        lang_cn = LANG_CODE_TO_CN.get(raw_lang.lower(), raw_lang)
        return TranslateResult(language=lang_cn, result=data["result"])
    except Exception as e:
        raise ValueError(f"无法从模型输出中解析 JSON: {raw[:200]}... ({e})") from e


# ─────────────────────────────────────────────
# 4. 主流程：接收用户输入 → 调 Agent → 拼最终 JSON
# ─────────────────────────────────────────────
async def detect_and_translate(query_input: str) -> dict:
    """返回用户要求的最终 JSON 格式"""
    print(f"\n>>> 用户输入: {query_input}")

    result = await Runner.run(translate_agent, query_input)
    raw = (result.final_output or "").strip() if isinstance(result.final_output, str) else ""

    translate_result = extract_translate_json(raw)
    print(f">>> 识别语种: {translate_result.language}")
    print(f">>> 翻译结果: {translate_result.result}")

    return {
        "query_input": query_input,
        "language": translate_result.language,
        "result": translate_result.result,
    }


# ─────────────────────────────────────────────
# 5. 主程序：用户手动输入文本进行翻译
# ─────────────────────────────────────────────
async def main():
    print("=" * 60)
    print("语种识别 + 翻译（输入 q 退出）")
    print("=" * 60)
    while True:
        user_q = input("\n请输入文本: ").strip()
        if user_q.lower() in ("q", "quit", "exit"):
            print("Bye~")
            break
        if not user_q:
            continue
        output = await detect_and_translate(user_q)
        print("\n**最终 JSON:**")
        print(json.dumps(output, ensure_ascii=False, indent=2))
        print("="*60)


if __name__ == "__main__":
    asyncio.run(main())

# 运行：python3 work1.py