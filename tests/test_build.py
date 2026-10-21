import json
from datetime import date

import pandas as pd
import pytest

from propfinder.build import add_scores, build, percentile, title_case
from propfinder.export import STREET_COLUMNS, export
from propfinder.sample import write_sample


def write_minimal(clean, sale_month_index=100.0, today_index=110.0):
    """One borough, one street of four flats, plus a cheaper and a dearer street."""
    sales, postcodes = [], []
    streets = [("CHEAP ROAD", 200_000), ("MID ROAD", 300_000), ("DEAR ROAD", 400_000)]
    for s, (street, price) in enumerate(streets):
        for i in range(4):
            key = f"SW5{s}{i}AA"
            postcodes.append(
                {
                    "postcode_key": key,
                    "easting": 525000 + s * 100,
                    "northing": 178000 + i * 10,
                    "la_code": "E09000020",
                    "lat": 51.49,
                    "lon": -0.19,
                }
            )
            sales.append(
                {
                    "transaction_id": f"{s}-{i}",
                    "price": price,
                    "sale_date": date(2020, 1, 15),
                    "postcode": f"SW5 {s}{i}AA",
                    "postcode_key": key,
                    "property_type": "F",
                    "new_build": False,
                    "tenure": "L",
                    "paon": str(i),
                    "saon": None,
                    "street": street,
                    "district": "KENSINGTON AND CHELSEA",
                }
            )
    pd.DataFrame(sales).to_parquet(clean / "sales.parquet")
    pd.DataFrame(postcodes).to_parquet(clean / "postcodes.parquet")
    hpi = [
        {
            "month": m,
            "borough": "Kensington and Chelsea",
            "la_code": "E09000020",
            "avg_price": 1.0,
            "property_type": t,
            "idx": v,
        }
        for t in ("ALL", "F")
        for m, v in ((date(2020, 1, 1), sale_month_index), (date(2026, 7, 1), today_index))
    ]
    pd.DataFrame(hpi).to_parquet(clean / "hpi.parquet")
    pd.DataFrame(
        [
            {
                "month": pd.Timestamp("2026-08-01"),
                "la_code": "E09000020",
                "borough": "Kensington and Chelsea",
                "rent_all": 3000,
                "rent_f": 2500,
                "rent_d": None,
                "rent_s": None,
                "rent_t": None,
                "rent_1b": 2000,
                "rent_2b": 2600,
                "rent_3b": 3400,
                "rent_4b": 5000,
            }
        ]
    ).to_parquet(clean / "rents.parquet")
    pd.DataFrame(
        [{"month": "2026-08", "category": "Burglary", "easting": 525000.0, "northing": 178000.0}]
    ).to_parquet(clean / "crimes.parquet")
    pd.DataFrame(
        [
            {
                "kind": "station",
                "name": "Earl's Court",
                "detail": "Tube",
                "easting": 525100.0,
                "northing": 178000.0,
                "lat": 51.49,
                "lon": -0.19,
            },
            {
                "kind": "supermarket",
                "name": "Tesco",
                "detail": "Tesco",
                "easting": 525200.0,
                "northing": 178000.0,
                "lat": 51.49,
                "lon": -0.19,
            },
        ]
    ).to_parquet(clean / "amenities.parquet")
    pd.DataFrame(
        [
            {
                "urn": "1",
                "name": "A Primary",
                "level": "Primary",
                "independent": False,
                "easting": 525000.0,
                "northing": 178500.0,
            },
            {
                "urn": "2",
                "name": "A Secondary",
                "level": "Secondary",
                "independent": False,
                "easting": 525000.0,
                "northing": 179000.0,
            },
        ]
    ).to_parquet(clean / "schools.parquet")


def test_prices_are_brought_to_todays_level(tmp_path):
    write_minimal(tmp_path)
    result = build(tmp_path)
    homes = result["homes"]
    assert homes["est_value"].round().tolist() == pytest.approx(
        (homes["price"] * 1.1).round().tolist()
    )


def test_street_value_gap_and_yield(tmp_path):
    write_minimal(tmp_path)
    s = build(tmp_path)["streets"].set_index("street")
    # The borough median flat is the middle street, so it has no gap.
    assert s.loc["Mid Road", "value_gap"] == pytest.approx(0.0)
    assert s.loc["Cheap Road", "value_gap"] == pytest.approx(-1 / 3)
    # Gross yield = 12 x flat rent / today's value.
    assert s.loc["Mid Road", "gross_yield"] == pytest.approx(12 * 2500 / 330_000)
    # The cheapest street is the best value.
    assert s.loc["Cheap Road", "score_value"] > s.loc["Dear Road", "score_value"]


def test_surroundings_are_measured_in_metres(tmp_path):
    write_minimal(tmp_path)
    s = build(tmp_path)["streets"].set_index("street")
    assert s.loc["Cheap Road", "station_name"] == "Earl's Court"
    assert s.loc["Cheap Road", "station_dist"] == pytest.approx(100, abs=20)
    assert s.loc["Cheap Road", "crime_burglary"] == 1


def test_scores_are_between_0_and_100():
    df = pd.DataFrame(
        {
            "crime_total": [1, 5, 9],
            "station_dist": [100, 500, 900],
            "shop_dist": [50, 60, 70],
            "primary_count": [1, 2, 3],
            "primary_dist": [100, 200, 300],
            "secondary_count": [0, 1, 2],
            "value_gap": [-0.2, 0, 0.2],
            "growth": [0.01, 0.02, None],
            "growth_pairs": [5, 5, 0],
            "gross_yield": [0.03, 0.04, 0.05],
        }
    )
    scored = add_scores(df)
    cols = [c for c in scored if c.startswith("score_")]
    values = scored[cols].stack().dropna()
    assert values.between(0, 100).all()
    assert scored["score_safety"].tolist() == [100, 67, 33]
    assert pd.isna(scored.loc[2, "score_growth"])
    assert percentile(pd.Series([3, 1, 2])).tolist() == [100, 33, 67]


def test_title_case():
    assert title_case("ST JOHN'S WOOD ROAD") == "St John's Wood Road"


def test_sample_builds_the_site(tmp_path):
    clean, web, site = tmp_path / "clean", tmp_path / "web", tmp_path / "site"
    web.mkdir()
    (web / "index.html").write_text("<html></html>")
    write_sample(clean, streets_per_borough=8)
    export(build(clean), web, site)
    streets = json.loads((site / "data" / "streets.json").read_text())
    assert streets["columns"] == STREET_COLUMNS
    assert len(streets["rows"]) > 20
    meta = json.loads((site / "data" / "meta.json").read_text())
    assert meta["streets"] == len(streets["rows"])
    assert (site / "index.html").exists()
    assert any((site / "data" / "areas").glob("*.json"))
