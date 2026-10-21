/* London Property Finder. Plain JavaScript, no build step. */
(() => {
  "use strict";

  // ---------- Settings ----------
  const FACTORS = [
    { key: "safety", label: "Low crime", short: "Safety" },
    { key: "transport", label: "Near a station", short: "Transport" },
    { key: "shops", label: "Near a supermarket", short: "Shops" },
    { key: "schools", label: "Schools nearby", short: "Schools" },
    { key: "value", label: "Priced below the area", short: "Value" },
    { key: "growth", label: "Price growth", short: "Growth" },
    { key: "yield", label: "Rental yield", short: "Yield" },
  ];
  const PERSONAS = {
    balanced: { safety: 2, transport: 2, shops: 2, schools: 2, value: 2, growth: 2, yield: 2 },
    investor: { safety: 1, transport: 2, shops: 1, schools: 0, value: 3, growth: 2, yield: 3 },
    family: { safety: 3, transport: 1, shops: 1, schools: 3, value: 1, growth: 1, yield: 0 },
    professional: { safety: 2, transport: 3, shops: 2, schools: 0, value: 1, growth: 1, yield: 0 },
  };
  const TYPES = { F: "Flat", T: "Terraced", S: "Semi-detached", D: "Detached" };
  const TYPE_PLURAL = { F: "Flats", T: "Terraced", S: "Semis", D: "Detached" };
  const PRICE_STEPS = [100, 150, 200, 250, 300, 350, 400, 450, 500, 550, 600, 650, 700, 750, 800,
    900, 1000, 1250, 1500, 1750, 2000, 2500, 3000, 4000, 5000].map((k) => k * 1000);
  const PAGE = 60;
  const WALK = 80; // metres per minute

  const state = {
    min: 0, max: 0, types: new Set(["F", "T", "S", "D"]), persona: "balanced",
    weights: { ...PERSONAS.balanced }, borough: "", walk: "", safety: "", tenure: "",
    valueOnly: false, busyOnly: false, sort: "match", shown: PAGE, selected: null,
  };
  let streets = [], meta = null, boroughs = new Map(), results = [], map, layer, markers = new Map();
  const homesCache = new Map();
  const $ = (id) => document.getElementById(id);

  // ---------- Formatting ----------
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const money = (v) => {
    if (v == null) return "–";
    if (v >= 1e6) return "£" + (v / 1e6).toFixed(v >= 1e7 ? 1 : 2).replace(/\.?0+$/, "") + "m";
    return "£" + Math.round(v / 1000) + "k";
  };
  const moneyFull = (v) => (v == null ? "–" : "£" + Math.round(v).toLocaleString("en-GB"));
  const pct = (v, d = 1) => (v == null ? "–" : (v * 100).toFixed(d) + "%");
  const mins = (m) => Math.max(1, Math.round(m / WALK));
  const monthName = (iso) => {
    if (!iso) return "";
    const [y, m] = iso.split("-");
    return new Date(+y, +m - 1, 1).toLocaleDateString("en-GB", { month: "short", year: "numeric" });
  };
  const dayName = (iso) => new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });

  // ---------- Data ----------
  const toObjects = (t) => t.rows.map((r) => Object.fromEntries(t.columns.map((c, i) => [c, r[i]])));

  async function load() {
    const [m, s] = await Promise.all([
      fetch("data/meta.json").then((r) => r.json()),
      fetch("data/streets.json").then((r) => r.json()),
    ]);
    meta = m;
    streets = toObjects(s);
    for (const b of toObjects(meta.boroughs)) boroughs.set(b.la_code, b);
    for (const st of streets) st.borough = boroughs.get(st.la_code)?.borough || "";
  }

  async function homesFor(outcode) {
    if (!homesCache.has(outcode)) {
      homesCache.set(outcode, fetch(`data/homes/${encodeURIComponent(outcode)}.json`)
        .then((r) => (r.ok ? r.json() : { columns: [], rows: [] }))
        .then(toObjects));
    }
    return homesCache.get(outcode);
  }

  // ---------- Matching ----------
  function priceBand(st, t) {
    const n = st[`n_${t.toLowerCase()}`];
    if (!n) return null;
    const med = st[`med_${t.toLowerCase()}`];
    const lo = st[`p25_${t.toLowerCase()}`] ?? med;
    const hi = st[`p75_${t.toLowerCase()}`] ?? med;
    return { type: t, n, med, lo, hi };
  }

  function bandsInBudget(st) {
    const out = [];
    for (const t of state.types) {
      const b = priceBand(st, t);
      if (!b) continue;
      if (state.min && b.hi < state.min) continue;
      if (state.max && b.lo > state.max) continue;
      out.push(b);
    }
    return out.sort((a, b) => b.n - a.n);
  }

  function matchScore(st) {
    let sum = 0, w = 0;
    for (const f of FACTORS) {
      const s = st[`score_${f.key}`], wt = state.weights[f.key];
      if (s == null || !wt) continue;
      sum += s * wt;
      w += wt;
    }
    return w ? Math.round(sum / w) : 0;
  }

  const isValuePick = (st) => st.value_gap != null && st.value_gap <= -0.1 && st.homes >= 5;

  function applyFilters() {
    const out = [];
    for (const st of streets) {
      if (state.borough && st.la_code !== state.borough) continue;
      if (state.walk && (st.station_dist == null || st.station_dist / WALK > +state.walk)) continue;
      if (state.safety && (st.score_safety ?? 0) < +state.safety) continue;
      if (state.tenure === "freehold" && st.leasehold_share > 0.5) continue;
      if (state.valueOnly && !isValuePick(st)) continue;
      if (state.busyOnly && st.sales < 10) continue;
      const bands = bandsInBudget(st);
      if (!bands.length) continue;
      st._bands = bands;
      st._match = matchScore(st);
      st._price = bands[0].med;
      out.push(st);
    }
    const by = {
      match: (a, b) => b._match - a._match || b.homes - a.homes,
      value: (a, b) => (a.value_gap ?? 9) - (b.value_gap ?? 9),
      yield: (a, b) => (b.gross_yield ?? -1) - (a.gross_yield ?? -1),
      growth: (a, b) => (b.score_growth ?? -1) - (a.score_growth ?? -1) || (b.growth ?? -1) - (a.growth ?? -1),
      safety: (a, b) => (b.score_safety ?? -1) - (a.score_safety ?? -1),
      price_asc: (a, b) => a._price - b._price,
      price_desc: (a, b) => b._price - a._price,
    }[state.sort];
    results = out.sort(by);
  }

  // ---------- Rendering: cards ----------
  function ring(v, small) {
    return `<div class="ring" style="--p:${v}"><span class="num">${v}</span></div>${small ? `<small>${small}</small>` : ""}`;
  }

  function tags(st) {
    const t = [];
    if (isValuePick(st)) t.push(`<span class="tag good">Value pick · ${Math.round(-st.value_gap * 100)}% below area</span>`);
    if (st.station_dist != null && st.station_dist / WALK <= 10)
      t.push(`<span class="tag">${mins(st.station_dist)} min to ${esc(st.station_name)}</span>`);
    if ((st.score_safety ?? 0) >= 75) t.push(`<span class="tag good">Low crime</span>`);
    else if (st.score_safety != null && st.score_safety <= 15) t.push(`<span class="tag warn">High crime area</span>`);
    if (st.gross_yield && (state.persona === "investor" || (st.score_yield ?? 0) >= 80))
      t.push(`<span class="tag">Yield ~${pct(st.gross_yield)}</span>`);
    if (state.persona === "family" && st.primary_count >= 3) t.push(`<span class="tag">${st.primary_count} primary schools in 1 km</span>`);
    return t.join("");
  }

  function priceLine(st) {
    return st._bands.slice(0, 2).map((b) =>
      `${TYPE_PLURAL[b.type]} <strong class="num">${money(b.med)}</strong>` +
      (b.n >= 4 ? ` <span class="muted num">(${money(b.lo)}–${money(b.hi)})</span>` : "")
    ).join(" &nbsp;·&nbsp; ");
  }

  function card(st, i) {
    const bars = FACTORS.map((f) => {
      const v = st[`score_${f.key}`];
      return `<div title="${f.label}: ${v ?? "not enough data"}"><i style="--v:${v ?? 0}"></i>${f.short}</div>`;
    }).join("");
    return `<li class="card${state.selected === st.id ? " is-selected" : ""}" data-id="${st.id}">
      <div><h2>${i + 1}. ${esc(st.street)}</h2><div class="where">${esc(st.outcode)} · ${esc(st.borough)} · ${st.homes} homes sold</div></div>
      <div class="score">${ring(st._match, "match")}</div>
      <div class="price">${priceLine(st)}</div>
      <div class="tags">${tags(st)}</div>
      <div class="bars">${bars}</div>
    </li>`;
  }

  function renderCards() {
    const list = $("cards");
    const n = results.length;
    const typeText = state.types.size === 4 ? "homes" : [...state.types].map((t) => TYPE_PLURAL[t].toLowerCase()).join(", ");
    const budget = state.min || state.max
      ? ` ${state.min ? "from " + money(state.min) : ""}${state.min && state.max ? " " : ""}${state.max ? "up to " + money(state.max) : ""}`
      : "";
    $("resultTitle").textContent = n ? `${n.toLocaleString("en-GB")} streets match` : "No streets match";
    $("resultSub").textContent = `${typeText}${budget}${state.borough ? " in " + boroughs.get(state.borough)?.borough : " across London"}, sorted by ${$("sort").selectedOptions[0].text.toLowerCase()}`;
    if (!n) {
      list.innerHTML = `<li class="empty">Try a wider budget, more property types or fewer filters.</li>`;
      $("loadMore").hidden = true;
      return;
    }
    list.innerHTML = results.slice(0, state.shown).map(card).join("");
    $("loadMore").hidden = n <= state.shown;
  }

  // ---------- Rendering: map ----------
  const colourFor = (v) => (v >= 75 ? "#0b6e4f" : v >= 65 ? "#2b9b6e" : v >= 55 ? "#6fbd9b" : v >= 45 ? "#b7dccb" : "#dfe9e3");

  function initMap() {
    map = L.map("map", { preferCanvas: true, zoomControl: true }).setView([51.505, -0.11], 11);
    L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
      maxZoom: 19, subdomains: "abcd",
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
    }).addTo(map);
    layer = L.layerGroup().addTo(map);
  }

  function renderMap(fit) {
    layer.clearLayers();
    markers.clear();
    const subset = results.slice(0, 6000);
    for (const st of subset.slice().reverse()) {
      const m = L.circleMarker([st.lat, st.lon], {
        radius: Math.min(9, 3.5 + Math.sqrt(st.homes) / 2.2),
        weight: 1, color: "#14213d", opacity: 0.35,
        fillColor: colourFor(st._match), fillOpacity: 0.9,
      });
      m.bindTooltip(`<b>${esc(st.street)}</b>, ${esc(st.outcode)}<br>Match ${st._match} · ${TYPE_PLURAL[st._bands[0].type]} ${money(st._bands[0].med)}`, { className: "street-tip", direction: "top" });
      m.on("click", () => openDetail(st.id, true));
      m.addTo(layer);
      markers.set(st.id, m);
    }
    if (fit && subset.length) {
      const b = L.latLngBounds(subset.map((s) => [s.lat, s.lon]));
      map.fitBounds(b.pad(0.05), { maxZoom: 15 });
    }
  }

  // ---------- Street detail ----------
  function scoreRow(label, v, text) {
    return `<div class="srow"><span>${label}</span><div class="track"><i style="width:${v ?? 0}%"></i></div><em class="num">${v ?? "–"}</em><small>${text}</small></div>`;
  }

  function portalLinks(st) {
    const oc = st.outcode.toLowerCase();
    const q = (a, b) => [state.min ? `${a}=${state.min}` : "", state.max ? `${b}=${state.max}` : ""].filter(Boolean).join("&");
    const rm = q("minPrice", "maxPrice"), zp = q("price_min", "price_max"), otm = q("min-price", "max-price");
    return `<div class="portals">
      <a class="portal" target="_blank" rel="noopener" href="https://www.rightmove.co.uk/property-for-sale/${st.outcode.toUpperCase()}.html${rm ? "?" + rm : ""}">Rightmove</a>
      <a class="portal" target="_blank" rel="noopener" href="https://www.zoopla.co.uk/for-sale/property/${oc}/${zp ? "?" + zp : ""}">Zoopla</a>
      <a class="portal" target="_blank" rel="noopener" href="https://www.onthemarket.com/for-sale/property/${oc}/${otm ? "?" + otm : ""}">OnTheMarket</a>
    </div>
    <p class="muted" style="font-size:12.5px;margin:8px 0 0">Opens homes for sale in ${esc(st.outcode)}${state.min || state.max ? " within your budget" : ""}. To rent: <a target="_blank" rel="noopener" href="https://www.zoopla.co.uk/to-rent/property/${oc}/">Zoopla</a> · <a target="_blank" rel="noopener" href="https://www.rightmove.co.uk/property-to-rent/${st.outcode.toUpperCase()}.html">Rightmove</a></p>`;
  }

  function nearIcon(kind) {
    const p = {
      train: '<path d="M6 3h8a2 2 0 012 2v8a2 2 0 01-2 2H6a2 2 0 01-2-2V5a2 2 0 012-2zM4 9h12M7 18l-1.5 2M13 18l1.5 2" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><circle cx="7.5" cy="12" r="1" fill="currentColor"/><circle cx="12.5" cy="12" r="1" fill="currentColor"/>',
      shop: '<path d="M3 4h2l2 9h9l2-6H6" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/><circle cx="8" cy="16.5" r="1.3" fill="currentColor"/><circle cx="15" cy="16.5" r="1.3" fill="currentColor"/>',
      school: '<path d="M2 8l8-4 8 4-8 4-8-4zM5 9.5V14c1.5 1.4 3.2 2 5 2s3.5-.6 5-2V9.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>',
    }[kind];
    return `<svg viewBox="0 0 20 20" aria-hidden="true">${p}</svg>`;
  }

  async function openDetail(id, fromMap) {
    const st = streets.find((s) => s.id === id);
    if (!st) return;
    state.selected = id;
    document.querySelectorAll(".card.is-selected").forEach((c) => c.classList.remove("is-selected"));
    const cardEl = document.querySelector(`.card[data-id="${id}"]`);
    if (cardEl) {
      cardEl.classList.add("is-selected");
      if (fromMap) cardEl.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
    if (map) map.panTo([st.lat, st.lon]);
    const b = boroughs.get(st.la_code) || {};
    const match = st._match ?? matchScore(st);
    const gap = st.value_gap;
    const gapText = gap == null ? "No comparison available"
      : `Typical home here is ${Math.abs(Math.round(gap * 100))}% ${gap < 0 ? "below" : "above"} the ${esc(st.borough)} average for the same type`;
    const growthText = st.growth != null && st.growth_pairs >= 3
      ? `Homes sold twice here gained ${pct(st.growth)} a year (${st.growth_pairs} homes)`
      : "Not enough homes sold twice here to measure";
    const types = ["F", "T", "S", "D"].map((t) => priceBand(st, t)).filter(Boolean);

    $("detailBody").innerHTML = `
      <h2>${esc(st.street)}</h2>
      <p class="where">${esc(st.outcode)} · ${esc(st.borough)}</p>
      <div class="d-hero">${ring(match)}<p><b>${match >= 70 ? "Strong match" : match >= 55 ? "Good match" : match >= 40 ? "Mixed match" : "Weak match"}</b> for your ${state.persona === "balanced" ? "priorities" : state.persona + " profile"}.<br>Scores compare this street with every other street in London. 100 is the best.</p></div>

      <div class="d-section"><h3>Homes for sale near here</h3>${portalLinks(st)}</div>

      <div class="d-section"><h3>Key numbers</h3><div class="kpis">
        <div class="kpi"><b class="num">${money(st.median_value)}</b><span>Typical value today</span></div>
        <div class="kpi"><b class="num">${pct(st.gross_yield)}</b><span>Estimated gross yield</span></div>
        <div class="kpi"><b class="num">${st.growth != null && st.growth_pairs >= 3 ? pct(st.growth) : "–"}</b><span>Growth per year</span></div>
        <div class="kpi"><b class="num">${pct(st.leasehold_share, 0)}</b><span>Sold as leasehold</span></div>
        <div class="kpi"><b class="num">${st.homes} / ${st.sales}</b><span>Homes / sales since 2018</span></div>
        <div class="kpi"><b>${monthName(st.last_sale)}</b><span>Most recent sale</span></div>
      </div></div>

      <div class="d-section"><h3>Prices by type, at today's level</h3>
        <table class="types"><thead><tr><th>Type</th><th>Homes</th><th>Typical</th><th>Middle half</th></tr></thead><tbody>
        ${types.map((t) => `<tr><td>${TYPES[t.type]}</td><td class="num">${t.n}</td><td class="num"><b>${money(t.med)}</b></td><td class="num">${t.n >= 4 ? money(t.lo) + "–" + money(t.hi) : "–"}</td></tr>`).join("")}
        </tbody></table></div>

      <div class="d-section"><h3>Scorecard</h3><div class="scorelist">
        ${scoreRow("Low crime", st.score_safety, `${st.crime_total} crimes reported within 250 m in 12 months (${st.crime_burglary} burglaries)`)}
        ${scoreRow("Transport", st.score_transport, `${esc(st.station_name)}, ${mins(st.station_dist)} min walk`)}
        ${scoreRow("Shops", st.score_shops, `${esc(st.shop_name)}, ${mins(st.shop_dist)} min walk`)}
        ${scoreRow("Schools", st.score_schools, `${st.primary_count} state primary schools within 1 km, ${st.secondary_count} secondary within 1.5 km`)}
        ${scoreRow("Value", st.score_value, gapText)}
        ${scoreRow("Growth", st.score_growth, growthText)}
        ${scoreRow("Yield", st.score_yield, b.rent_all ? `Based on ${esc(st.borough)} average rents (${moneyFull(b.rent_all)} a month for all homes)` : "No rent data")}
      </div></div>

      <div class="d-section"><h3>Nearby</h3><div class="near">
        <div>${nearIcon("train")}<span>${esc(st.station_name)} <span class="muted">${esc(st.station_detail)}</span></span><span class="muted num">${mins(st.station_dist)} min</span></div>
        <div>${nearIcon("shop")}<span>${esc(st.shop_name)}</span><span class="muted num">${mins(st.shop_dist)} min</span></div>
        <div>${nearIcon("school")}<span>${esc(st.primary_name)} <span class="muted">primary</span></span><span class="muted num">${mins(st.primary_dist)} min</span></div>
        <div>${nearIcon("school")}<span>${esc(st.secondary_name)} <span class="muted">secondary</span></span><span class="muted num">${mins(st.secondary_dist)} min</span></div>
      </div></div>

      <div class="d-section"><h3>Recent sales on this street</h3><div id="salesBox" class="muted">Loading sales…</div></div>
      <p class="note">Values are estimates: the last sale price of each home, brought to today's level with the UK House Price Index for ${esc(st.borough)}. They do not know about size, condition or improvements. This page is information, not financial advice.</p>
    `;
    $("detail").hidden = false;
    $("detail").scrollTop = 0;
    writeHash();

    const homes = (await homesFor(st.outcode)).filter((h) => h.street_id === st.id);
    if (state.selected !== id) return;
    const rows = homes.slice(0, 25).map((h) => {
      const addr = [h.saon, h.paon].filter(Boolean).join(", ");
      const extra = [TYPES[h.property_type], h.tenure === "L" ? "leasehold" : "freehold", h.new_build ? "new build" : ""].filter(Boolean).join(", ");
      return `<tr><td>${esc(addr)} <small>${esc(h.postcode)} · ${extra}</small></td>
        <td class="num">${moneyFull(h.price)}<small>${dayName(h.sale_date)}</small></td>
        <td class="num">${money(h.est_value)}<small>today</small></td></tr>`;
    }).join("");
    $("salesBox").outerHTML = homes.length
      ? `<table class="sales"><tbody>${rows}</tbody></table>${homes.length > 25 ? `<p class="muted" style="font-size:13px">Showing the 25 most recent of ${homes.length} homes.</p>` : ""}`
      : `<p class="muted">No sales to show.</p>`;
  }

  function closeDetail() {
    $("detail").hidden = true;
    state.selected = null;
    document.querySelectorAll(".card.is-selected").forEach((c) => c.classList.remove("is-selected"));
    writeHash();
  }

  // ---------- Boroughs view ----------
  let boroughSort = { key: "median_value", dir: -1 };
  function renderBoroughs() {
    const cols = [
      ["borough", "Borough", (b) => esc(b.borough)],
      ["median_value", "Typical value", (b) => money(b.median_value)],
      ["growth", "Growth a year", (b) => pct(b.growth)],
      ["rent_all", "Average rent", (b) => moneyFull(b.rent_all)],
      ["rent_2b", "Two-bed rent", (b) => moneyFull(b.rent_2b)],
      ["yield", "Gross yield", (b) => pct(b.yield)],
      ["streets", "Streets", (b) => b.streets.toLocaleString("en-GB")],
    ];
    const count = new Map();
    for (const s of streets) count.set(s.la_code, (count.get(s.la_code) || 0) + 1);
    const rows = [...boroughs.values()].map((b) => ({
      ...b, streets: count.get(b.la_code) || 0,
      yield: b.rent_all && b.median_value ? (12 * b.rent_all) / b.median_value : null,
    }));
    const { key, dir } = boroughSort;
    rows.sort((a, b) => (typeof a[key] === "string" ? a[key].localeCompare(b[key]) : (a[key] ?? -1) - (b[key] ?? -1)) * dir);
    $("boroughTable").innerHTML = `<thead><tr>${cols.map(([k, l]) => `<th data-key="${k}" class="${k === key ? "sorted" : ""}">${l}${k === key ? (dir < 0 ? " ↓" : " ↑") : ""}</th>`).join("")}</tr></thead>
      <tbody>${rows.map((b) => `<tr data-la="${b.la_code}">${cols.map(([, , f]) => `<td class="num">${f(b)}</td>`).join("")}</tr>`).join("")}</tbody>`;
  }

  // ---------- Method view ----------
  function renderMethod() {
    $("method").innerHTML = `
      <h1>How it works</h1>
      <p class="lead">London Property Finder ranks every London street with at least ${3} homes sold since 2018. It uses only official open data, rebuilt automatically every day.</p>
      <div class="callout">This site gives information, not financial advice. Values are estimates from past sales. Before you buy, get a survey, a valuation and advice from a solicitor.</div>
      <h2>The data</h2>
      <table>
        <tr><th>What</th><th>Source</th><th>Covers</th></tr>
        <tr><td>Every home sold</td><td>HM Land Registry Price Paid Data</td><td>${dayName(meta.sales_from)} to ${dayName(meta.sales_to)}</td></tr>
        <tr><td>Price changes since each sale</td><td>UK House Price Index, by borough and property type</td><td>Up to ${monthName(meta.hpi_month)}</td></tr>
        <tr><td>Rents</td><td>ONS Price Index of Private Rents, by borough</td><td>Latest month</td></tr>
        <tr><td>Crime</td><td>data.police.uk, street-level crime (Met Police and City of London Police)</td><td>${monthName(meta.crime_from)} to ${monthName(meta.crime_to)}</td></tr>
        <tr><td>Schools</td><td>Department for Education, Get Information About Schools</td><td>Open schools today</td></tr>
        <tr><td>Stations and supermarkets</td><td>OpenStreetMap</td><td>Today</td></tr>
        <tr><td>Postcode locations</td><td>Ordnance Survey Code-Point Open</td><td>Latest release</td></tr>
      </table>
      <h2>From sales to streets</h2>
      <p>Each home's last sale price is brought to today's level with the House Price Index for its borough and type. Homes are then grouped into streets by street name and postcode district, so a long road in two districts appears twice. A street needs at least three different homes sold to appear.</p>
      <h2>The seven scores</h2>
      <p>Each score is a percentile from 0 to 100: a score of 80 means the street does better than 80% of London streets on that measure.</p>
      <ul>
        <li><b>Low crime:</b> crimes reported within 250 metres of the middle of the street in the last 12 months. Busy town centres score low because of shoplifting and street crime, even where homes are safe.</li>
        <li><b>Transport:</b> walking distance in a straight line to the nearest Tube, rail, Overground, DLR, Elizabeth line or tram station.</li>
        <li><b>Shops:</b> distance to the nearest supermarket.</li>
        <li><b>Schools:</b> number of state primary schools within 1 km, distance to the nearest one, and secondary schools within 1.5 km. School quality is not yet included.</li>
        <li><b>Value:</b> how the street's typical home compares with homes of the same type in the same borough. A low price can mean a bargain, or a smaller or older home.</li>
        <li><b>Growth:</b> the yearly price change of homes on the street that sold twice, at least a year apart.</li>
        <li><b>Yield:</b> 12 months of the borough's average rent for that type of home, divided by today's value. This is a gross figure before costs.</li>
      </ul>
      <h2>Your match score</h2>
      <p>Your profile gives each score a weight from 0 to 3. The match score is the weighted average. You can change the weights under <b>More filters</b>.</p>
      <h2>Limits</h2>
      <ul>
        <li>The data has no floor area or number of bedrooms, so prices are not per square foot.</li>
        <li>Homes for sale come from the portals. This site links to them and does not copy their listings.</li>
        <li>Recent months are incomplete because some sales take weeks to be registered.</li>
      </ul>
      <h2>About</h2>
      <p>Built by <a href="https://egeerenler.com">Ege Erenler</a>. The code, tests and data pipeline are on <a href="https://github.com/EgeErenler/london-property-finder">GitHub</a>.</p>
      <p class="muted" style="font-size:13px">Contains HM Land Registry data © Crown copyright and database right 2026. Contains OS data © Crown copyright and database right 2026. Contains public sector information licensed under the Open Government Licence v3.0. Map data © OpenStreetMap contributors (ODbL). Last built ${dayName(meta.built_at)}.</p>`;
  }

  // ---------- Controls ----------
  function fillBudget() {
    const opt = (v, label) => `<option value="${v}">${label}</option>`;
    $("minPrice").innerHTML = opt(0, "No min") + PRICE_STEPS.map((v) => opt(v, money(v))).join("");
    $("maxPrice").innerHTML = opt(0, "No max") + PRICE_STEPS.map((v) => opt(v, money(v))).join("");
    $("borough").innerHTML = `<option value="">All of London</option>` +
      [...boroughs.values()].sort((a, b) => a.borough.localeCompare(b.borough))
        .map((b) => `<option value="${b.la_code}">${esc(b.borough)}</option>`).join("");
  }

  function renderWeights() {
    $("weights").innerHTML = FACTORS.map((f) => `
      <label class="weight"><span>${f.label}</span><output>${["Ignore", "Low", "Medium", "High"][state.weights[f.key]]}</output>
      <input type="range" min="0" max="3" step="1" value="${state.weights[f.key]}" data-weight="${f.key}"></label>`).join("");
  }

  function syncControls() {
    $("minPrice").value = state.min;
    $("maxPrice").value = state.max;
    document.querySelectorAll("#types .chip").forEach((c) => c.classList.toggle("is-on", state.types.has(c.dataset.type)));
    document.querySelectorAll("#persona button").forEach((b) => b.classList.toggle("is-on", b.dataset.persona === state.persona));
    $("borough").value = state.borough;
    $("walk").value = state.walk;
    $("safety").value = state.safety;
    $("tenure").value = state.tenure;
    $("valueOnly").checked = state.valueOnly;
    $("busyOnly").checked = state.busyOnly;
    $("sort").value = state.sort;
    const extra = [state.borough, state.walk, state.safety, state.tenure, state.valueOnly, state.busyOnly].filter(Boolean).length;
    $("moreCount").hidden = !extra;
    $("moreCount").textContent = extra;
    renderWeights();
  }

  function update({ fit = false, keepPage = false } = {}) {
    if (!keepPage) state.shown = PAGE;
    applyFilters();
    renderCards();
    if (map) renderMap(fit);
    syncControls();
    writeHash();
  }

  // ---------- URL state, so a search can be shared ----------
  function writeHash() {
    const p = new URLSearchParams();
    if (state.min) p.set("min", state.min);
    if (state.max) p.set("max", state.max);
    if (state.types.size !== 4) p.set("types", [...state.types].join(""));
    if (state.persona !== "balanced") p.set("for", state.persona);
    const base = PERSONAS[state.persona];
    if (FACTORS.some((f) => base[f.key] !== state.weights[f.key])) p.set("w", FACTORS.map((f) => state.weights[f.key]).join(""));
    for (const k of ["borough", "walk", "safety", "tenure"]) if (state[k]) p.set(k, state[k]);
    if (state.valueOnly) p.set("value", "1");
    if (state.busyOnly) p.set("busy", "1");
    if (state.sort !== "match") p.set("sort", state.sort);
    if (state.selected != null) p.set("street", state.selected);
    const view = document.querySelector(".tab.is-active")?.dataset.view;
    if (view && view !== "search") p.set("view", view);
    const s = p.toString();
    history.replaceState(null, "", s ? "#" + s : location.pathname);
  }

  function readHash() {
    const p = new URLSearchParams(location.hash.slice(1));
    state.min = +p.get("min") || 0;
    state.max = +p.get("max") || 0;
    if (p.get("types")) state.types = new Set(p.get("types").split("").filter((t) => TYPES[t]));
    if (PERSONAS[p.get("for")]) state.persona = p.get("for");
    state.weights = { ...PERSONAS[state.persona] };
    const w = p.get("w");
    if (w && w.length === FACTORS.length) FACTORS.forEach((f, i) => (state.weights[f.key] = Math.min(3, +w[i] || 0)));
    for (const k of ["borough", "walk", "safety", "tenure"]) state[k] = p.get(k) || "";
    state.valueOnly = p.get("value") === "1";
    state.busyOnly = p.get("busy") === "1";
    state.sort = p.get("sort") || "match";
    return { street: p.has("street") ? +p.get("street") : null, view: p.get("view") };
  }

  function showView(view) {
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("is-active", t.dataset.view === view));
    document.querySelectorAll(".view").forEach((v) => v.classList.toggle("is-active", v.dataset.view === view));
    const search = view === "search";
    $("searchbar").hidden = !search;
    if (!search) $("morePanel").hidden = true;
    setBarHeight();
    if (search && map) setTimeout(() => map.invalidateSize(), 0);
    writeHash();
  }

  function setBarHeight() {
    const bar = $("searchbar").hidden ? 0 : $("searchbar").offsetHeight;
    const more = $("morePanel").hidden ? 0 : $("morePanel").offsetHeight;
    document.documentElement.style.setProperty("--bar", bar + more + "px");
    if (map) map.invalidateSize();
  }

  function bind() {
    $("minPrice").onchange = (e) => { state.min = +e.target.value; if (state.max && state.min > state.max) state.max = 0; update(); };
    $("maxPrice").onchange = (e) => { state.max = +e.target.value; if (state.max && state.min > state.max) state.min = 0; update(); };
    $("types").onclick = (e) => {
      const t = e.target.closest(".chip")?.dataset.type;
      if (!t) return;
      if (state.types.has(t) && state.types.size > 1) state.types.delete(t); else state.types.add(t);
      update();
    };
    $("persona").onclick = (e) => {
      const p = e.target.closest("button")?.dataset.persona;
      if (!p) return;
      state.persona = p;
      state.weights = { ...PERSONAS[p] };
      if (p === "investor" && state.sort === "match") state.sort = "match";
      update();
    };
    $("weights").oninput = (e) => {
      const k = e.target.dataset.weight;
      if (!k) return;
      state.weights[k] = +e.target.value;
      e.target.previousElementSibling.textContent = ["Ignore", "Low", "Medium", "High"][state.weights[k]];
      applyFilters(); renderCards(); renderMap(false); writeHash();
    };
    $("moreBtn").onclick = () => {
      const panel = $("morePanel");
      panel.hidden = !panel.hidden;
      $("moreBtn").setAttribute("aria-expanded", String(!panel.hidden));
      setBarHeight();
    };
    $("borough").onchange = (e) => { state.borough = e.target.value; update({ fit: true }); };
    for (const k of ["walk", "safety", "tenure"]) $(k).onchange = (e) => { state[k] = e.target.value; update(); };
    $("valueOnly").onchange = (e) => { state.valueOnly = e.target.checked; update(); };
    $("busyOnly").onchange = (e) => { state.busyOnly = e.target.checked; update(); };
    $("sort").onchange = (e) => { state.sort = e.target.value; update(); };
    $("loadMore").onclick = () => { state.shown += PAGE; renderCards(); };
    $("cards").onclick = (e) => { const c = e.target.closest(".card"); if (c) openDetail(+c.dataset.id); };
    $("cards").onmouseover = (e) => {
      const c = e.target.closest(".card");
      const m = c && markers.get(+c.dataset.id);
      if (m) m.openTooltip();
    };
    $("closeDetail").onclick = closeDetail;
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("detail").hidden) closeDetail(); });
    document.querySelectorAll(".tab").forEach((t) => (t.onclick = () => showView(t.dataset.view)));
    document.querySelector(".mobile-switch").onclick = (e) => {
      const pane = e.target.closest("button")?.dataset.pane;
      if (!pane) return;
      document.querySelectorAll(".mobile-switch button").forEach((b) => b.classList.toggle("is-on", b.dataset.pane === pane));
      document.querySelector(".view-search").classList.toggle("show-map", pane === "map");
      if (map) setTimeout(() => map.invalidateSize(), 0);
    };
    $("boroughTable").onclick = (e) => {
      const th = e.target.closest("th");
      if (th) {
        const k = th.dataset.key;
        boroughSort = { key: k, dir: boroughSort.key === k ? -boroughSort.dir : k === "borough" ? 1 : -1 };
        renderBoroughs();
        return;
      }
      const tr = e.target.closest("tr[data-la]");
      if (tr) { state.borough = tr.dataset.la; showView("search"); update({ fit: true }); }
    };
    window.addEventListener("resize", setBarHeight);
  }

  // ---------- Start ----------
  async function start() {
    try {
      await load();
    } catch (err) {
      $("resultTitle").textContent = "The data could not be loaded";
      $("resultSub").textContent = "Please refresh the page.";
      console.error(err);
      return;
    }
    $("fresh").innerHTML = `Sales to <b>${monthName(meta.sales_to)}</b> · updated <b>${dayName(meta.built_at)}</b>`;
    fillBudget();
    const { street, view } = readHash();
    syncControls();
    bind();
    if (window.L) initMap();
    setBarHeight();
    update({ fit: !!state.borough });
    renderBoroughs();
    renderMethod();
    if (view && view !== "search") showView(view);
    if (street != null) openDetail(street);
  }

  start();
})();
