"""Live test: the real local LLM (Ollama) on saved captions.

Skipped by default and in CI. Run on your Mac with Ollama running:
    OLLAMA_BASE_URL=http://localhost:11434 uv run pytest -m live -q
"""

import json
from pathlib import Path

import pytest

from travelkaki.config import Settings
from travelkaki.ingest.extract import extract_places
from travelkaki.llm.client import LlmClient

CASES = json.loads((Path(__file__).parent / "fixtures" / "captions.json").read_text())


@pytest.mark.live
@pytest.mark.parametrize("case", CASES, ids=[c["city"] for c in CASES])
async def test_real_llm_finds_expected_places(case):
    llm = LlmClient(Settings(telegram_bot_token="x:y"))
    places = await extract_places(llm, case["city"], case["caption"], on_call=lambda: None)
    names = " | ".join(p.name.lower() for p in places)
    for expected in case["expected"]:
        assert expected.lower() in names, f"missing {expected!r} in {names!r}"
    if not case["expected"]:
        assert places == []
