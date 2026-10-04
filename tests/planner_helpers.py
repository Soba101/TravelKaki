"""Builders for planner tests: places and trip inputs around Tokyo."""

from datetime import date, timedelta

from travelkaki.planner.types import PlanInput, PlanPlace, Window

BASE = (35.6900, 139.7000)  # "hotel" in Shinjuku
TUE = date(2026, 12, 15)  # a Tuesday


def place(pid, lat=35.6900, lng=139.7000, tier="must", category="museum", hours=None, visit=None):
    """A pinned place. Default: a museum next to the hotel, unknown hours."""
    from travelkaki.planner.rules import visit_minutes

    return PlanPlace(
        pid, f"Place {pid}", category, lat, lng, tier, 1 if tier == "must" else 0,
        1 if tier == "maybe" else 0, hours, visit or visit_minutes(category),
    )  # fmt: skip


def make_input(places, days=2, window=None, skipped=(), base=BASE):
    return PlanInput(
        trip_id=1,
        city="Tokyo",
        dates=[TUE + timedelta(days=i) for i in range(days)],
        base=base,
        base_is_hotel=True,
        places=list(places),
        skipped=list(skipped),
        dropped=[],
        window=window or Window(),
    )


def planned_ids(plan):
    """{day number: [place ids]}"""
    return {i + 1: [s.place_id for s in d.stops] for i, d in enumerate(plan.days)}
