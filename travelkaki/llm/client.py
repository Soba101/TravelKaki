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
from collections.abc import Callable

from travelkaki.config import Settings

log = logging.getLogger(__name__)

BACKOFF = [1, 3]  # seconds to wait before the 2nd and 3rd try
TIMEOUT = 60  # seconds. The first local call also loads the model, so be generous.


class LlmUnavailable(Exception):
    """No model gave a usable answer (down, timed out, or bad JSON)."""


class LlmClient:
    def __init__(self, settings: Settings, completion=None, sleep=asyncio.sleep):
        # `completion` and `sleep` can be swapped for fakes in tests.
        if completion is None:
            import litellm  # imported here: it's slow to import and tests don't need it

            completion = litellm.acompletion
        self._completion = completion
        self._sleep = sleep
        self._settings = settings

    def _tries(self) -> list[str]:
        """The models to try, in order."""
        tries = [self._settings.extract_model] * 2
        if self._settings.extract_fallback_model:
            tries.append(self._settings.extract_fallback_model)
        return tries

    def _kwargs(self, model: str) -> dict:
        """Ollama needs its address; cloud models need the API key (never sent to Ollama)."""
        if model.startswith("ollama"):
            return {"api_base": self._settings.ollama_base_url}
        return {"api_key": self._settings.llm_api_key}

    async def extract_json(
        self, messages: list[dict], schema: dict, on_call: Callable[[], None]
    ) -> dict:
        """Ask for an answer that follows `schema`, and return it as a dict."""
        for attempt, model in enumerate(self._tries()):
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
                    **self._kwargs(model),
                )
                return json.loads(response.choices[0].message.content)
            except Exception as e:  # noqa: BLE001 - any failure here just means "try the next one"
                log.warning("LLM try %d (%s) failed: %s", attempt + 1, model, type(e).__name__)
        raise LlmUnavailable()
