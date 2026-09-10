import asyncio

from research_assistant.models import (DraftClaim, DraftReport, DraftSection,
                                       EvidenceDraft, Extraction, Plan, Review)
from research_assistant.retrieval import Page

QUOTE = "This official page contains verified research evidence about the subject."


class FakeLLM:
    def __init__(self, sufficient_after=1, bad_schema=None, bad_quote=False, bad_reference=False, delay=0):
        self.sufficient_after = sufficient_after
        self.reviews = 0
        self.bad_schema = bad_schema
        self.bad_quote = bad_quote
        self.bad_reference = bad_reference
        self.delay = delay
        self.calls = []

    async def ask(self, instruction, payload, schema, usage):
        from research_assistant.llm import ModelFormatError
        self.calls.append(schema)
        usage.model_calls += 1
        await asyncio.sleep(self.delay)
        if schema == self.bad_schema:
            raise ModelFormatError("模型输出不符合结构要求")
        usage.calls_with_usage += 1
        usage.total_tokens += 15
        usage.prompt_tokens += 10
        usage.completion_tokens += 5
        if schema == Plan:
            return Plan(subquestions=["研究问题"], queries=["first research"])
        if schema == Extraction:
            return Extraction(evidence=[EvidenceDraft(statement="来自实际页面的证据。",
                                                       quote="A fabricated quote which is not in the page." if self.bad_quote else QUOTE)])
        if schema == Review:
            self.reviews += 1
            sufficient = self.reviews >= self.sufficient_after
            return Review(sufficient=sufficient, reason="证据充分" if sufficient else "需要补检",
                          queries=[f"additional query {self.reviews}"],
                          unresolved_questions=[] if sufficient else ["仍需补充证据"])
        if schema == DraftReport:
            claim = DraftClaim(text="研究结论", evidence_ids=["E999" if self.bad_reference else "E1"],
                               confidence="高", confidence_reason="页面证据支持")
            return DraftReport(summary=[claim], sections=[DraftSection(title="研究发现", claims=[claim])],
                               key_conclusions=[claim], unresolved_questions=payload["unresolved_questions"])
        raise AssertionError(schema)

    async def close(self):
        pass


class FakeSearch:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    async def search(self, query):
        from research_assistant.retrieval import RetrievalError
        self.calls.append(query)
        if self.fail:
            raise RetrievalError("检索失败或无结果")
        n = len(self.calls)
        return [{"url": f"https://example.com/{n}", "title": "示例"},
                {"url": f"https://example.com/{n}#section", "title": "重复页面"}]


class FakeReader:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    async def read(self, url):
        from research_assistant.retrieval import RetrievalError
        self.calls.append(url)
        if self.fail:
            raise RetrievalError("网页没有可读取正文")
        return Page(url, "页面标题", QUOTE, None)

    async def close(self):
        pass
