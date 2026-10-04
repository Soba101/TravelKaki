"""Tests for place cards, keyboards and bot messages. Pure functions, no Telegram."""

from travelkaki.bot.cards import (
    ERRORS,
    error_text,
    list_keyboard,
    list_text,
    maps_url,
    parse_callback,
    places_text,
    retry_keyboard,
)
from travelkaki.db.models import Place
from travelkaki.db.place_queries import VoteCounts
from travelkaki.ingest import pipeline


def _place(id=1, name="Ichiran", confidence="none", **kw):
    defaults = dict(
        category="ramen", video_note="24h, solo booths", lat=None, lng=None, address=None
    )
    return Place(id=id, trip_id=1, name=name, confidence=confidence, **(defaults | kw))


def _buttons(markup):
    return [[(b.text, b.callback_data) for b in row] for row in markup.inline_keyboard]


def test_list_escapes_html():
    # Review Focus 3: names come from untrusted captions.
    text = list_text([_place(name="Bar <Ishi> & *Co*")], "Tokyo", "Alex", "tiktok")
    assert "Bar &lt;Ishi&gt; &amp; *Co*" in text
    assert "<Ishi>" not in text


def test_list_text_is_one_compact_message():
    # One message per link instead of one card per place (#49).
    places = [_place(1, "Ichiran"), _place(2, "Butagumi", category="tonkatsu")]
    text = list_text(places, "Tokyo", "Alex", "tiktok", merged=["Tsukiji Market"], extra=3)
    lines = text.split("\n")
    assert lines[0] == "📍 2 places from Alex's TikTok"
    assert lines[1].startswith("1. <b>Ichiran</b> · ramen · <a href=")
    assert lines[2].startswith("2. <b>Butagumi</b> · tonkatsu")
    assert "Already saved: Tsukiji Market" in text
    assert "+3 more, see /places" in text


def test_list_text_headers():
    assert list_text([_place()], "Tokyo", None, None).startswith("📍 Added: ")  # text add
    assert list_text([_place()], "Tokyo", None, "instagram").startswith(
        "📍 1 place from an Instagram"
    )


def test_unsure_pins_are_marked():
    low = _place(1, confidence="low", lat=35.6, lng=139.7, address="1-2 Shibuya")
    far = _place(2, confidence="far", lat=34.7, lng=135.5)
    high = _place(3, confidence="high", lat=35.6, lng=139.7)
    lines = list_text([low, far, high], "Tokyo", "Alex", "tiktok").split("\n")
    assert lines[1].endswith("⚠️") and lines[2].endswith("⚠️") and not lines[3].endswith("⚠️")


def test_list_keyboard_one_row_per_place():
    big = 10**9
    low = _place(big, confidence="low", lat=35.6, lng=139.7)
    rows = _buttons(list_keyboard([_place(5), low], {5: VoteCounts(2, 0, 1)}))
    assert rows[0] == [("1 ✅2", "v:5:m"), ("🤔0", "v:5:y"), ("❌1", "v:5:s")]
    assert rows[1] == [  # unsure pin: extra "wrong place" button; missing counts = 0
        ("2 ✅0", f"v:{big}:m"),
        ("🤔0", f"v:{big}:y"),
        ("❌0", f"v:{big}:s"),
        ("👎📍", f"w:{big}"),
    ]
    assert all(len(data.encode()) <= 64 for row in rows for _, data in row)
    assert _buttons(retry_keyboard(5)) == [[("🔁 Retry", "r:5")]]


def test_maps_url():
    assert maps_url(_place(lat=35.5, lng=139.25), "Tokyo").endswith("query=35.5,139.25")
    assert maps_url(_place(name="Ichiran Shibuya"), "Tokyo").endswith(
        "query=Ichiran+Shibuya%2C+Tokyo"
    )


def test_every_pipeline_error_has_a_message():
    codes = [
        pipeline.NO_CAPTION,
        pipeline.LLM_UNAVAILABLE,
        pipeline.CAP_REACHED,
        pipeline.NO_PLACES,
        pipeline.UNKNOWN,
    ]
    for code in codes + ["interrupted", "link_error"]:
        assert code in ERRORS
    assert "@travelkakiibot add &lt;place&gt;" in error_text("no_caption", "travelkakiibot")


def test_places_text_order_and_skipped_section():
    a = (_place(1, "A"), VoteCounts(must=2))
    b = (_place(2, "B"), VoteCounts(must=1, maybe=3))
    c = (_place(3, "C"), VoteCounts(skip=2))
    text = "".join(places_text([c, b, a], "Tokyo"))
    assert text.index("A") < text.index("B") < text.index("Skipped") < text.index("C")


def test_places_text_splits_long_lists():
    rows = [(_place(i, f"Place number {i} " + "x" * 40), VoteCounts()) for i in range(300)]
    chunks = places_text(rows, "Tokyo")
    assert len(chunks) > 1 and all(len(c) <= 4096 for c in chunks)
    assert places_text([], "Tokyo") == ["No places yet. Post a TikTok or IG link!"]


def test_parse_callback():
    assert parse_callback("v:12:m") == ("v", 12, "m")
    assert parse_callback("w:3") == ("w", 3, None)
    assert parse_callback("r:4") == ("r", 4, None)
    for bad in ["x", "v:abc:m", "v:1:z", "q:1", "", "v:1"]:
        assert parse_callback(bad) is None
