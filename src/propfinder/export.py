"""Write the website: the static app from web/ plus compact JSON data files."""

from __future__ import annotations

import json
import logging
import math
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

# The street list loads on every visit, so it is kept small: whole numbers only,
# prices in thousands of pounds and shares in percent. The app decodes them.
TYPES = ("f", "t", "s", "d")
CORE = {
    "id": ("id", 1),
    "street": ("street", None),
    "outcode": ("outcode", None),
    "b": ("borough_idx", 1),
    "y": ("lat", 1e5),
    "x": ("lon", 1e5),
    "homes": ("homes", 1),
    "sales": ("sales", 1),
    **{
        f"{q}_{t}": (f"{q}_{t}", 1 if q == "n" else 1e-3)
        for t in TYPES
        for q in ("n", "p25", "med", "p75")
    },
    "lease": ("leasehold_share", 100),
    "gap": ("value_gap", 1000),
    "yld": ("gross_yield", 1e4),
    "gro": ("growth", 1e4),
    "gp": ("growth_pairs", 1),
    "st": ("station_idx", 1),
    "sd": ("station_dist", 1),
    **{
        f"s_{k}": (f"score_{k}", 1)
        for k in ("safety", "transport", "shops", "schools", "value", "growth", "yield")
    },
}
STREET_COLUMNS = list(CORE)

# Loaded only when someone opens a street, one file per postcode district.
DETAIL_COLUMNS = [
    "id",
    "last_sale",
    "median_value",
    "flat_share",
    "new_build_share",
    "crime_total",
    "crime_burglary",
    "crime_violence",
    "crime_robbery",
    "stations_1km",
    "shop_name",
    "shop_detail",
    "shop_dist",
    "shops_1km",
    "primary_name",
    "primary_dist",
    "primary_count",
    "secondary_name",
    "secondary_dist",
    "secondary_count",
]

HOME_COLUMNS = [
    "street_id",
    "saon",
    "paon",
    "postcode",
    "property_type",
    "tenure",
    "new_build",
    "price",
    "sale_date",
    "est_value",
    "prev_price",
    "prev_date",
    "times_sold",
    "lat",
    "lon",
]

# How many decimals to keep for each kind of number.
ROUNDING = {
    "lat": 5,
    "lon": 5,
    "flat_share": 2,
    "leasehold_share": 2,
    "new_build_share": 2,
    "growth": 4,
    "value_gap": 3,
    "gross_yield": 4,
}


def _clean(value, col: str):
    if value is None or value is pd.NaT or (isinstance(value, float) and math.isnan(value)):
        return None
    if pd.api.types.is_scalar(value) and pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp | datetime):
        return value.strftime("%Y-%m-%d")
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float):
        digits = ROUNDING.get(col)
        if digits is None:
            return int(round(value))
        return round(value, digits)
    if hasattr(value, "isoformat"):
        return value.isoformat()[:10]
    return value


def table(df: pd.DataFrame, columns: list[str]) -> dict:
    rows = [
        [_clean(v, c) for v, c in zip(row, columns, strict=True)]
        for row in df[columns].itertuples(index=False, name=None)
    ]
    return {"columns": columns, "rows": rows}


def _write(path: Path, data) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    path.write_text(text, encoding="utf-8")
    return len(text)


def core_table(streets: pd.DataFrame) -> dict:
    rows = []
    for rec in streets.to_dict("records"):
        row = []
        for src, scale in CORE.values():
            v = rec.get(src)
            if v is None or (isinstance(v, float) and math.isnan(v)):
                row.append(None)
            elif scale is None:
                row.append(v)
            else:
                row.append(int(round(float(v) * scale)))
        rows.append(row)
    return {"columns": STREET_COLUMNS, "rows": rows}


def export(result: dict[str, pd.DataFrame], web_dir: Path, site_dir: Path) -> Path:
    if site_dir.exists():
        shutil.rmtree(site_dir)
    shutil.copytree(web_dir, site_dir)
    data = site_dir / "data"

    streets = result["streets"].copy()
    boroughs = result["boroughs"].reset_index(drop=True)
    streets["borough_idx"] = streets["la_code"].map(
        {code: i for i, code in enumerate(boroughs["la_code"])}
    )
    stations = streets[["station_name", "station_detail"]].drop_duplicates().reset_index(drop=True)
    lookup = {pair: i for i, pair in enumerate(stations.itertuples(index=False, name=None))}
    streets["station_idx"] = [
        lookup[pair]
        for pair in zip(streets["station_name"], streets["station_detail"], strict=True)
    ]
    size = _write(data / "streets.json", core_table(streets))
    log.info("export: streets.json %.1f MB for %d streets", size / 1e6, len(streets))

    homes = result["homes"].sort_values(["street_id", "sale_date"], ascending=[True, False])
    homes_by_area = dict(tuple(homes.groupby("outcode")))
    for outcode, group in streets.groupby("outcode"):
        area = {
            "streets": table(group, DETAIL_COLUMNS),
            "homes": table(homes_by_area.get(outcode, homes.iloc[:0]), HOME_COLUMNS),
        }
        _write(data / "areas" / f"{outcode}.json", area)
    log.info("export: detail files for %d postcode districts", streets["outcode"].nunique())

    meta = result["meta"].iloc[0].to_dict()
    meta = {k: _clean(v, k) for k, v in meta.items()}
    meta["built_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ")
    meta["boroughs"] = table(boroughs, list(boroughs.columns))
    meta["stations"] = stations.values.tolist()
    _write(data / "meta.json", meta)
    return site_dir
