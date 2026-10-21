"""Ordnance Survey Code-Point Open: the location of every London postcode."""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path

import duckdb

from propfinder import http
from propfinder.config import CODEPOINT_URL, LONDON_PREFIX
from propfinder.geo import grid_to_latlon

log = logging.getLogger(__name__)

COLUMNS = {
    "postcode": "VARCHAR",
    "quality": "INTEGER",
    "easting": "DOUBLE",
    "northing": "DOUBLE",
    "country": "VARCHAR",
    "nhs_region": "VARCHAR",
    "nhs_ha": "VARCHAR",
    "county_code": "VARCHAR",
    "la_code": "VARCHAR",
    "ward_code": "VARCHAR",
}


def fetch(raw_dir: Path) -> Path:
    target = raw_dir / "codepoint" / "codepo_gb.zip"
    # Code-Point Open is updated four times a year; the cache key changes monthly.
    if not target.exists():
        http.download(CODEPOINT_URL, target)
    folder = target.parent / "csv"
    if not folder.exists():
        with zipfile.ZipFile(target) as archive:
            for name in archive.namelist():
                if name.startswith("Data/CSV/") and name.endswith(".csv"):
                    (folder / Path(name).name).parent.mkdir(parents=True, exist_ok=True)
                    (folder / Path(name).name).write_bytes(archive.read(name))
    return folder


def clean(folder: Path, clean_dir: Path) -> Path:
    clean_dir.mkdir(parents=True, exist_ok=True)
    df = duckdb.execute(
        """
        SELECT replace(postcode, ' ', '') AS postcode_key, easting, northing, la_code
        FROM read_csv($glob, header = false, columns = $columns)
        WHERE starts_with(la_code, $prefix) AND easting > 0 AND quality < 90
        """,
        {"glob": str(folder / "*.csv"), "columns": COLUMNS, "prefix": LONDON_PREFIX},
    ).df()
    df["lat"], df["lon"] = grid_to_latlon(df["easting"], df["northing"])
    target = clean_dir / "postcodes.parquet"
    df.to_parquet(target, index=False)
    log.info("postcodes: %s London postcodes", f"{len(df):,}")
    return target
