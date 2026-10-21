"""ONS Price Index of Private Rents: average monthly rent by borough and property type."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import openpyxl
import pandas as pd

from propfinder import http
from propfinder.config import LONDON_PREFIX, PIPR_PAGE

log = logging.getLogger(__name__)

# "Rental price ..." columns in "Table 1" of the workbook, mapped to our names.
RENT_COLUMNS = {
    "": "rent_all",
    "onebed": "rent_1b",
    "twobed": "rent_2b",
    "threebed": "rent_3b",
    "fourormorebed": "rent_4b",
    "detached": "rent_d",
    "semidetached": "rent_s",
    "terraced": "rent_t",
}


def rent_column(name: str) -> str | None:
    """Map a header such as 'Rental price two bed' to 'rent_2b'."""
    n = name.lower().strip()
    if not n.startswith("rental price"):
        return None
    rest = n.removeprefix("rental price").replace(" ", "").replace("-", "")
    if rest.startswith("flat"):
        return "rent_f"
    return RENT_COLUMNS.get(rest)


def find_latest_file(html: str) -> str:
    links = re.findall(r'href="(/file\?uri=[^"]+\.xlsx)"', html)
    if not links:
        raise RuntimeError("No rent workbook link found on the ONS dataset page")
    return "https://www.ons.gov.uk" + links[0]


def fetch(raw_dir: Path) -> Path:
    url = find_latest_file(http.get_text(PIPR_PAGE))
    return http.download(url, raw_dir / "rents" / "pipr.xlsx")


def _number(value):
    return value if isinstance(value, (int, float)) else None


def parse(rows: list[tuple]) -> pd.DataFrame:
    """Turn the rows of Table 1 into one row per London borough for the latest month."""
    header_at = next(i for i, r in enumerate(rows) if r and r[0] == "Time period")
    header = [str(h).strip() if h else "" for h in rows[header_at]]
    wanted = {}
    for i, name in enumerate(header):
        ours = rent_column(name)
        if ours:
            wanted.setdefault(ours, i)
    records = []
    for r in rows[header_at + 1 :]:
        if not r or not r[1] or not str(r[1]).startswith(LONDON_PREFIX):
            continue
        rec = {"month": pd.Timestamp(r[0]), "la_code": r[1], "borough": r[2]}
        rec.update({ours: _number(r[i]) for ours, i in wanted.items()})
        records.append(rec)
    df = pd.DataFrame(records)
    for ours in [*RENT_COLUMNS.values(), "rent_f"]:
        if ours not in df:
            df[ours] = None  # keep the schema stable if ONS renames a column
    return df[df["month"] == df["month"].max()].reset_index(drop=True)


def clean(xlsx_path: Path, clean_dir: Path) -> Path:
    clean_dir.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    df = parse(list(wb["Table 1"].iter_rows(values_only=True)))
    target = clean_dir / "rents.parquet"
    df.to_parquet(target, index=False)
    log.info("rents: %d boroughs for %s", len(df), df["month"].max().date())
    return target
