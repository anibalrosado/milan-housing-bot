"""
Interactive Leaflet map generator.

Reads all non-Passed listings from the Google Sheet, attaches lat/lng via
Geocoder, and writes a self-contained mobile-first HTML file to
public/map.html.

Pin colors:
  Gold star   — Università Cattolica anchor
  Blue        — Group of 5
  Pink        — Couple
  Green ring  — Top Pick (overrides search type color)
  Grey        — Removed

Filter panel (top of screen, collapsible):
  Search type toggles, Status toggles, Removed toggle

Popup: title, price, beds, neighborhood, walk time, available-from,
  "Open Listing" and "Open in Sheet" buttons.
"""

import json
import logging
import os
import re

logger = logging.getLogger(__name__)

_SHEET_COLS = {
    "date_found":    "Date Found",
    "source":        "Source",
    "search_type":   "Search Type",
    "title":         "Title",
    "neighborhood":  "Neighborhood",
    "walk":          "Walk to Cattolica (min)",
    "price":         "Price (€/month)",
    "per_person":    "Per Person (€/mo)",
    "bedrooms":      "Bedrooms",
    "furnished":     "Furnished",
    "available":     "Available From",
    "url":           "Listing URL",
    "status":        "Status",
    "listing_status": "Listing Status",
}


class MapGenerator:
    def __init__(self, config: dict, sheets_writer, geocoder, sheet_id: str):
        self.config = config
        self.sheets_writer = sheets_writer
        self.geocoder = geocoder
        self.sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}"

    def generate(self) -> str:
        output_path = self.config["map"]["output_path"]
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Pull listings from sheet (excludes Status="Passed")
        try:
            rows = self.sheets_writer.read_all_listings()
        except Exception as exc:
            logger.error("MapGenerator: failed to read sheet: %s", exc)
            rows = []

        listings = []
        for row in rows:
            listing_status = row.get(_SHEET_COLS["listing_status"], "Active")
            if listing_status == "Passed":
                continue

            url = row.get(_SHEET_COLS["url"], "")
            if not url:
                continue

            # Geocode via cache then Nominatim
            neighborhood = row.get(_SHEET_COLS["neighborhood"], "Milan")
            address = neighborhood
            listing_hash = _url_hash(url)
            try:
                lat, lng = self.geocoder.geocode(listing_hash, address, neighborhood)
            except Exception:
                lat, lng = self.config.get("cattolica_lat", 45.4625), self.config.get("cattolica_lng", 9.1801)

            price_raw = row.get(_SHEET_COLS["price"], "")
            try:
                price = float(str(price_raw).replace(",", "")) if price_raw else None
            except ValueError:
                price = None

            listings.append({
                "title":          row.get(_SHEET_COLS["title"], "")[:80],
                "source":         row.get(_SHEET_COLS["source"], ""),
                "search_type":    row.get(_SHEET_COLS["search_type"], ""),
                "neighborhood":   neighborhood,
                "walk":           row.get(_SHEET_COLS["walk"], ""),
                "price":          price,
                "per_person":     row.get(_SHEET_COLS["per_person"], ""),
                "bedrooms":       row.get(_SHEET_COLS["bedrooms"], ""),
                "furnished":      row.get(_SHEET_COLS["furnished"], ""),
                "available":      row.get(_SHEET_COLS["available"], ""),
                "url":            url,
                "status":         row.get(_SHEET_COLS["status"], ""),
                "listing_status": listing_status,
                "lat":            lat,
                "lng":            lng,
            })

        logger.info("MapGenerator: building map with %d listing(s)", len(listings))

        cattolica = {
            "lat": self.config.get("cattolica_lat", 45.4625),
            "lng": self.config.get("cattolica_lng", 9.1801),
        }
        tile_url   = self.config["map"]["tile_url"]
        tile_attr  = self.config["map"]["tile_attribution"]
        move_in    = self.config["search"]["move_in"]
        move_out   = self.config["search"]["move_out"]

        html = _build_html(listings, cattolica, tile_url, tile_attr, self.sheet_url,
                           move_in, move_out)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)

        return output_path


# ── URL hash helper ────────────────────────────────────────────────────────────

def _url_hash(url: str) -> str:
    import hashlib
    return hashlib.sha256(url.encode()).hexdigest()[:16]


# ── HTML builder ───────────────────────────────────────────────────────────────

def _fmt_date(iso: str) -> str:
    """'2026-09-01' → 'Sep 1, 2026'"""
    try:
        from datetime import date
        d = date.fromisoformat(iso)
        return d.strftime("%b %-d, %Y")
    except Exception:
        return iso


def _build_html(
    listings: list[dict],
    cattolica: dict,
    tile_url: str,
    tile_attr: str,
    sheet_url: str,
    move_in: str = "",
    move_out: str = "",
) -> str:
    listings_json = json.dumps(listings, ensure_ascii=False)
    cattolica_json = json.dumps(cattolica)
    move_in_fmt  = _fmt_date(move_in)  if move_in  else ""
    move_out_fmt = _fmt_date(move_out) if move_out else ""
    date_range_label = f"{move_in_fmt} – {move_out_fmt}" if move_in_fmt and move_out_fmt else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Milan Housing Map</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:14px;
      display:flex;height:100vh;overflow:hidden}}

/* ── Sidebar ── */
#sidebar{{
  width:320px;flex-shrink:0;display:flex;flex-direction:column;
  height:100vh;background:#fff;border-right:1px solid #e5e7eb;
  z-index:500;
}}
#sidebar-header{{
  padding:14px 14px 10px;border-bottom:1px solid #e5e7eb;flex-shrink:0
}}
#sidebar-title{{font-size:15px;font-weight:700;color:#1a6e3c;margin-bottom:10px}}
.filter-group{{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:6px}}
.filter-group label{{
  display:flex;align-items:center;gap:4px;
  background:#f0f4f0;border-radius:20px;padding:3px 9px;
  cursor:pointer;font-size:11px;white-space:nowrap
}}
.filter-group label:hover{{background:#d8eddd}}
#sheet-link{{
  display:inline-block;margin-top:6px;font-size:11px;
  color:#1a6e3c;text-decoration:none;font-weight:600
}}
#count{{font-size:11px;color:#888;margin-top:4px}}

/* ── Listing list ── */
#listing-list{{flex:1;overflow-y:auto}}
.list-item{{
  display:flex;border-bottom:1px solid #f3f4f6;
  cursor:pointer;transition:background .15s;
}}
.list-item:hover{{background:#f9fafb}}
.list-item.active{{background:#ecfdf5;border-left:3px solid #1a6e3c}}
.list-item-bar{{width:4px;flex-shrink:0}}
.list-item-body{{padding:10px 10px 10px 8px;flex:1;min-width:0}}
.list-item-title{{
  font-size:12px;font-weight:600;color:#111;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:3px
}}
.list-item-price{{font-size:13px;font-weight:700;color:#1a6e3c}}
.list-item-meta{{font-size:11px;color:#6b7280;margin-top:2px;display:flex;gap:8px;flex-wrap:wrap}}
.list-item-removed .list-item-title{{color:#9ca3af;text-decoration:line-through}}
.list-item-removed .list-item-price{{color:#9ca3af}}

/* Mobile sidebar toggle */
#sidebar-toggle{{
  display:none;position:fixed;bottom:80px;right:14px;z-index:1500;
  background:#1a6e3c;color:#fff;border:none;border-radius:50%;
  width:48px;height:48px;font-size:20px;cursor:pointer;
  box-shadow:0 2px 8px rgba(0,0,0,.3)
}}
@media(max-width:768px){{
  #sidebar{{
    position:fixed;left:0;top:0;bottom:0;transform:translateX(-100%);
    transition:transform .25s ease;z-index:900;
  }}
  #sidebar.open{{transform:translateX(0)}}
  #sidebar-toggle{{display:flex;align-items:center;justify-content:center}}
  #map-wrap{{width:100vw}}
}}

/* ── Map ── */
#map-wrap{{flex:1;position:relative}}
#map{{width:100%;height:100%}}

/* ── Badges ── */
.badge{{
  border-radius:20px;padding:2px 8px;font-size:10px;font-weight:700;
  text-transform:uppercase;letter-spacing:.3px
}}
.badge-group{{background:#dbeafe;color:#1e40af}}
.badge-couple{{background:#fce7f3;color:#9d174d}}

/* ── Bottom-sheet popup ── */
#popup-sheet{{
  position:fixed;bottom:0;left:0;right:0;
  background:#fff;border-radius:16px 16px 0 0;
  box-shadow:0 -4px 20px rgba(0,0,0,.2);
  padding:18px 20px 28px;z-index:2000;
  transform:translateY(100%);transition:transform .3s ease;
  max-height:72vh;overflow-y:auto
}}
#popup-sheet.open{{transform:translateY(0)}}
#popup-close{{
  position:absolute;top:14px;right:16px;
  background:none;border:none;font-size:22px;cursor:pointer;color:#999;line-height:1
}}
#popup-title{{font-size:15px;font-weight:700;margin-bottom:8px;padding-right:28px}}
.popup-badges{{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px}}
.pbadge{{
  border-radius:20px;padding:3px 10px;font-size:11px;font-weight:700;
  text-transform:uppercase;letter-spacing:.4px
}}
.pbadge-group{{background:#dbeafe;color:#1e40af}}
.pbadge-couple{{background:#fce7f3;color:#9d174d}}
.pbadge-active{{background:#d1fae5;color:#065f46}}
.pbadge-removed{{background:#fee2e2;color:#991b1b}}
.pbadge-toppick{{background:#fef9c3;color:#713f12}}
.pbadge-reviewing{{background:#ede9fe;color:#5b21b6}}
.pbadge-contacted{{background:#e0f2fe;color:#075985}}
.popup-details{{font-size:13px;color:#444;line-height:1.8}}
.popup-details strong{{color:#222}}
.popup-actions{{display:flex;gap:10px;margin-top:14px;flex-wrap:wrap}}
.popup-btn{{
  flex:1;min-width:120px;padding:10px;border-radius:8px;
  font-size:13px;font-weight:600;text-align:center;
  text-decoration:none;border:none;cursor:pointer
}}
.btn-primary{{background:#1a6e3c;color:#fff}}
.btn-secondary{{background:#f3f4f6;color:#374151}}
.btn-primary:hover{{background:#145c31}}
.btn-secondary:hover{{background:#e5e7eb}}
</style>
</head>
<body>

<!-- Left sidebar -->
<div id="sidebar">
  <div id="sidebar-header">
    <div id="sidebar-title">🏠 Milan Housing</div>
    <div class="filter-group">
      <label><input type="checkbox" class="ft" data-key="group" checked> 🔵 Group of 5</label>
      <label><input type="checkbox" class="ft" data-key="couple" checked> 🩷 Couple</label>
    </div>
    <div class="filter-group">
      <label><input type="checkbox" class="ft" data-key="active" checked> Active</label>
      <label><input type="checkbox" class="ft" data-key="reviewing" checked> Reviewing</label>
      <label><input type="checkbox" class="ft" data-key="contacted" checked> Contacted</label>
      <label><input type="checkbox" class="ft" data-key="toppick" checked> ⭐ Top Pick</label>
      <label><input type="checkbox" class="ft" data-key="removed"> Removed</label>
    </div>
    <a id="sheet-link" href="{sheet_url}" target="_blank">📊 Open Google Sheet ↗</a>
    <div id="count"></div>
  </div>
  <div id="listing-list"></div>
</div>

<!-- Map -->
<div id="map-wrap">
  <div id="map"></div>
</div>

<!-- Mobile sidebar toggle -->
<button id="sidebar-toggle" title="Toggle list">☰</button>

<!-- Bottom-sheet popup -->
<div id="popup-sheet">
  <button id="popup-close">×</button>
  <div id="popup-title"></div>
  <div class="popup-badges" id="popup-badges"></div>
  <div class="popup-details" id="popup-details"></div>
  <div class="popup-actions" id="popup-actions"></div>
</div>

<script>
const LISTINGS  = {listings_json};
const CATTOLICA = {cattolica_json};
const SHEET_URL = {json.dumps(sheet_url)};
const MOVE_IN   = {json.dumps(move_in)};
const MOVE_OUT  = {json.dumps(move_out)};
const DATE_LABEL = {json.dumps(date_range_label)};

// ── Date-parameterised listing URL ────────────────────────────────────────────
function listingUrlWithDates(url, source) {{
  if (!MOVE_IN || !MOVE_OUT) return url;
  try {{
    const u = new URL(url);
    const s = (source || '').toLowerCase();
    if (s === 'spotahome')      {{ u.searchParams.set('moveInDate', MOVE_IN);  u.searchParams.set('moveOutDate', MOVE_OUT); }}
    else if (s === 'uniplaces') {{ u.searchParams.set('check_in',  MOVE_IN);  u.searchParams.set('check_out',  MOVE_OUT); }}
    else if (s === 'housinganywhere') {{ u.searchParams.set('arrival', MOVE_IN); u.searchParams.set('departure', MOVE_OUT); }}
    return u.toString();
  }} catch(e) {{ return url; }}
}}

// ── Map init ──────────────────────────────────────────────────────────────────
const map = L.map('map').setView([CATTOLICA.lat, CATTOLICA.lng], 14);
L.tileLayer({json.dumps(tile_url)}, {{
  attribution: {json.dumps(tile_attr)}, maxZoom: 19
}}).addTo(map);

// Invalidate map size after sidebar renders (prevents grey tile strip)
setTimeout(() => map.invalidateSize(), 100);

// Cattolica anchor
const catIcon = L.divIcon({{
  html: '<div style="font-size:26px;line-height:1;filter:drop-shadow(0 1px 4px rgba(0,0,0,.5))">⭐</div>',
  className:'', iconAnchor:[13,13]
}});
L.marker([CATTOLICA.lat, CATTOLICA.lng], {{icon: catIcon}})
  .addTo(map)
  .bindTooltip('Università Cattolica', {{permanent:false, direction:'top'}});

// ── Pin factory ───────────────────────────────────────────────────────────────
function makeIcon(l, selected) {{
  let bg = l.search_type === 'Group of 5' ? '#3b82f6' : '#ec4899';
  let border = selected ? '#1a6e3c' : '#fff';
  let size = selected ? 18 : 13;
  let shadow = selected ? '0 0 0 3px rgba(26,110,60,.4),0 2px 6px rgba(0,0,0,.4)' : '0 1px 4px rgba(0,0,0,.3)';
  let opacity = 1;
  const ls = (l.listing_status || '').toLowerCase();
  const st = (l.status || '').toLowerCase();
  if (st === 'top pick') border = selected ? '#1a6e3c' : '#f59e0b';
  if (ls === 'removed') {{ bg = '#9ca3af'; opacity = 0.55; }}
  return L.divIcon({{
    html: `<div style="width:${{size}}px;height:${{size}}px;border-radius:50%;
             background:${{bg}};border:2.5px solid ${{border}};
             opacity:${{opacity}};box-shadow:${{shadow}};
             transition:all .15s"></div>`,
    className:'', iconAnchor:[size/2, size/2]
  }});
}}

// ── State ─────────────────────────────────────────────────────────────────────
const filters = {{
  group:true, couple:true, active:true, reviewing:true, contacted:true, toppick:true, removed:false
}};
let visibleListings = [];
let visibleMarkers  = [];
let selectedIdx     = null;
const layerGroup    = L.layerGroup().addTo(map);

// ── Visibility test ───────────────────────────────────────────────────────────
function listingVisible(l) {{
  const st = (l.search_type || '').toLowerCase();
  const ls = (l.listing_status || 'active').toLowerCase();
  const s  = (l.status || '').toLowerCase();
  if (st === 'group of 5' && !filters.group)  return false;
  if (st === 'couple'     && !filters.couple) return false;
  if (ls === 'removed'    && !filters.removed) return false;
  if (ls === 'active' || ls === '') {{
    if ((s === '' || s === 'new' || s === 'active') && !filters.active)  return false;
    if (s === 'reviewing' && !filters.reviewing) return false;
    if (s === 'contacted' && !filters.contacted) return false;
    if (s === 'top pick'  && !filters.toppick)   return false;
  }}
  return true;
}}

// ── Render (markers + list) ───────────────────────────────────────────────────
function renderAll() {{
  layerGroup.clearLayers();
  visibleListings = [];
  visibleMarkers  = [];
  selectedIdx     = null;
  document.getElementById('listing-list').innerHTML = '';
  document.getElementById('popup-sheet').classList.remove('open');

  LISTINGS.forEach(l => {{
    if (!listingVisible(l)) return;
    const idx = visibleListings.length;
    visibleListings.push(l);

    // Map marker
    const m = L.marker([l.lat, l.lng], {{icon: makeIcon(l, false)}});
    m.on('click', (e) => {{ L.DomEvent.stopPropagation(e); selectListing(idx); }});
    layerGroup.addLayer(m);
    visibleMarkers.push(m);

    // List row
    document.getElementById('listing-list').appendChild(buildListItem(l, idx));
  }});

  document.getElementById('count').textContent =
    `${{visibleListings.length}} listing(s) shown`;
}}

// ── Build list item DOM ───────────────────────────────────────────────────────
function buildListItem(l, idx) {{
  const bar   = l.search_type === 'Group of 5' ? '#3b82f6' : '#ec4899';
  const price     = l.price      ? `€${{Number(l.price).toLocaleString()}}/mo` : '—';
  const perPerson = l.per_person ? ` · €${{Number(l.per_person).toLocaleString()}}/pp` : '';
  const walk  = l.walk  ? `🚶 ${{l.walk}} min` : '';
  const beds  = l.bedrooms ? `${{l.bedrooms}}BR` : '';
  const ls    = (l.listing_status || '').toLowerCase();
  const st    = (l.status || '').toLowerCase();

  let statusTag = '';
  if (ls === 'removed')   statusTag = '<span class="badge badge-removed" style="font-size:9px">removed</span>';
  else if (st==='top pick') statusTag = '<span style="font-size:10px">⭐</span>';

  const div = document.createElement('div');
  div.className = 'list-item' + (ls === 'removed' ? ' list-item-removed' : '');
  div.dataset.index = idx;
  div.innerHTML = `
    <div class="list-item-bar" style="background:${{bar}}"></div>
    <div class="list-item-body">
      <div class="list-item-title">${{l.title}} ${{statusTag}}</div>
      <div class="list-item-price">${{price}}<span style="font-weight:400;color:#555;font-size:11px">${{perPerson}}</span></div>
      <div class="list-item-meta">
        ${{beds ? `<span>${{beds}}</span>` : ''}}
        ${{walk ? `<span>${{walk}}</span>` : ''}}
        <span>${{l.neighborhood}}</span>
        <span style="color:#9ca3af">${{l.source}}</span>
      </div>
    </div>`;
  div.addEventListener('click', () => selectListing(idx));
  return div;
}}

// ── Select a listing ──────────────────────────────────────────────────────────
function selectListing(idx) {{
  // Deselect previous
  if (selectedIdx !== null) {{
    const prev = document.querySelector(`.list-item[data-index="${{selectedIdx}}"]`);
    if (prev) prev.classList.remove('active');
    if (visibleMarkers[selectedIdx])
      visibleMarkers[selectedIdx].setIcon(makeIcon(visibleListings[selectedIdx], false));
  }}

  selectedIdx = idx;
  const l = visibleListings[idx];
  if (!l) return;

  // Highlight list row
  const row = document.querySelector(`.list-item[data-index="${{idx}}"]`);
  if (row) {{
    row.classList.add('active');
    row.scrollIntoView({{behavior:'smooth', block:'nearest'}});
  }}

  // Enlarge / highlight marker
  if (visibleMarkers[idx])
    visibleMarkers[idx].setIcon(makeIcon(l, true));

  openPopup(l);
  map.panTo([l.lat, l.lng], {{animate:true, duration:0.4}});
}}

// ── Popup ─────────────────────────────────────────────────────────────────────
function openPopup(l) {{
  document.getElementById('popup-title').textContent = l.title;

  const badges = document.getElementById('popup-badges');
  badges.innerHTML = '';
  const stCls = l.search_type === 'Group of 5' ? 'pbadge-group' : 'pbadge-couple';
  badges.innerHTML += `<span class="pbadge ${{stCls}}">${{l.search_type}}</span>`;
  const ls = (l.listing_status || 'active').toLowerCase();
  const st = (l.status || '').toLowerCase();
  if      (ls === 'removed')   badges.innerHTML += '<span class="pbadge pbadge-removed">Removed</span>';
  else if (st === 'top pick')  badges.innerHTML += '<span class="pbadge pbadge-toppick">⭐ Top Pick</span>';
  else if (st === 'reviewing') badges.innerHTML += '<span class="pbadge pbadge-reviewing">Reviewing</span>';
  else if (st === 'contacted') badges.innerHTML += '<span class="pbadge pbadge-contacted">Contacted</span>';
  else                         badges.innerHTML += '<span class="pbadge pbadge-active">Active</span>';

  const price     = l.price      ? `€${{Number(l.price).toLocaleString()}}/mo` : '—';
  const perPerson = l.per_person ? `€${{Number(l.per_person).toLocaleString()}}/mo per person` : '';
  const walk  = l.walk  ? `${{l.walk}} min walk to Cattolica` : '';
  const beds  = l.bedrooms ? `${{l.bedrooms}} bedroom(s)` : '';
  const furn  = (l.furnished === true  || l.furnished === 'TRUE')  ? 'Furnished'   :
                (l.furnished === false || l.furnished === 'FALSE') ? 'Unfurnished' : '';
  const avail = l.available || '';

  let d = `<strong>Price:</strong> ${{price}}`;
  if (perPerson) d += ` <span style="font-size:12px;color:#555">(≈ ${{perPerson}})</span>`;
  if (DATE_LABEL) d += ` <span style="font-size:11px;color:#888">(for ${{DATE_LABEL}})</span>`;
  d += '<br>';
  if (DATE_LABEL) d += `<strong>Stay:</strong> ${{DATE_LABEL}}<br>`;
  if (beds)  d += `<strong>Bedrooms:</strong> ${{beds}}<br>`;
  if (furn)  d += `<strong>Furnished:</strong> ${{furn}}<br>`;
  if (avail) d += `<strong>Available:</strong> ${{avail}}<br>`;
  d += `<strong>Neighborhood:</strong> ${{l.neighborhood}}`;
  if (walk)  d += ` · ${{walk}}`;
  d += `<br><strong>Source:</strong> ${{l.source}}`;
  document.getElementById('popup-details').innerHTML = d;

  const listingUrl = listingUrlWithDates(l.url, l.source);
  document.getElementById('popup-actions').innerHTML = `
    <a class="popup-btn btn-primary"   href="${{listingUrl}}" target="_blank">Open Listing ↗</a>
    <a class="popup-btn btn-secondary" href="${{SHEET_URL}}"  target="_blank">Open Sheet ↗</a>`;

  document.getElementById('popup-sheet').classList.add('open');
}}

// ── Close popup ───────────────────────────────────────────────────────────────
function closePopup() {{
  document.getElementById('popup-sheet').classList.remove('open');
  if (selectedIdx !== null) {{
    const row = document.querySelector(`.list-item[data-index="${{selectedIdx}}"]`);
    if (row) row.classList.remove('active');
    if (visibleMarkers[selectedIdx])
      visibleMarkers[selectedIdx].setIcon(makeIcon(visibleListings[selectedIdx], false));
    selectedIdx = null;
  }}
}}
document.getElementById('popup-close').addEventListener('click', closePopup);
map.on('click', closePopup);

// ── Filters ───────────────────────────────────────────────────────────────────
document.querySelectorAll('.ft').forEach(cb => {{
  cb.addEventListener('change', () => {{
    filters[cb.dataset.key] = cb.checked;
    renderAll();
  }});
}});

// ── Mobile sidebar toggle ─────────────────────────────────────────────────────
document.getElementById('sidebar-toggle').addEventListener('click', () => {{
  const sb = document.getElementById('sidebar');
  sb.classList.toggle('open');
  setTimeout(() => map.invalidateSize(), 260);
}});

// Close sidebar when clicking map on mobile
map.on('click', () => {{
  if (window.innerWidth <= 768)
    document.getElementById('sidebar').classList.remove('open');
}});

// ── Boot ──────────────────────────────────────────────────────────────────────
renderAll();
</script>
</body>
</html>"""
