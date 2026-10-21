from datetime import date, datetime

import pandas as pd

from propfinder.sources import crime, hpi, osm, rents, schools


def test_rent_columns_are_matched_by_name():
    assert rents.rent_column("Rental price") == "rent_all"
    assert rents.rent_column("Rental price two bed") == "rent_2b"
    assert rents.rent_column("Rental price four or more bed") == "rent_4b"
    assert rents.rent_column("Rental price semidetached") == "rent_s"
    assert rents.rent_column("Rental price flat or maisonette") == "rent_f"
    assert rents.rent_column("Index two bed") is None


def test_rents_keep_latest_month_for_london_only():
    header = (
        "Time period",
        "Area code",
        "Area name",
        "Region",
        "Index",
        "Rental price",
        "Rental price flat or maisonette",
    )
    rows = [
        ("Price Index of Private Rents",),
        header,
        (datetime(2026, 7, 1), "E09000020", "Kensington and Chelsea", "London", 100, 3500, 3000),
        (datetime(2026, 8, 1), "E09000020", "Kensington and Chelsea", "London", 101, 3600, "[x]"),
        (datetime(2026, 8, 1), "E06000001", "Hartlepool", "North East", 100, 700, 600),
    ]
    df = rents.parse(rows)
    assert len(df) == 1
    assert df.loc[0, "rent_all"] == 3600
    assert pd.isna(df.loc[0, "rent_f"])


def test_find_latest_rent_file():
    html = '<a href="/file?uri=/a/16september2026/pipr.xlsx">x</a><a href="/file?uri=/a/old.xlsx">'
    assert rents.find_latest_file(html).endswith("16september2026/pipr.xlsx")


def test_crime_keeps_newest_london_street_files():
    names = [
        f"2026-0{m}/2026-0{m}-{f}-street.csv"
        for m in range(1, 10)
        for f in ("metropolitan", "city-of-london", "kent")
    ]
    names += ["2026-09/2026-09-metropolitan-outcomes.csv"]
    picked = crime.pick_files(names, months=2)
    assert picked == [
        "2026-08/2026-08-city-of-london-street.csv",
        "2026-08/2026-08-metropolitan-street.csv",
        "2026-09/2026-09-city-of-london-street.csv",
        "2026-09/2026-09-metropolitan-street.csv",
    ]


def test_hpi_months_back_crosses_the_year():
    assert hpi._months_back(date(2026, 2, 15), 3) == ["2026-02", "2026-01", "2025-12"]


def test_school_phases():
    assert schools.phase_group("Primary") == "Primary"
    assert schools.phase_group("All-through") == "Secondary"
    assert schools.phase_group("Nursery") is None


def test_osm_stations_and_supermarkets():
    data = {
        "elements": [
            {
                "type": "node",
                "lat": 51.49,
                "lon": -0.19,
                "tags": {"railway": "station", "station": "subway", "name": "Earl's Court"},
            },
            {
                "type": "way",
                "center": {"lat": 51.49, "lon": -0.19},
                "tags": {
                    "public_transport": "station",
                    "station": "subway",
                    "name": "Earl's Court",
                    "network": "London Underground",
                },
            },
            {
                "type": "node",
                "lat": 51.5,
                "lon": -0.2,
                "tags": {"shop": "supermarket", "name": "Tesco Superstore", "brand": "Tesco"},
            },
            {"type": "node", "lat": 51.5, "lon": -0.2, "tags": {"shop": "supermarket"}},
        ]
    }
    df = osm.parse(data)
    assert sorted(df["kind"]) == ["station", "supermarket"]
    assert df.loc[df["kind"] == "supermarket", "detail"].item() == "Tesco"
    assert df.loc[df["kind"] == "station", "detail"].item() == "Tube"


def test_station_modes():
    assert osm.station_modes({"network": "London Overground;National Rail"}) == "Overground, Rail"
    assert (
        osm.station_modes({"station": "light_rail", "network": "Docklands Light Railway"}) == "DLR"
    )
