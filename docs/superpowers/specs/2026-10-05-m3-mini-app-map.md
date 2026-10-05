# M3 Mini App Map — Spec + Plan (PR1: #23 + #24)

**Date:** 2026-10-05. Spec and plan are one short doc to save usage.

## Decisions (Donovan, 2026-10-05)

- The map is **read-only** in M3. Voting stays in chat (maybe later).
- Today: PR1 = #23 (JSON API + initData check) and #24 (Leaflet map, pins by vote).
- Later: PR2 = #25 (day tabs + routes) and #26 (Open map button, `/map`, tunnel).
- Tunnel: decide in PR2. Recommended: Tailscale Funnel (stable https, no port forwarding).
- Reviews: one Sonnet reviewer per PR.

## How a friend opens the map (PR2, but it shapes PR1)

- Telegram does not allow `web_app` buttons in groups. So the bot posts a normal URL
  button: `https://t.me/<bot>/<app>?startapp=<trip_id>` (a "direct link" mini app).
- Telegram opens the mini app and passes `start_param = <trip_id>` inside `initData`.
- `initData` is signed by Telegram with our bot token. So the server knows who the user is.

## Security (#23)

1. **Signature.** `secret = HMAC_SHA256(key="WebAppData", msg=bot_token)`.
   `hash = hex(HMAC_SHA256(key=secret, msg=data_check_string))`.
   `data_check_string` = all fields except `hash`, as `key=value`, sorted, joined by `\n`.
   Compare with `hmac.compare_digest`.
2. **Freshness.** Reject if `auth_date` is older than 24 h.
3. **Membership.** The trip id in the link can be forwarded. So we also call
   `getChatMember(trip.chat_id, user_id)`. Allowed: creator, administrator, member,
   restricted with `is_member`. Cache the answer for 10 min (one Telegram call per person).
4. Errors: 401 bad/missing/old initData; 403 not a member; 404 no such trip.
   One vague message for 403/404 is not needed: trip ids are not secret.

## API

`GET /api/trip/{trip_id}` with header `Authorization: tma <initData>`.

```json
{"city": "Tokyo", "hotel": {"name": "...", "lat": 1.0, "lng": 2.0} | null,
 "places": [{"id": 1, "name": "...", "category": "...", "lat": 1.0 | null,
             "lng": 2.0 | null, "address": "..." | null,
             "must": 2, "maybe": 0, "skip": 0, "tier": "must",
             "maps_url": "https://www.google.com/maps/search/..."}]}
```

Reuse `rules.tier` and `cards.maps_url`. `GET /app` serves the map page (no auth: it is
just HTML/JS; the data needs auth).

## Map page (#24)

- `travelkaki/web/static/map.html` + `map.js`. Leaflet 1.9 from unpkg, OSM tiles,
  `telegram-web-app.js` from telegram.org.
- Pin colours: Must-go green, Maybe amber, Skip grey. Hotel = blue.
- Popup: name, category, vote counts, "Open in Google Maps" (`Telegram.WebApp.openLink`).
- Places without a pin are listed under the map.
- Map fits all pins. Errors show a plain message ("Open this from the trip's group").

## Files

| File | Job |
|---|---|
| `web/auth.py` | `check_init_data(raw, token, now) -> (user_id, start_param)` |
| `web/members.py` | `MemberCheck`: getChatMember + 10 min cache |
| `web/trip_json.py` | `trip_json(s, trip) -> dict` (pure DB → JSON) |
| `web/api.py` | router: `/api/trip/{id}`, `/app` |
| `web/static/map.html`, `map.js` | the page |
| `web/app.py` | include router; put `deps` + member check on `app.state` |

## Tasks (TDD)

1. auth.py: tests for valid, bad hash, missing hash, old auth_date, no user.
2. members.py: tests with a fake bot: member, left, restricted, cache hit, Telegram error → False.
3. trip_json.py: tests: tiers, null pins, hotel, maps_url.
4. api.py + app wiring: TestClient tests: 401, 403, 404, 200 body; `/app` serves HTML.
5. map.html/map.js. Check: page loads in headless Chromium with a stubbed API.
6. Ruff + full pytest → PR → Sonnet review → fix → merge → comment #23, #24.
