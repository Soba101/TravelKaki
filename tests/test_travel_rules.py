"""Travel estimate, vote tiers, visit lengths, evening places (M2 Task 4)."""

import pytest

from travelkaki.planner.rules import is_evening, is_food, tier, visit_minutes
from travelkaki.planner.travel import estimate
from travelkaki.planner.types import PlanPlace, Window

A = (35.6595, 139.7005)


def test_estimate_same_point():
    assert estimate(A, A) == (0, "walk")


def test_estimate_short_walk():
    # 0.009 deg latitude ~ 1.0 km -> x1.3 = 1.3 km -> 17.4 min walk -> 18
    assert estimate(A, (A[0] + 0.009, A[1])) == (18, "walk")


def test_estimate_transit():
    # ~10 km -> x1.3 = 13 km -> 39 min at 20 km/h + 10 min
    assert estimate(A, (A[0] + 0.0899, A[1])) == (49, "transit")


@pytest.mark.parametrize(
    "votes, expected",
    [
        ((0, 0, 0), "maybe"),
        ((1, 0, 0), "must"),
        ((1, 0, 2), "skip"),
        ((0, 2, 2), "maybe"),
        ((0, 0, 1), "skip"),
    ],
)
def test_tier(votes, expected):
    assert tier(*votes) == expected


@pytest.mark.parametrize(
    "category, minutes",
    [("Cafe", 45), ("ramen shop", 60), ("Museum", 120), ("bar", 90), ("", 60), ("park", 60)],
)
def test_visit_minutes(category, minutes):
    assert visit_minutes(category) == minutes


def test_is_food():
    assert is_food("Ramen") and is_food("night market")
    assert not is_food("museum")


def _place(category="museum", hours=None):
    return PlanPlace(1, "X", category, 35.0, 139.0, "maybe", 0, 0, hours, 60)


def test_is_evening():
    assert is_evening(_place("izakaya"))
    assert is_evening(_place("place", "Mo-Su 18:00-02:00"))
    assert not is_evening(_place("museum", "Mo-Su 10:00-18:00"))
    assert not is_evening(_place("museum", None))


def test_window_label():
    assert Window().label() == "flex"
    assert Window(600, 1320, fixed=True).label() == "10-22"
    assert Window(1080, 1560, fixed=True).label() == "18-2"
