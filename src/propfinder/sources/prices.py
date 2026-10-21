"""HM Land Registry Price Paid Data: every residential sale in London since 2018."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import duckdb

from propfinder import http
from propfinder.config import PPD_URL, years

log = logging.getLogger(__name__)

# The files have no header row. The order is documented by HM Land Registry.
COLUMNS = {
    "transaction_id": "VARCHAR",
    "price": "BIGINT",
    "transfer_date": "TIMESTAMP",
    "postcode": "VARCHAR",
    "property_type": "VARCHAR",
    "old_new": "VARCHAR",
    "duration": "VARCHAR",
    "paon": "VARCHAR",
    "saon": "VARCHAR",
    "street": "VARCHAR",
    "locality": "VARCHAR",
    "town_city": "VARCHAR",
    "district": "VARCHAR",
    "county": "VARCHAR",
    "ppd_category": "VARCHAR",
    "record_status": "VARCHAR",
}


def fetch(raw_dir: Path) -> list[Path]:
    """Download the yearly files. The current and last year still change, so they are refreshed."""
    current = date.today().year
    paths = []
    for year in years():
        target = raw_dir / "ppd" / f"pp-{year}.csv"
        if not target.exists() or year >= current - 1:
            http.download(PPD_URL.format(year=year), target)
        paths.append(target)
    return paths


CLEAN_SQL = """
COPY (
    SELECT
        transaction_id,
        price,
        transfer_date::DATE AS sale_date,
        upper(trim(postcode)) AS postcode,
        replace(upper(postcode), ' ', '') AS postcode_key,
        property_type,
        old_new = 'Y' AS new_build,
        duration AS tenure,
        nullif(trim(paon), '') AS paon,
        nullif(trim(saon), '') AS saon,
        nullif(trim(street), '') AS street,
        district
    FROM read_csv($files, header = false, columns = $columns)
    WHERE county = 'GREATER LONDON'
      AND ppd_category = 'A'           -- standard market sales only
      AND record_status <> 'D'         -- drop deleted records
      AND property_type IN ('D', 'S', 'T', 'F')
      AND postcode IS NOT NULL
      AND street IS NOT NULL
      AND price >= 10000
    -- A record can be changed after publication; keep the latest version of each sale.
    QUALIFY row_number() OVER (PARTITION BY transaction_id ORDER BY record_status = 'A') = 1
) TO '{target}' (FORMAT parquet)
"""


def clean(csv_paths: list[Path], clean_dir: Path) -> Path:
    clean_dir.mkdir(parents=True, exist_ok=True)
    target = clean_dir / "sales.parquet"
    con = duckdb.connect()
    con.execute(
        CLEAN_SQL.format(target=target),
        {"files": [str(p) for p in csv_paths], "columns": COLUMNS},
    )
    rows = con.execute(f"SELECT count(*) FROM '{target}'").fetchone()[0]
    log.info("sales: %s London sales", f"{rows:,}")
    return target
