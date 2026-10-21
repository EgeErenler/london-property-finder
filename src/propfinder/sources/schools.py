"""Department for Education, Get Information About Schools: every open school in London."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from propfinder import http
from propfinder.config import GIAS_URL, LONDON_SCHOOL_LAS
from propfinder.geo import grid_to_latlon

log = logging.getLogger(__name__)

USE = {
    "URN": "urn",
    "EstablishmentName": "name",
    "LA (code)": "la",
    "EstablishmentStatus (name)": "status",
    "PhaseOfEducation (name)": "phase",
    "EstablishmentTypeGroup (name)": "type_group",
    "TypeOfEstablishment (name)": "type",
    "Gender (name)": "gender",
    "ReligiousCharacter (name)": "religion",
    "NumberOfPupils": "pupils",
    "Postcode": "postcode",
    "SchoolWebsite": "website",
    "Easting": "easting",
    "Northing": "northing",
}


def fetch(raw_dir: Path, today: date | None = None) -> Path:
    today = today or date.today()
    for back in range(7):
        url = GIAS_URL.format(day=(today - timedelta(days=back)).strftime("%Y%m%d"))
        if http.exists(url):
            return http.download(url, raw_dir / "schools" / "gias.csv")
    raise RuntimeError("No schools file found for the last seven days")


def phase_group(phase: str) -> str | None:
    """Primary, Secondary or None (nurseries, colleges and special schools without a phase)."""
    if phase in ("Primary", "Middle deemed primary"):
        return "Primary"
    if phase in ("Secondary", "Middle deemed secondary", "All-through"):
        return "Secondary"
    return None


def clean(csv_path: Path, clean_dir: Path) -> Path:
    clean_dir.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(
        csv_path, encoding="cp1252", usecols=list(USE), dtype=str, low_memory=False
    ).rename(columns=USE)
    df = df[(df["status"] == "Open") & df["la"].isin(LONDON_SCHOOL_LAS)].copy()
    df["level"] = df["phase"].map(phase_group)
    df["easting"] = pd.to_numeric(df["easting"], errors="coerce")
    df["northing"] = pd.to_numeric(df["northing"], errors="coerce")
    df["pupils"] = pd.to_numeric(df["pupils"], errors="coerce")
    df["independent"] = df["type_group"].eq("Independent schools")
    df = df[df["level"].notna() & (df["easting"] > 0)].copy()
    df["lat"], df["lon"] = grid_to_latlon(df["easting"], df["northing"])
    cols = [
        "urn",
        "name",
        "level",
        "phase",
        "type",
        "independent",
        "gender",
        "religion",
        "pupils",
        "postcode",
        "website",
        "easting",
        "northing",
        "lat",
        "lon",
    ]
    target = clean_dir / "schools.parquet"
    df[cols].to_parquet(target, index=False)
    log.info("schools: %d primary and secondary schools", len(df))
    return target
