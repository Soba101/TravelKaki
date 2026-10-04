"""One small wrapper around LiteLLM for structured (JSON) answers (issue #11).

Order of tries:
  1. the main model (EXTRACT_MODEL, local Ollama by default), up to 2 tries
  2. the fallback model (EXTRACT_FALLBACK_MODEL), 1 try, only if it is set
  3. give up -> LlmUnavailable
`on_call()` runs before every try. It counts toward the daily cap and may
raise CapReached, which stops everything at once.
"""

import asyncio
import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass

from travelkaki.config import Settings

log = logging.getLogger(__name__)

BACKOFF = [1, 3]  # seconds to wait before the 2nd and 3rd try
TIMEOUT = 60  # seconds. The first local call also loads the model, so be generous.
MAX_TOKENS = 1500  # stops a runaway model; a normal answer is a few hundred tokens
PLAN_TIMEOUT = 120  # seconds per planner round (longer prompts than extraction)


@dataclass
class ToolCall:
    """One tool the model wants to run. `arguments` is the raw JSON text."""

    id: str
    name: str
    arguments: str


@dataclass
class ToolReply:
    """The model's answer in one planner round (M2)."""

    content: str | None  # plain text, if any
    tool_calls: list[ToolCall]
    message: dict  # the assistant message, to add back to the chat history
    tokens: int


class LlmUnavailable(Exception):
    """No model gave a usable answer (down, timed out, or bad JSON)."""


class LlmClient:
    def __init__(self, settings: Settings, completion=None, sleep=asyncio.sleep):
        # `completion` and `sleep` can be swapped for fakes in tests.
        if completion is None:
            # Without this, LiteLLM downloads a model price list from the internet
            # when imported. We don't need it, and CI must not use the network. (PR2 review)
            os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
            import litellm  # imported here: it's slow to import and tests don't need it

            completion = litellm.acompletion
        self._completion = completion
        self._sleep = sleep
        self._settings = settings

    def _tries(self, main: str, fallback: str | None) -> list[str]:
        """The models to try, in order: main twice, then the fallback once (if set)."""
        return [main] * 2 + ([fallback] if fallback else [])

    def _kwargs(self, model: str) -> dict:
        """Ollama needs its address; cloud models need the API key (never sent to Ollama)."""
        if model.startswith("ollama"):
            return {"api_base": self._settings.ollama_base_url}
        return {"api_key": self._settings.llm_api_key}

    async def extract_json(
        self,
        messages: list[dict],
        schema: dict,
        on_call: Callable[[], None],
        validate: Callable[[dict], object] | None = None,
    ):
        """Ask for an answer that follows `schema`.

        Returns the parsed JSON dict, or `validate(dict)` when given. If `validate`
        raises (right JSON, wrong shape), that try counts as failed, so the retry
        and the fallback model still get their turn. (PR2 review)
        """
        tries = self._tries(self._settings.extract_model, self._settings.extract_fallback_model)
        for attempt, model in enumerate(tries):
            if attempt > 0:
                await self._sleep(BACKOFF[attempt - 1])  # short wait before retrying
            on_call()  # may raise CapReached: let it through
            try:
                response = await self._completion(
                    model=model,
                    messages=messages,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {"name": "extraction", "schema": schema},
                    },
                    timeout=TIMEOUT,
                    temperature=0,
                    max_tokens=MAX_TOKENS,
                    **self._kwargs(model),
                )
                raw = json.loads(response.choices[0].message.content)
                return validate(raw) if validate else raw
            except Exception as e:  # noqa: BLE001 - any failure here just means "try the next one"
                log.warning("LLM try %d (%s) failed: %s", attempt + 1, model, type(e).__name__)
        raise LlmUnavailable()

    async def chat_tools(
        self, messages: list[dict], tools: list[dict], on_call: Callable[[], None]
    ) -> ToolReply:
        """One planner round: send the chat + tool list, get text and/or tool calls (M2).

        Same tries as extract_json (plan model x2, then the fallback once),
        and `on_call()` runs before every try (daily cap). Raises LlmUnavailable.
        """
        tries = self._tries(self._settings.plan_model, self._settings.plan_fallback_model)
        for attempt, model in enumerate(tries):
            if attempt > 0:
                await self._sleep(BACKOFF[attempt - 1])
            on_call()  # may raise CapReached: let it through
            try:
                response = await self._completion(
                    model=model,
                    messages=messages,
                    tools=tools,
                    timeout=PLAN_TIMEOUT,
                    temperature=0,
                    max_tokens=MAX_TOKENS,
                    **self._kwargs(model),
                )
                msg = response.choices[0].message
                calls = [
                    ToolCall(c.id, c.function.name, c.function.arguments or "{}")
                    for c in (msg.tool_calls or [])
                ]
                usage = getattr(response, "usage", None)
                tokens = getattr(usage, "total_tokens", 0) or 0
                return ToolReply(msg.content, calls, msg.model_dump(exclude_none=True), tokens)
            except Exception as e:  # noqa: BLE001 - any failure here just means "try the next one"
                log.warning("plan try %d (%s) failed: %s", attempt + 1, model, type(e).__name__)
        raise LlmUnavailable()
