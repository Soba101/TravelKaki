"""Web routes for the mini app (M3, #23 + #24).

GET /app                 -> the map page (plain HTML; no data in it)
GET /static/map.js       -> the page's script (mounted in web/app.py)
GET /api/trip/{trip_id}  -> the trip as JSON. Needs header "Authorization: tma <initData>".

The page's data is protected 2 ways: the initData signature proves who the
user is, and getChatMember proves they are in the trip's group.
"""

from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import FileResponse

from travelkaki.db.models import Trip
from travelkaki.web.auth import AuthError, check_init_data
from travelkaki.web.trip_json import trip_json

router = APIRouter()
STATIC = Path(__file__).parent / "static"


@router.get("/app")
async def map_page() -> FileResponse:
    return FileResponse(STATIC / "map.html")


@router.get("/api/trip/{trip_id}")
async def get_trip(trip_id: int, request: Request, authorization: str = Header("")) -> dict:
    state = request.app.state
    # 1. Who is asking? (401 if initData is missing, forged or old.)
    scheme, _, raw = authorization.partition(" ")
    if scheme != "tma":
        raise HTTPException(401, "Open this from Telegram.")
    try:
        user_id, _ = check_init_data(raw, state.token)
    except AuthError as e:
        raise HTTPException(401, "Open this from Telegram.") from e

    with state.deps.sessions() as s:
        trip = s.get(Trip, trip_id)
        if trip is None:
            raise HTTPException(404, "No such trip.")
        # 2. Are they in the trip's group? (403 if not.)
        if not await state.members.ok(trip.chat_id, user_id):
            raise HTTPException(403, "Only the trip's group can see this map.")
        return trip_json(s, trip)
