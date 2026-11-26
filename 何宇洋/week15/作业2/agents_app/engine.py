"""进程1和进程2各自通过 Agent + Runner 执行；明确使用 Chat Completions。"""
from agents import Agent, ModelSettings, OpenAIChatCompletionsModel, Runner, set_tracing_disabled

from common.llm import CLASSIFY_PROMPT, REPLY_PROMPTS, REPLY_SUFFIX, model_name
from common.models import Reply, ReplyInput, Sentiment

set_tracing_disabled(True)


class Engine:
    def __init__(self, client):
        model = OpenAIChatCompletionsModel(model=model_name(), openai_client=client)
        self.classifier = Agent(
            name="情感识别Agent",
            instructions=CLASSIFY_PROMPT,
            model=model,
            # JSON object 模式兼容 DeepSeek，不依赖 strict JSON schema。
            model_settings=ModelSettings(max_tokens=400, extra_body={
                "response_format": {"type": "json_object"},
                "thinking": {"type": "disabled"},
            }),
        )
        self.responders = {
            label: Agent(name="鼓励Agent" if label == "positive" else "排解Agent",
                         instructions=prompt + REPLY_SUFFIX, model=model,
                         model_settings=ModelSettings(max_tokens=500, extra_body={
                             "thinking": {"type": "disabled"},
                         }))
            for label, prompt in REPLY_PROMPTS.items()
        }

    async def classify(self, text: str) -> Sentiment:
        result = await Runner.run(self.classifier, input=text, max_turns=1)
        return Sentiment.model_validate_json(result.final_output)

    async def respond(self, data: ReplyInput) -> Reply:
        agent = self.responders[data.analysis.sentiment]
        result = await Runner.run(agent, input=data.model_dump_json(), max_turns=1)
        return Reply(reply=str(result.final_output).strip())
