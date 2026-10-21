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

STREET_COLUMNS = [
    "id",
    "street",
    "outcode",
    "la_code",
    "lat",
    "lon",
    "homes",
    "sales",
    "last_sale",
    "median_value",
    "n_d",
    "p25_d",
    "med_d",
    "p75_d",
    "n_s",
    "p25_s",
    "med_s",
    "p75_s",
    "n_t",
    "p25_t",
    "med_t",
    "p75_t",
    "n_f",
    "p25_f",
    "med_f",
    "p75_f",
    "flat_share",
    "leasehold_share",
    "new_build_share",
    "growth",
    "growth_pairs",
    "value_gap",
    "gross_yield",
    "crime_total",
    "crime_burglary",
    "crime_violence",
    "crime_robbery",
    "station_name",
    "station_detail",
    "station_dist",
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
    "independent_count",
    "score_safety",
    "score_transport",
    "score_shops",
    "score_schools",
    "score_value",
    "score_growth",
    "score_yield",
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


def export(result: dict[str, pd.DataFrame], web_dir: Path, site_dir: Path) -> Path:
    if site_dir.exists():
        shutil.rmtree(site_dir)
    shutil.copytree(web_dir, site_dir)
    data = site_dir / "data"

    size = _write(data / "streets.json", table(result["streets"], STREET_COLUMNS))
    log.info("export: streets.json %.1f MB", size / 1e6)

    homes = result["homes"].sort_values(["street_id", "sale_date"], ascending=[True, False])
    for outcode, group in homes.groupby(homes["postcode"].str.split(" ").str[0]):
        _write(data / "homes" / f"{outcode}.json", table(group, HOME_COLUMNS))
    log.info(
        "export: homes for %d postcode districts", homes["postcode"].str.split(" ").str[0].nunique()
    )

    boroughs = result["boroughs"]
    meta = result["meta"].iloc[0].to_dict()
    meta = {k: _clean(v, k) for k, v in meta.items()}
    meta["built_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ")
    meta["boroughs"] = table(boroughs, list(boroughs.columns))
    _write(data / "meta.json", meta)
    return site_dir
