"""LangGraph 节点使用 OpenAI 兼容客户端访问 DeepSeek。"""
from common.llm import CLASSIFY_PROMPT, REPLY_PROMPTS, REPLY_SUFFIX, model_name
from common.models import Reply, ReplyInput, Sentiment


class Engine:
    def __init__(self, client):
        self.client = client

    async def classify(self, text: str) -> Sentiment:
        result = await self.client.chat.completions.create(
            model=model_name(),
            messages=[{"role": "system", "content": CLASSIFY_PROMPT},
                      {"role": "user", "content": text}],
            response_format={"type": "json_object"},
            extra_body={"thinking": {"type": "disabled"}},
            max_tokens=400,
        )
        return Sentiment.model_validate_json(result.choices[0].message.content or "")

    async def respond(self, data: ReplyInput) -> Reply:
        result = await self.client.chat.completions.create(
            model=model_name(),
            messages=[{"role": "system", "content": REPLY_PROMPTS[data.analysis.sentiment] + REPLY_SUFFIX},
                      {"role": "user", "content": data.model_dump_json()}],
            extra_body={"thinking": {"type": "disabled"}},
            max_tokens=500,
        )
        return Reply(reply=(result.choices[0].message.content or "").strip())
