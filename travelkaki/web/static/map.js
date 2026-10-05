// TravelKaki map page logic (M3, #24). Plain JS, no build step.
// 1. Find the trip id (Telegram's start_param, or ?trip= when testing in a browser).
// 2. Fetch the trip with our signed initData.
// 3. Draw a pin per place, coloured by the group's vote.
// 4. Day tabs (M3, #25): each tab shows that day's route from the latest /plan, in order.

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
  // innerHTML escapes & < > but not quotes. We also use esc() inside attributes
  // (data-url="..."), so escape quotes too (PR #55 review).
  return div.innerHTML.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function tripId() {
  const fromTg = tg && tg.initDataUnsafe ? tg.initDataUnsafe.start_param : null;
  return fromTg || new URLSearchParams(location.search).get("trip");
}

function pin(layer, lat, lng, colour, html) {
  return L.circleMarker([lat, lng], {
    radius: 9, color: "#fff", weight: 2, fillColor: colour, fillOpacity: 0.95,
  }).addTo(layer).bindPopup(html);
}

function popupHtml(p) {
  return `<b>${esc(p.name)}</b><br>${esc(p.category)}<br>` +
    `Must-go ${p.must} · Maybe ${p.maybe} · Skip ${p.skip}<br>` +
    `<a href="#" data-url="${esc(p.maps_url)}">Open in Google Maps</a>`;
}

// Make "Open in Google Maps" style links open through Telegram.
function wireLinks(el) {
  el.querySelectorAll("a[data-url]").forEach((a) => {
    a.onclick = (ev) => { ev.preventDefault(); openLink(a.dataset.url); };
  });
}

// Fit the map to these points. With none, show the world zoomed out.
function fit(map, points) {
  if (points.length) map.fitBounds(points, { padding: [30, 30], maxZoom: 15 });
  else map.setView([20, 0], 2);
}

// The "All places" view: every pin, coloured by vote. Returns the info HTML.
function drawAll(map, layer, trip) {
  const points = [];
  if (trip.hotel) {
    pin(layer, trip.hotel.lat, trip.hotel.lng, COLOURS.hotel, `<b>${esc(trip.hotel.name)}</b><br>Hotel`);
    points.push([trip.hotel.lat, trip.hotel.lng]);
  }
  const noPin = [];
  for (const p of trip.places) {
    if (p.lat == null || p.lng == null) { noPin.push(p); continue; }
    pin(layer, p.lat, p.lng, COLOURS[p.tier] || COLOURS.maybe, popupHtml(p));
    points.push([p.lat, p.lng]);
  }
  fit(map, points);

  const legend = Object.entries({ must: "Must-go", maybe: "Maybe", skip: "Skip", hotel: "Hotel" })
    .map(([k, label]) => `<span><i class="dot" style="background:${COLOURS[k]}"></i>${label}</span>`)
    .join("");
  let html = `<div class="legend">${legend}</div>`;
  if (noPin.length) {
    html += `<h3>No pin yet (${noPin.length})</h3>` + noPin
      .map((p) => `<div>${esc(p.name)} · <a href="#" data-url="${esc(p.maps_url)}">Maps</a></div>`)
      .join("");
  }
  return html;
}

// One day's view: numbered stops in visit order, joined by a line from the hotel and back.
function drawDay(map, layer, trip, day) {
  const points = [];
  if (trip.hotel) points.push([trip.hotel.lat, trip.hotel.lng]);
  const lines = day.stops.map((x, i) => {
    if (x.lat != null && x.lng != null) {
      points.push([x.lat, x.lng]);
      L.marker([x.lat, x.lng], {
        icon: L.divIcon({ className: "num", html: String(i + 1), iconSize: [22, 22] }),
      }).addTo(layer).bindPopup(`<b>${esc(x.name)}</b><br>${x.start}–${x.end}`);
    }
    return `<div>${i + 1}. ${x.start} ${esc(x.name)}</div>`;
  });
  if (trip.hotel) {
    pin(layer, trip.hotel.lat, trip.hotel.lng, COLOURS.hotel, `<b>${esc(trip.hotel.name)}</b>`);
    points.push([trip.hotel.lat, trip.hotel.lng]);  // back to the hotel at night
  }
  L.polyline(points, { color: COLOURS.hotel, weight: 3, opacity: 0.7 }).addTo(layer);
  fit(map, points);
  // Long days have more than one link (Google Maps allows 9 stops per link).
  const links = day.links.map((url, k) =>
    `<a href="#" data-url="${esc(url)}">Directions${day.links.length > 1 ? " " + (k + 1) : ""}</a>`);
  return `<h3>${esc(day.label)}</h3>${lines.join("")}<p>${links.join(" · ")}</p>`;
}

// Tabs: "All places" plus one per planned day. Clicking a tab redraws the map.
function draw(trip) {
  const map = L.map("map");
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19, attribution: "© OpenStreetMap",
  }).addTo(map);
  // Popup links: open through Telegram (a plain link would open inside the tiny webview).
  map.on("popupopen", (e) => wireLinks(e.popup.getElement()));

  const layer = L.layerGroup().addTo(map);  // cleared on every tab switch
  const tabs = document.getElementById("tabs");
  const views = [["All places", () => drawAll(map, layer, trip)]];
  // Tabs show the date ("Sat 12 Dec"), not "Day N": free days aren't in the list,
  // so a count would not match the /plan message's day numbers (PR #57 review).
  trip.days.forEach((d) => views.push([d.label, () => drawDay(map, layer, trip, d)]));

  function show(i) {
    layer.clearLayers();
    info.innerHTML = views[i][1]();
    wireLinks(info);
    tabs.querySelectorAll("button").forEach((b, k) => b.classList.toggle("on", k === i));
  }
  tabs.innerHTML = views.map(([label]) => `<button>${esc(label)}</button>`).join("");
  tabs.querySelectorAll("button").forEach((b, i) => { b.onclick = () => show(i); });
  if (views.length === 1) tabs.style.display = "none";  // no plan yet: no tabs needed
  show(0);
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
