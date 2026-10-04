"""Live test: the real local LLM runs the planner loop (M2 Task 14).

Skipped in CI. Run on the Mac (see the handoff for the throwaway container):
    uv run pytest -m live tests/test_planner_live.py
"""

import pytest

from tests.fakes import make_deps
from tests.planner_helpers import make_input, place
from travelkaki.config import Settings
from travelkaki.db import queries
from travelkaki.llm.client import LlmClient
from travelkaki.planner.loop import run_planner
from travelkaki.planner.validate import savable

pytestmark = pytest.mark.live

# Six real Tokyo places with real OSM hours. teamLab is closed on Tue (made up, as a trap).
PLACES = [
    place(1, 35.6491, 139.7898, category="museum", hours="Mo,We-Su 09:00-22:00"),  # teamLab
    place(2, 35.6655, 139.7707, category="market", hours="Mo-Sa 05:00-14:00"),  # Tsukiji
    place(3, 35.6614, 139.7041, category="ramen", hours="24/7"),  # Ichiran Shibuya
    place(4, 35.6585, 139.7016, tier="maybe", category="viewpoint", hours="Mo-Su 10:00-22:30"),
    place(5, 35.7148, 139.7967, category="temple", hours="Mo-Su 06:00-17:00"),  # Senso-ji
    place(6, 35.7188, 139.7765, tier="maybe", category="museum", hours="Tu-Su 09:30-17:00"),
]


async def test_real_llm_plans_a_valid_trip(sessions):
    settings = Settings(_env_file=None, telegram_bot_token="x:y")
    with sessions() as s:
        trip = queries.upsert_trip(s, 1, "Tokyo", None, None, None)
    inp = make_input(PLACES, days=2)
    inp.trip_id = trip.id
    deps = make_deps(sessions, llm=LlmClient(settings))
    result = await run_planner(deps, inp, "live-1")
    print(f"\nrounds={result.rounds} used_ai={result.used_ai} tradeoffs={result.tradeoffs!r}")
    assert result.used_ai, "the local model did not finish with save_plan"
    assert savable(result.plan, result.issues)
