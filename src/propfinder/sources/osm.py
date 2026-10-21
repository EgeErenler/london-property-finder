"""OpenStreetMap: supermarkets and rail, Tube, Overground, DLR and tram stations in London."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import pandas as pd

from propfinder import http
from propfinder.config import OVERPASS_URLS
from propfinder.geo import latlon_to_grid

log = logging.getLogger(__name__)

# A box around Greater London. Stations just outside the boundary still matter to
# streets near the edge, so a box works better here than the borough boundary.
QUERY = """
[out:json][timeout:180][bbox:51.27,-0.53,51.71,0.35];
(
  nwr["shop"="supermarket"];
  nwr["railway"~"^(station|halt)$"];
);
out center tags;
"""

# A complete answer has well over this many of each; fewer means the mirror cut it short.
MIN_SUPERMARKETS = 300
MIN_STATIONS = 300


def complete(data: dict) -> bool:
    if data.get("remark"):  # Overpass reports timeouts and errors here
        return False
    elements = data.get("elements", [])
    shops = sum(1 for e in elements if e.get("tags", {}).get("shop") == "supermarket")
    stations = len(elements) - shops
    return shops >= MIN_SUPERMARKETS and stations >= MIN_STATIONS


def fetch(raw_dir: Path, max_age_days: int = 7) -> Path:
    target = raw_dir / "osm" / "london.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    # Stations and supermarkets change slowly; a weekly refresh is enough and is kinder
    # to the free Overpass servers.
    if target.exists() and time.time() - target.stat().st_mtime < max_age_days * 86400:
        log.info("osm: using the cached file from the last %d days", max_age_days)
        return target
    errors = []
    for url in OVERPASS_URLS:
        try:
            data = http.post_json(url, {"data": QUERY})
        except Exception as exc:  # noqa: BLE001 - try the next mirror
            errors.append(f"{url}: {exc}")
            continue
        if complete(data):
            target.write_text(json.dumps(data))
            log.info("osm: %d elements from %s", len(data["elements"]), url)
            return target
        errors.append(f"{url}: incomplete answer ({len(data.get('elements', []))} elements)")
    # OpenStreetMap changes slowly, so the last complete answer is a safe fallback.
    if target.exists():
        log.warning("osm: no complete answer (%s), using the cached file", "; ".join(errors))
        return target
    raise RuntimeError("No complete answer from any Overpass mirror: " + "; ".join(errors))


def station_modes(tags: dict) -> str:
    """A short label such as 'Tube, Elizabeth line' from the station tags."""
    text = " ".join(str(tags.get(k, "")) for k in ("network", "line", "operator")).lower()
    modes = []
    if tags.get("station") == "subway" or "underground" in text:
        modes.append("Tube")
    if "elizabeth" in text:
        modes.append("Elizabeth line")
    if "overground" in text:
        modes.append("Overground")
    if tags.get("station") == "light_rail" or "docklands" in text or "dlr" in text:
        modes.append("DLR")
    if "tramlink" in text or tags.get("station") == "tram":
        modes.append("Tram")
    if not modes or "national rail" in text:
        modes.append("Rail")
    return ", ".join(dict.fromkeys(modes))


def parse(data: dict) -> pd.DataFrame:
    rows = []
    for el in data["elements"]:
        tags = el.get("tags", {})
        lat = el.get("lat", el.get("center", {}).get("lat"))
        lon = el.get("lon", el.get("center", {}).get("lon"))
        name = tags.get("name")
        if lat is None or not name:
            continue
        if tags.get("shop") == "supermarket":
            kind, detail = "supermarket", tags.get("brand") or name
        elif tags.get("railway") in ("station", "halt"):
            if tags.get("station") in ("miniature", "funicular") or tags.get("disused"):
                continue
            kind, detail = "station", station_modes(tags)
        else:
            continue
        rows.append({"kind": kind, "name": name, "detail": detail, "lat": lat, "lon": lon})
    df = pd.DataFrame(rows)
    # Stations are often mapped twice (a node and an area); keep one per name.
    df["key"] = (
        df["name"].str.lower().str.replace(r"\s+(station|underground station)$", "", regex=True)
    )
    stations = df[df["kind"] == "station"].sort_values("detail", key=lambda s: s.str.len())
    stations = stations.drop_duplicates("key", keep="last")
    df = pd.concat([df[df["kind"] == "supermarket"], stations]).drop(columns="key")
    return df.reset_index(drop=True)


def clean(json_path: Path, clean_dir: Path) -> Path:
    clean_dir.mkdir(parents=True, exist_ok=True)
    df = parse(json.loads(json_path.read_text()))
    df["easting"], df["northing"] = latlon_to_grid(df["lat"], df["lon"])
    target = clean_dir / "amenities.parquet"
    df.to_parquet(target, index=False)
    log.info("osm: %s", df["kind"].value_counts().to_dict())
    return target
