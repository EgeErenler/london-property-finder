"""Synthetic clean tables in the real schemas, for tests and for working on the app offline.

The numbers are made up. They only need to look like London so the app can be built and checked.
"""

from __future__ import annotations

import string
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from propfinder.geo import grid_to_latlon

BOROUGHS = [
    ("E09000020", "Kensington and Chelsea", 525500, 178500, 1_300_000, "SW5"),
    ("E09000033", "City of Westminster", 529000, 181000, 1_000_000, "W2"),
    ("E09000022", "Lambeth", 531000, 175500, 560_000, "SE11"),
    ("E09000030", "Tower Hamlets", 535500, 181500, 480_000, "E14"),
    ("E09000017", "Hillingdon", 507500, 184000, 470_000, "UB8"),
    ("E09000002", "Barking and Dagenham", 547500, 184500, 360_000, "RM9"),
]
STREET_WORDS = [
    "Oak",
    "Park",
    "Church",
    "Mill",
    "Victoria",
    "Albert",
    "Station",
    "Grove",
    "Kings",
    "Queens",
    "Cedar",
    "Elm",
    "Manor",
    "Rose",
    "Hill",
    "Garden",
]
SUFFIX = ["Road", "Street", "Avenue", "Gardens", "Lane", "Close", "Square", "Crescent"]
TYPE_FACTOR = {"D": 2.0, "S": 1.4, "T": 1.15, "F": 0.65}


def write_sample(clean_dir: Path, seed: int = 11, streets_per_borough: int = 40) -> Path:
    rng = np.random.default_rng(seed)
    clean_dir.mkdir(parents=True, exist_ok=True)
    today = date.today()
    months = pd.date_range("2017-01-01", today.replace(day=1), freq="MS")

    postcodes, sales, hpi = [], [], []
    tid = 0
    for la, borough, east, north, level, outcode in BOROUGHS:
        trend = np.cumprod(1 + rng.normal(0.003, 0.006, len(months)))
        for t, f in [("ALL", 1.0), *TYPE_FACTOR.items()]:
            for m, v in zip(months, trend, strict=True):
                hpi.append(
                    {
                        "month": m.date(),
                        "borough": borough,
                        "la_code": la,
                        "avg_price": level * f * v,
                        "property_type": t,
                        "idx": 100 * v * rng.uniform(0.995, 1.005),
                    }
                )
        flat_bias = 0.8 if level > 800_000 else 0.4
        for s in range(streets_per_borough):
            name = f"{rng.choice(STREET_WORDS)} {rng.choice(SUFFIX)}"
            sx, sy = east + rng.normal(0, 1500), north + rng.normal(0, 1500)
            street_level = level * rng.lognormal(0, 0.25)
            for p in range(int(rng.integers(3, 30))):
                unit = rng.choice(list("ABDEFGHJ")) + rng.choice(list("LNPQRSTU"))
                pc = f"{outcode} {rng.integers(1, 9)}{unit}"
                key = pc.replace(" ", "")
                postcodes.append(
                    {
                        "postcode_key": key,
                        "easting": sx + rng.normal(0, 60),
                        "northing": sy + rng.normal(0, 60),
                        "la_code": la,
                    }
                )
                ptype = "F" if rng.random() < flat_bias else str(rng.choice(["D", "S", "T"]))
                paon, saon = str(rng.integers(1, 200)), (f"FLAT {p + 1}" if ptype == "F" else None)
                for _ in range(int(rng.choice([1, 1, 1, 2, 2, 3]))):
                    d = date(2018, 1, 1) + timedelta(
                        days=int(rng.integers(0, (today - date(2018, 1, 1)).days))
                    )
                    m_i = months.get_loc(pd.Timestamp(d.replace(day=1)))
                    price = (
                        street_level
                        * TYPE_FACTOR[ptype]
                        * trend[m_i]
                        / trend[-1]
                        * rng.lognormal(0, 0.12)
                    )
                    tid += 1
                    sales.append(
                        {
                            "transaction_id": f"{{{tid:08d}}}",
                            "price": int(round(price, -3)),
                            "sale_date": d,
                            "postcode": pc,
                            "postcode_key": key,
                            "property_type": ptype,
                            "new_build": bool(rng.random() < 0.05),
                            "tenure": "L" if ptype == "F" else "F",
                            "paon": paon,
                            "saon": saon,
                            "street": name.upper()
                            + f" {string.ascii_uppercase[s % 26]}" * (s >= 16),
                            "district": borough.upper(),
                        }
                    )

    pcs = pd.DataFrame(postcodes).drop_duplicates("postcode_key")
    pcs["lat"], pcs["lon"] = grid_to_latlon(pcs["easting"], pcs["northing"])
    pcs.to_parquet(clean_dir / "postcodes.parquet", index=False)
    pd.DataFrame(sales).to_parquet(clean_dir / "sales.parquet", index=False)
    hpi_df = pd.DataFrame(hpi)
    hpi_df = hpi_df[hpi_df["month"] < (today.replace(day=1) - timedelta(days=50))]
    hpi_df.to_parquet(clean_dir / "hpi.parquet", index=False)

    rents = []
    for la, borough, *_rest in BOROUGHS:
        lvl = _rest[2] / 1_000_000
        base = 1500 + 1800 * lvl
        rents.append(
            {
                "month": pd.Timestamp(today.replace(day=1)) - pd.DateOffset(months=2),
                "la_code": la,
                "borough": borough,
                "rent_all": base,
                "rent_1b": base * 0.8,
                "rent_2b": base,
                "rent_3b": base * 1.3,
                "rent_4b": base * 1.9,
                "rent_d": base * 2.2,
                "rent_s": base * 1.5,
                "rent_t": base * 1.3,
                "rent_f": base * 0.95,
            }
        )
    pd.DataFrame(rents).to_parquet(clean_dir / "rents.parquet", index=False)

    xs, ys = pcs["easting"].to_numpy(), pcs["northing"].to_numpy()
    n = 20000
    pick = rng.integers(0, len(xs), n)
    cats = [
        "Anti-social behaviour",
        "Violence and sexual offences",
        "Burglary",
        "Robbery",
        "Vehicle crime",
        "Other theft",
        "Shoplifting",
    ]
    last = pd.Timestamp(today.replace(day=1)) - pd.DateOffset(months=2)
    pd.DataFrame(
        {
            "month": [
                (last - pd.DateOffset(months=int(i))).strftime("%Y-%m")
                for i in rng.integers(0, 12, n)
            ],
            "category": rng.choice(cats, n),
            "easting": xs[pick] + rng.normal(0, 400, n),
            "northing": ys[pick] + rng.normal(0, 400, n),
        }
    ).to_parquet(clean_dir / "crimes.parquet", index=False)

    amen = []
    for i in range(60):
        j = rng.integers(0, len(xs))
        amen.append(
            {
                "kind": "station",
                "name": f"{rng.choice(STREET_WORDS)} Park {i}",
                "detail": str(rng.choice(["Tube", "Rail", "Overground", "Tube, Elizabeth line"])),
                "easting": xs[j] + rng.normal(0, 500),
                "northing": ys[j] + rng.normal(0, 500),
            }
        )
    for _ in range(120):
        j = rng.integers(0, len(xs))
        brand = str(rng.choice(["Tesco", "Sainsbury's", "Waitrose", "Lidl", "Aldi", "Co-op"]))
        amen.append(
            {
                "kind": "supermarket",
                "name": brand,
                "detail": brand,
                "easting": xs[j] + rng.normal(0, 300),
                "northing": ys[j] + rng.normal(0, 300),
            }
        )
    amen_df = pd.DataFrame(amen)
    amen_df["lat"], amen_df["lon"] = grid_to_latlon(amen_df["easting"], amen_df["northing"])
    amen_df.to_parquet(clean_dir / "amenities.parquet", index=False)

    schools = []
    for i in range(150):
        j = rng.integers(0, len(xs))
        level = "Primary" if i % 3 else "Secondary"
        schools.append(
            {
                "urn": str(100000 + i),
                "name": f"{rng.choice(STREET_WORDS)} {level} School",
                "level": level,
                "phase": level,
                "type": "Academy converter",
                "independent": bool(i % 10 == 0),
                "gender": "Mixed",
                "religion": "None",
                "pupils": int(rng.integers(150, 1500)),
                "postcode": "",
                "website": "",
                "easting": xs[j] + rng.normal(0, 600),
                "northing": ys[j] + rng.normal(0, 600),
            }
        )
    sch = pd.DataFrame(schools)
    sch["lat"], sch["lon"] = grid_to_latlon(sch["easting"], sch["northing"])
    sch.to_parquet(clean_dir / "schools.parquet", index=False)
    return clean_dir
