"""Small planner rules: vote tiers, visit length, food and evening places (M2 spec).

Categories come from the LLM as free text ("ramen shop", "Museum"), so we
match lower-case keywords. The first matching group wins.
"""

from travelkaki.planner.hours import parse
from travelkaki.planner.types import PlanPlace

# (keywords, minutes spent there). Order matters: "ramen shop" is food, not shopping.
VISIT_RULES = [
    (("cafe", "coffee", "bakery", "dessert"), 45),
    (("restaurant", "ramen", "sushi", "food", "market", "stall", "izakaya"), 60),
    (("museum", "attraction", "theme", "aquarium", "zoo", "gallery"), 120),
    (("park", "viewpoint", "temple", "shrine", "garden"), 60),
    (("shop", "mall"), 60),
    (("bar", "nightlife", "club"), 90),
]
DEFAULT_VISIT = 60

FOOD_WORDS = (
    "cafe", "coffee", "bakery", "dessert", "restaurant", "ramen", "sushi",
    "food", "market", "stall", "izakaya",
)  # fmt: skip
EVENING_WORDS = ("bar", "nightlife", "club", "izakaya")
EVENING_OPENS = 17 * 60  # opens at 17:00 or later = an evening place


def tier(must: int, maybe: int, skip: int) -> str:
    """'skip' if skips outnumber the rest, 'must' if anyone said Must-go, else 'maybe'.

    Places nobody voted on count as 'maybe'.
    """
    if skip > must + maybe:
        return "skip"
    if must >= 1:
        return "must"
    return "maybe"


def _has(category: str, words) -> bool:
    text = category.lower()
    return any(w in text for w in words)


def visit_minutes(category: str) -> int:
    for words, minutes in VISIT_RULES:
        if _has(category, words):
            return minutes
    return DEFAULT_VISIT


def is_food(category: str) -> bool:
    return _has(category, FOOD_WORDS)


def is_evening(place: PlanPlace) -> bool:
    """A bar-like category, or known hours that only start in the evening."""
    if _has(place.category, EVENING_WORDS):
        return True
    week = parse(place.hours)
    if not week:
        return False
    starts = [s for intervals in week.values() for s, _ in intervals]
    return bool(starts) and min(starts) >= EVENING_OPENS
