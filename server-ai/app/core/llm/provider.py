from abc import ABC, abstractmethod
import hashlib
from typing import AsyncIterator

class LlmProvider(ABC):
    @abstractmethod
    async def answer(self, question: str) -> AsyncIterator[str]: ...
    @abstractmethod
    def usage(self, question: str, answer: str) -> dict[str, int]: ...

class MockProvider(LlmProvider):
    async def answer(self, question: str) -> AsyncIterator[str]:
        text = f"这是针对“{question}”的模拟回答。"
        for token in [text[i:i+4] for i in range(0, len(text), 4)]:
            yield token
    def usage(self, question: str, answer: str) -> dict[str, int]:
        return {"prompt_tokens": len(question), "completion_tokens": len(answer)}

class OpenAiProvider(MockProvider):
    """OpenAI-compatible placeholder; uses deterministic fallback until endpoint wiring is configured."""
    pass

def provider_from_settings(settings):
    return OpenAiProvider() if settings.ai_provider.lower() == "real" else MockProvider()
