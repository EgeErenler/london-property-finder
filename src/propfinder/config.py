"""Paths, source URLs and constants. Paths are relative to the repository root."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

RAW_DIR = Path(os.getenv("PF_RAW_DIR", "data/raw"))
CLEAN_DIR = Path(os.getenv("PF_CLEAN_DIR", "data/clean"))
SITE_DIR = Path(os.getenv("PF_SITE_DIR", "site"))
WEB_DIR = Path(os.getenv("PF_WEB_DIR", "web"))

USER_AGENT = "london-property-finder (+https://github.com/EgeErenler/london-property-finder)"

# HM Land Registry Price Paid Data, one file per year.
PPD_URL = "https://price-paid-data.publicdata.landregistry.gov.uk/pp-{year}.csv"
FIRST_YEAR = 2018

# Ordnance Survey Code-Point Open: every postcode with its grid reference.
CODEPOINT_URL = (
    "https://api.os.uk/downloads/v1/products/CodePointOpen/downloads?area=GB&format=CSV&redirect"
)

# UK House Price Index, full file. Published monthly with a two month lag.
HPI_URL = (
    "https://publicdata.landregistry.gov.uk/market-trend-data/"
    "house-price-index-data/UK-HPI-full-file-{month}.csv"
)

# Department for Education, Get Information About Schools (all establishments).
GIAS_URL = (
    "https://ea-edubase-api-prod.azurewebsites.net/edubase/downloads/public/edubasealldata{day}.csv"
)

# ONS Price Index of Private Rents. The file name changes with every release,
# so the dataset page is read first to find the newest file.
PIPR_PAGE = (
    "https://www.ons.gov.uk/economy/inflationandpriceindices/datasets/"
    "priceindexofprivaterentsukmonthlypricestatistics"
)

# data.police.uk bulk archive: 36 months of street-level crime for every force.
CRIME_URL = "https://data.police.uk/data/archive/latest.zip"
CRIME_FORCES = ("metropolitan", "city-of-london")
CRIME_MONTHS = 12

# OpenStreetMap through the Overpass API. Mirrors are tried in order.
OVERPASS_URLS = (
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass-api.de/api/interpreter",
)

# Get Information About Schools codes for the 33 London local authorities.
LONDON_SCHOOL_LAS = tuple(str(c) for c in [*range(201, 214), *range(301, 321)])

# London boroughs have local authority codes E09000001 to E09000033.
LONDON_PREFIX = "E09"

PROPERTY_TYPES = {"D": "Detached", "S": "Semi-detached", "T": "Terraced", "F": "Flat"}

# Distances used for the street scorecard, in metres.
CRIME_RADIUS = 250
PRIMARY_RADIUS = 1000
SECONDARY_RADIUS = 1500
WALK_METRES_PER_MINUTE = 80

# A street needs this many different homes sold before it is shown.
MIN_HOMES_PER_STREET = 3


def years(today: date | None = None) -> list[int]:
    today = today or date.today()
    return list(range(FIRST_YEAR, today.year + 1))
