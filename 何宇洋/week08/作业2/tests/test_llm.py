import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from research_assistant.config import Settings
from research_assistant.llm import DeepSeek, ModelFormatError
from research_assistant.models import Plan, Usage


@pytest.mark.parametrize("content,finish", [('not json', 'stop'), ('{"queries":[]}', 'stop'), ('{}', 'length')])
def test_invalid_response_schema_and_usage(content, finish):
    async def scenario():
        llm = DeepSeek(Settings(api_key="fake"))
        response = SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3, total_tokens=10),
            choices=[SimpleNamespace(finish_reason=finish, message=SimpleNamespace(content=content))])
        llm.client.chat.completions.create = AsyncMock(return_value=response)
        usage = Usage()
        try:
            with pytest.raises(ModelFormatError):
                await llm.ask("test", {}, Plan, usage)
            assert usage.model_calls == usage.calls_with_usage == 1
            assert usage.total_tokens == 10
            kwargs = llm.client.chat.completions.create.call_args.kwargs
            assert kwargs["model"] == "deepseek-v4-flash"
        finally:
            await llm.close()
    asyncio.run(scenario())
