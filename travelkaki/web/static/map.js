// TravelKaki map page logic (M3, #24). Plain JS, no build step.
// 1. Find the trip id (Telegram's start_param, or ?trip= when testing in a browser).
// 2. Fetch the trip with our signed initData.
// 3. Draw a pin per place, coloured by the group's vote.

const tg = window.Telegram ? window.Telegram.WebApp : null;
// Same colours as the vote buttons' meaning: Must-go, Maybe, Skip. Hotel is blue.
const COLOURS = { must: "#2e9e44", maybe: "#e0a000", skip: "#999999", hotel: "#2a7ae2" };
const info = document.getElementById("info");

// Open links via Telegram when we can (stays inside the app), else a new tab.
function openLink(url) {
  if (tg && tg.openLink) tg.openLink(url);
  else window.open(url, "_blank");
}

// Escape text before putting it in HTML (place names come from social posts).
function esc(text) {
  const div = document.createElement("div");
  div.textContent = text == null ? "" : String(text);
  return div.innerHTML;
}

function tripId() {
  const fromTg = tg && tg.initDataUnsafe ? tg.initDataUnsafe.start_param : null;
  return fromTg || new URLSearchParams(location.search).get("trip");
}

function pin(map, lat, lng, colour, html) {
  return L.circleMarker([lat, lng], {
    radius: 9, color: "#fff", weight: 2, fillColor: colour, fillOpacity: 0.95,
  }).addTo(map).bindPopup(html);
}

function popupHtml(p) {
  return `<b>${esc(p.name)}</b><br>${esc(p.category)}<br>` +
    `Must-go ${p.must} · Maybe ${p.maybe} · Skip ${p.skip}<br>` +
    `<a href="#" data-url="${esc(p.maps_url)}">Open in Google Maps</a>`;
}

function draw(trip) {
  const map = L.map("map");
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19, attribution: "© OpenStreetMap",
  }).addTo(map);

  const points = [];
  if (trip.hotel) {
    pin(map, trip.hotel.lat, trip.hotel.lng, COLOURS.hotel, `<b>${esc(trip.hotel.name)}</b><br>Hotel`);
    points.push([trip.hotel.lat, trip.hotel.lng]);
  }
  const noPin = [];
  for (const p of trip.places) {
    if (p.lat == null || p.lng == null) { noPin.push(p); continue; }
    pin(map, p.lat, p.lng, COLOURS[p.tier] || COLOURS.maybe, popupHtml(p));
    points.push([p.lat, p.lng]);
  }
  // Show every pin. With no pins at all, show the world zoomed out.
  if (points.length) map.fitBounds(points, { padding: [30, 30], maxZoom: 15 });
  else map.setView([20, 0], 2);

  // Popup links: open through Telegram (a plain link would open inside the tiny webview).
  map.on("popupopen", (e) => {
    const a = e.popup.getElement().querySelector("a[data-url]");
    if (a) a.onclick = (ev) => { ev.preventDefault(); openLink(a.dataset.url); };
  });

  const legend = Object.entries({ must: "Must-go", maybe: "Maybe", skip: "Skip", hotel: "Hotel" })
    .map(([k, label]) => `<span><i class="dot" style="background:${COLOURS[k]}"></i>${label}</span>`)
    .join("");
  let html = `<div class="legend">${legend}</div>`;
  if (noPin.length) {
    html += `<h3>No pin yet (${noPin.length})</h3>` + noPin
      .map((p) => `<div>${esc(p.name)} · <a href="#" data-url="${esc(p.maps_url)}">Maps</a></div>`)
      .join("");
  }
  info.innerHTML = html;
  info.querySelectorAll("a[data-url]").forEach((a) => {
    a.onclick = (ev) => { ev.preventDefault(); openLink(a.dataset.url); };
  });
}

async function main() {
  if (tg) { tg.ready(); tg.expand(); }
  const id = tripId();
  if (!id) { info.textContent = "Open this map from your trip's group chat."; return; }
  const res = await fetch(`/api/trip/${encodeURIComponent(id)}`, {
    headers: { Authorization: "tma " + (tg ? tg.initData : "") },
  });
  if (!res.ok) {
    // The server sends a short reason ("Open this from Telegram.", ...).
    const body = await res.json().catch(() => ({}));
    info.textContent = body.detail || "Could not load the trip.";
    return;
  }
  draw(await res.json());
}

main().catch(() => { info.textContent = "Could not load the trip."; });
