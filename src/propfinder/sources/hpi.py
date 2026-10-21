"""UK House Price Index: monthly price index for each London borough and property type.

The index is used to bring an old sale price up to today's level.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import duckdb

from propfinder import http
from propfinder.config import HPI_URL, LONDON_PREFIX

log = logging.getLogger(__name__)


def _months_back(today: date, n: int) -> list[str]:
    out, year, month = [], today.year, today.month
    for _ in range(n):
        out.append(f"{year}-{month:02d}")
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return out


def fetch(raw_dir: Path, today: date | None = None) -> Path:
    for month in _months_back(today or date.today(), 6):
        url = HPI_URL.format(month=month)
        if http.exists(url):
            return http.download(url, raw_dir / "hpi" / "uk-hpi.csv")
    raise RuntimeError("No UK HPI file found for the last six months")


def clean(csv_path: Path, clean_dir: Path) -> Path:
    clean_dir.mkdir(parents=True, exist_ok=True)
    target = clean_dir / "hpi.parquet"
    duckdb.execute(
        f"""
        COPY (
            WITH src AS (
                SELECT strptime("Date", '%d/%m/%Y')::DATE AS month, "RegionName" AS borough,
                       "AreaCode" AS la_code, "Index" AS idx_all, "DetachedIndex" AS idx_d,
                       "SemiDetachedIndex" AS idx_s, "TerracedIndex" AS idx_t, "FlatIndex" AS idx_f,
                       "AveragePrice" AS avg_price
                FROM read_csv('{csv_path}', header = true, types = {{'Date': 'VARCHAR'}})
                WHERE starts_with("AreaCode", '{LONDON_PREFIX}')
            )
            UNPIVOT src ON idx_all AS 'ALL', idx_d AS 'D', idx_s AS 'S', idx_t AS 'T', idx_f AS 'F'
            INTO NAME property_type VALUE idx
        ) TO '{target}' (FORMAT parquet)
        """
    )
    rows, latest = duckdb.execute(f"SELECT count(*), max(month) FROM '{target}'").fetchone()
    log.info("hpi: %s rows up to %s", f"{rows:,}", latest)
    return target
