"""Tests for place cards, keyboards and bot messages. Pure functions, no Telegram."""

from travelkaki.bot.cards import (
    ERRORS,
    card_keyboard,
    card_text,
    error_text,
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


def test_card_escapes_html():
    # Review Focus 3: names come from untrusted captions.
    text = card_text(_place(name="Bar <Ishi> & *Co*"), "Tokyo", "Alex", "tiktok")
    assert "Bar &lt;Ishi&gt; &amp; *Co*" in text
    assert "<Ishi>" not in text


def test_card_text_lines():
    text = card_text(_place(), "Tokyo", "Alex", "tiktok")
    assert text.startswith("📍 <b>Ichiran</b> · ramen")
    assert "“24h, solo booths”" in text
    assert "from Alex's TikTok" in text and "Map ↗</a>" in text


def test_text_add_card_has_only_map_link():
    text = card_text(_place(video_note=""), "Tokyo", None, None)
    assert "from" not in text and "Map ↗" in text


def test_low_and_far_cards_ask_and_offer_wrong_place():
    low = _place(confidence="low", lat=35.6, lng=139.7, address="1-2 Shibuya")
    assert "Is this right? 1-2 Shibuya" in card_text(low, "Tokyo", None, None)
    assert len(_buttons(card_keyboard(low, VoteCounts()))) == 2
    far = _place(confidence="far", lat=34.7, lng=135.5)
    assert "⚠️ Not near Tokyo" in card_text(far, "Tokyo", None, None)
    high = _place(confidence="high", lat=35.6, lng=139.7)
    assert len(_buttons(card_keyboard(high, VoteCounts()))) == 1


def test_vote_buttons_show_counts_and_fit_telegram_limit():
    rows = _buttons(card_keyboard(_place(id=10**9), VoteCounts(2, 0, 1)))
    assert rows[0] == [
        ("✅ Must 2", f"v:{10**9}:m"),
        ("🤔 Maybe 0", f"v:{10**9}:y"),
        ("❌ Skip 1", f"v:{10**9}:s"),
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
