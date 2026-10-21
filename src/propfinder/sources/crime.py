"""data.police.uk: street-level crime in London for the last 12 months.

The bulk archive is large (about 1.7 GB) and holds 36 months for every police force,
so only the London street files for the newest months are extracted.
"""

from __future__ import annotations

import logging
import re
import zipfile
from pathlib import Path

import duckdb

from propfinder import http
from propfinder.config import CRIME_FORCES, CRIME_MONTHS, CRIME_URL
from propfinder.geo import latlon_to_grid

log = logging.getLogger(__name__)

STREET_FILE = re.compile(r"(\d{4}-\d{2})/\1-(" + "|".join(CRIME_FORCES) + r")-street\.csv$")


def pick_files(names: list[str], months: int = CRIME_MONTHS) -> list[str]:
    """The London street files for the newest `months` months in the archive."""
    matches = [(m.group(1), n) for n in names if (m := STREET_FILE.search(n))]
    keep = sorted({month for month, _ in matches})[-months:]
    return sorted(n for month, n in matches if month in keep)


def fetch(raw_dir: Path) -> Path:
    archive_path = raw_dir / "crime" / "latest.zip"
    folder = raw_dir / "crime" / "london"
    marker = raw_dir / "crime" / "version.txt"
    # The archive changes once a month. Skip the 1.7 GB download when we already have it.
    version = http.last_modified(CRIME_URL)
    if version and marker.exists() and marker.read_text() == version and any(folder.glob("*.csv")):
        log.info("crime: archive unchanged since %s", version)
        return folder
    http.download(CRIME_URL, archive_path, timeout=900)
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("*.csv"):
        old.unlink()
    with zipfile.ZipFile(archive_path) as archive:
        for name in pick_files(archive.namelist()):
            (folder / Path(name).name).write_bytes(archive.read(name))
    archive_path.unlink()  # too large to keep in the cache
    if version:
        marker.write_text(version)
    return folder


def clean(folder: Path, clean_dir: Path) -> Path:
    clean_dir.mkdir(parents=True, exist_ok=True)
    df = duckdb.execute(
        """
        SELECT "Month" AS month, "Crime type" AS category,
               "Latitude"::DOUBLE AS lat, "Longitude"::DOUBLE AS lon
        FROM read_csv($glob, header = true, all_varchar = true)
        WHERE "Latitude" IS NOT NULL AND "Longitude" IS NOT NULL
        """,
        {"glob": str(folder / "*.csv")},
    ).df()
    df["easting"], df["northing"] = latlon_to_grid(df["lat"], df["lon"])
    target = clean_dir / "crimes.parquet"
    df.drop(columns=["lat", "lon"]).to_parquet(target, index=False)
    log.info("crime: %s records, %s to %s", f"{len(df):,}", df["month"].min(), df["month"].max())
    return target
