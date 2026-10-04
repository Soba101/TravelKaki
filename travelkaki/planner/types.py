"""Small data classes shared by the planner (M2 spec).

Times are minutes from midnight on that day. 09:30 = 570.
An end after midnight is > 1440 (00:30 next morning = 1470).
"""

from dataclasses import dataclass, field
from datetime import date

EVENING_END = 1500  # 01:00: latest end when an evening place is on the day
MAX_SPAN = 720  # a day's busy span is at most 12 hours


@dataclass(frozen=True)
class Window:
    """When a day may start and end.

    Flexible (default): start 09:00 (or when the first stop opens), end by 22:00,
    or by 01:00 if an evening place is on the day. Fixed: `/plan 10-22`.
    """

    start: int = 540  # 09:00
    latest_end: int = 1320  # 22:00
    fixed: bool = False

    def label(self) -> str:
        """'flex', or the fixed hours like '10-22' (saved with the itinerary)."""
        if not self.fixed:
            return "flex"
        return f"{self.start // 60}-{(self.latest_end // 60) % 24}"


@dataclass
class PlanPlace:
    """A saved place the planner may use (it has a map pin)."""

    id: int
    name: str
    category: str
    lat: float
    lng: float
    tier: str  # "must" or "maybe" (skips never get here)
    must: int  # Must-go votes
    maybe: int  # Maybe votes
    hours: str | None  # raw OSM opening hours; None or "" = unknown
    visit: int  # minutes spent there
    note: str = ""  # what the post said about it
    address: str | None = None

    @property
    def point(self) -> tuple[float, float]:
        return (self.lat, self.lng)


@dataclass
class Stop:
    """One visit in a day: arrive at `start`, leave at `end`."""

    place_id: int
    start: int
    end: int
    travel: int  # minutes from the previous stop (or the hotel)
    mode: str  # "walk" or "transit"


@dataclass
class Day:
    date: date
    stops: list[Stop] = field(default_factory=list)


@dataclass
class Dropped:
    """A place left out of the plan, with a true, plain reason."""

    place_id: int
    name: str
    reason: str  # e.g. "closed on Tue 16 Dec", "no time left on Day 2"


@dataclass
class Plan:
    days: list[Day]
    dropped: list[Dropped] = field(default_factory=list)


@dataclass
class Issue:
    """One validator finding. level "error" = plan not valid, "warning" = FYI."""

    level: str
    code: str
    text: str
    place_id: int | None = None
    day: int | None = None  # 1-based day number


@dataclass
class Priorities:
    """What the agent asks build_days for. Ids are place ids."""

    include: list[int] = field(default_factory=list)  # add these (e.g. a Maybe)
    exclude: list[int] = field(default_factory=list)  # leave these out
    pins: dict[int, int] = field(default_factory=dict)  # place id -> day number (1-based)


@dataclass
class PlanInput:
    """Everything the planner needs about one trip, read once from the DB."""

    trip_id: int
    city: str
    dates: list[date]
    base: tuple[float, float]  # hotel pin, or the city centre
    base_is_hotel: bool
    places: list[PlanPlace]  # pinned Must + Maybe places
    skipped: list[int]  # ids of skip-tier places (never planned)
    dropped: list[Dropped]  # left out before planning (e.g. "no map pin")
    window: Window = field(default_factory=Window)

    def place(self, place_id: int) -> PlanPlace | None:
        return next((p for p in self.places if p.id == place_id), None)
