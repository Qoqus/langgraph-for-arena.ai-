"""Any OpenAI-compatible chat-completions endpoint, over the standard library.

Deliberately dependency-free: swapping the mock for a real curator is an
environment variable, not a code change.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from ..prompts import build_messages


class CuratorLLMError(RuntimeError):
    pass


class OpenAICompatibleCurator:
    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        temperature: float = 0.9,
        timeout: float = 120.0,
        max_retries: int = 3,
        json_mode: bool | None = None,
    ) -> None:
        self.model = model or os.environ.get("MUSEUM_LLM_MODEL", "")
        self.base_url = (
            base_url or os.environ.get("MUSEUM_LLM_BASE_URL", "https://api.openai.com/v1")
        ).rstrip("/")
        self.api_key = api_key or os.environ.get("MUSEUM_LLM_API_KEY", "")
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max_retries
        if json_mode is None:
            json_mode = os.environ.get("MUSEUM_LLM_JSON_MODE", "1").lower() not in (
                "0",
                "false",
                "no",
                "off",
            )
        self.json_mode = json_mode
        if not self.model:
            raise CuratorLLMError(
                "no model configured: pass --model, set MUSEUM_LLM_MODEL, or use 'mock'"
            )
        self.name = f"openai-compatible:{self.model}"

    def propose(self, context: dict) -> str:
        messages = build_messages(context)
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if self.json_mode:
            payload["response_format"] = {"type": "json_object"}
        body = json.dumps(payload).encode("utf-8")

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            request = urllib.request.Request(
                f"{self.base_url}/chat/completions",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    data = json.loads(response.read().decode("utf-8"))
                content = data["choices"][0]["message"].get("content") or ""
                if not content.strip():
                    raise CuratorLLMError("model returned empty content")
                return content
            except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt == self.max_retries:
                    break
                time.sleep(min(8.0, 1.5 * attempt))
        raise CuratorLLMError(
            f"curator call failed after {self.max_retries} attempts: {last_error}"
        )
