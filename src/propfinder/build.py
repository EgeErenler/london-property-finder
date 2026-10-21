"""Turn the clean source tables into homes, streets and street scorecards.

The steps are:
1. Bring every sale price up to today's level with the UK House Price Index.
2. Keep the latest sale of each home, and pair it with the previous sale of the same home.
3. Group homes into streets (street name + postcode district).
4. Measure what is around each street: crime, stations, supermarkets and schools.
5. Turn every measure into a 0 to 100 score, where 100 is the best street in London.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from propfinder import config
from propfinder.geo import count_within, grid_to_latlon, nearest

log = logging.getLogger(__name__)

SQL = """
CREATE OR REPLACE VIEW sales AS SELECT * FROM '{clean}/sales.parquet';
CREATE OR REPLACE VIEW postcodes AS SELECT * FROM '{clean}/postcodes.parquet';
CREATE OR REPLACE VIEW hpi AS SELECT * FROM '{clean}/hpi.parquet';
CREATE OR REPLACE VIEW rents AS SELECT * FROM '{clean}/rents.parquet';

CREATE OR REPLACE TABLE boroughs AS
SELECT DISTINCT la_code, borough FROM hpi;

CREATE OR REPLACE TABLE hpi_latest AS
SELECT la_code, property_type, idx AS idx_now, month AS hpi_month
FROM hpi
QUALIFY row_number() OVER (PARTITION BY la_code, property_type ORDER BY month DESC) = 1;

-- 1. Every sale with its location and today's estimated value.
CREATE OR REPLACE TABLE sales_valued AS
WITH located AS (
    SELECT s.*, p.la_code, p.easting, p.northing, p.lat, p.lon,
           split_part(s.postcode, ' ', 1) AS outcode,
           date_trunc('month', s.sale_date)::DATE AS sale_month
    FROM sales s JOIN postcodes p USING (postcode_key)
),
indexed AS (
    SELECT l.*,
           coalesce(h_t.idx, h_a.idx) AS idx_then,
           coalesce(n_t.idx_now, n_a.idx_now) AS idx_now,
           coalesce(n_t.hpi_month, n_a.hpi_month) AS hpi_month
    FROM located l
    LEFT JOIN hpi h_t ON h_t.la_code = l.la_code AND h_t.property_type = l.property_type
                     AND h_t.month = l.sale_month
    LEFT JOIN hpi h_a ON h_a.la_code = l.la_code AND h_a.property_type = 'ALL'
                     AND h_a.month = l.sale_month
    LEFT JOIN hpi_latest n_t ON n_t.la_code = l.la_code AND n_t.property_type = l.property_type
    LEFT JOIN hpi_latest n_a ON n_a.la_code = l.la_code AND n_a.property_type = 'ALL'
)
SELECT *,
       -- Sales newer than the latest index month are already at today's level.
       CASE WHEN sale_month > hpi_month OR idx_then IS NULL OR idx_now IS NULL THEN price
            ELSE price * idx_now / idx_then END AS est_value,
       concat_ws('|', postcode_key, coalesce(saon, ''), coalesce(paon, ''), street) AS home_key,
       concat_ws('|', street, outcode) AS street_key
FROM indexed;

-- 2. One row per home: the latest sale, plus the sale before it.
CREATE OR REPLACE TABLE homes AS
WITH ordered AS (
    SELECT *,
           lead(price) OVER w AS prev_price,
           lead(sale_date) OVER w AS prev_date,
           lead(property_type) OVER w AS prev_type,
           count(*) OVER (PARTITION BY home_key) AS times_sold,
           row_number() OVER w AS rn
    FROM sales_valued
    WINDOW w AS (PARTITION BY home_key ORDER BY sale_date DESC, transaction_id)
)
SELECT * EXCLUDE (rn),
       CASE WHEN prev_price IS NOT NULL AND prev_type = property_type
                 AND sale_date - prev_date >= 365
                 AND price::DOUBLE / prev_price BETWEEN 0.3 AND 5
            THEN power(price::DOUBLE / prev_price, 365.25 / (sale_date - prev_date)) - 1
       END AS annual_return
FROM ordered WHERE rn = 1;

-- How each home compares with homes of the same type in the same borough.
CREATE OR REPLACE TABLE borough_type AS
SELECT la_code, property_type, median(est_value) AS borough_median, count(*) AS homes
FROM homes GROUP BY ALL;

CREATE OR REPLACE TABLE homes_scored AS
SELECT h.*,
       h.est_value / bt.borough_median - 1 AS value_gap,
       12 * CASE h.property_type WHEN 'D' THEN r.rent_d WHEN 'S' THEN r.rent_s
                                 WHEN 'T' THEN r.rent_t WHEN 'F' THEN r.rent_f END
          / h.est_value AS gross_yield_type,
       12 * r.rent_all / h.est_value AS gross_yield_all
FROM homes h
JOIN borough_type bt USING (la_code, property_type)
LEFT JOIN rents r USING (la_code);

-- 3. Streets.
CREATE OR REPLACE TABLE streets AS
SELECT
    street_key,
    any_value(street) AS street,
    any_value(outcode) AS outcode,
    mode(la_code) AS la_code,
    count(*) AS homes,
    sum(times_sold) AS sales,
    max(sale_date) AS last_sale,
    avg(easting) AS easting,
    avg(northing) AS northing,
    median(est_value) AS median_value,
    {type_cols}
    avg((property_type = 'F')::INT) AS flat_share,
    avg((tenure = 'L')::INT) AS leasehold_share,
    avg(new_build::INT) AS new_build_share,
    median(annual_return) AS growth,
    count(annual_return) AS growth_pairs,
    median(value_gap) AS value_gap,
    median(coalesce(gross_yield_type, gross_yield_all)) AS gross_yield
FROM homes_scored
-- A price far below the borough level is usually a part-share or discounted sale, not
-- a market price, so it is left out of the street figures (but still listed as a sale).
WHERE value_gap > -0.65
GROUP BY street_key
HAVING count(*) >= {min_homes};
"""

TYPE_COLS = "\n".join(
    f"    count(*) FILTER (property_type = '{t}') AS n_{t.lower()},\n"
    f"    quantile_cont(est_value, 0.25) FILTER (property_type = '{t}') AS p25_{t.lower()},\n"
    f"    median(est_value) FILTER (property_type = '{t}') AS med_{t.lower()},\n"
    f"    quantile_cont(est_value, 0.75) FILTER (property_type = '{t}') AS p75_{t.lower()},"
    for t in config.PROPERTY_TYPES
)


def build_tables(clean_dir: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(
        SQL.format(clean=clean_dir, type_cols=TYPE_COLS, min_homes=config.MIN_HOMES_PER_STREET)
    )
    counts = con.execute(
        "SELECT (SELECT count(*) FROM sales_valued), (SELECT count(*) FROM homes),"
        " (SELECT count(*) FROM streets)"
    ).fetchone()
    log.info("build: %s sales, %s homes, %s streets", *(f"{c:,}" for c in counts))
    return con


def add_surroundings(streets: pd.DataFrame, clean_dir: Path) -> pd.DataFrame:
    """Crime, transport, shops and schools around the middle of each street."""
    pts = streets[["easting", "northing"]].to_numpy()
    out = streets.copy()

    crimes = pd.read_parquet(clean_dir / "crimes.parquet")
    groups = {
        "crime_total": crimes,
        "crime_burglary": crimes[crimes["category"] == "Burglary"],
        "crime_violence": crimes[crimes["category"] == "Violence and sexual offences"],
        "crime_robbery": crimes[crimes["category"] == "Robbery"],
    }
    for col, frame in groups.items():
        out[col] = count_within(pts, frame[["easting", "northing"]].to_numpy(), config.CRIME_RADIUS)

    amen = pd.read_parquet(clean_dir / "amenities.parquet")
    for kind, prefix in (("station", "station"), ("supermarket", "shop")):
        sub = amen[amen["kind"] == kind].reset_index(drop=True)
        xy = sub[["easting", "northing"]].to_numpy()
        dist, idx = nearest(pts, xy)
        out[f"{prefix}_dist"] = dist
        out[f"{prefix}_name"] = sub["name"].to_numpy()[idx]
        out[f"{prefix}_detail"] = sub["detail"].to_numpy()[idx]
        out[f"{prefix}s_1km"] = count_within(pts, xy, 1000)

    schools = pd.read_parquet(clean_dir / "schools.parquet")
    state = schools[~schools["independent"]]
    for level, prefix, radius in (
        ("Primary", "primary", config.PRIMARY_RADIUS),
        ("Secondary", "secondary", config.SECONDARY_RADIUS),
    ):
        sub = state[state["level"] == level].reset_index(drop=True)
        xy = sub[["easting", "northing"]].to_numpy()
        dist, idx = nearest(pts, xy)
        out[f"{prefix}_dist"] = dist
        out[f"{prefix}_name"] = sub["name"].to_numpy()[idx]
        out[f"{prefix}_count"] = count_within(pts, xy, radius)
    indep = schools[schools["independent"]][["easting", "northing"]].to_numpy()
    out["independent_count"] = count_within(pts, indep, config.SECONDARY_RADIUS)
    return out


def percentile(series: pd.Series, higher_is_better: bool = True) -> pd.Series:
    """0 to 100, where 100 is the best street in London. Missing values stay missing."""
    ranked = series.rank(pct=True, ascending=higher_is_better)
    return (ranked * 100).round()


def add_scores(streets: pd.DataFrame) -> pd.DataFrame:
    s = streets.copy()
    s["score_safety"] = percentile(s["crime_total"], higher_is_better=False)
    s["score_transport"] = percentile(s["station_dist"], higher_is_better=False)
    s["score_shops"] = percentile(s["shop_dist"], higher_is_better=False)
    s["score_schools"] = (
        (
            percentile(s["primary_count"])
            + percentile(s["primary_dist"], higher_is_better=False)
            + percentile(s["secondary_count"])
        )
        / 3
    ).round()
    s["score_value"] = percentile(s["value_gap"], higher_is_better=False)
    reliable_growth = s["growth"].where(s["growth_pairs"] >= 3)
    s["score_growth"] = percentile(reliable_growth)
    s["score_yield"] = percentile(s["gross_yield"])
    return s


def title_case(name: str) -> str:
    """'ST JOHN'S WOOD ROAD' -> "St John's Wood Road"."""
    words = []
    for word in str(name).lower().split():
        parts = word.split("-")
        words.append("-".join(p[:1].upper() + p[1:] for p in parts))
    return " ".join(words)


def build(clean_dir: Path) -> dict[str, pd.DataFrame]:
    con = build_tables(clean_dir)
    streets = con.execute("SELECT * FROM streets ORDER BY street_key").df()
    streets["street"] = streets["street"].map(title_case)
    streets["lat"], streets["lon"] = grid_to_latlon(streets["easting"], streets["northing"])
    streets = add_scores(add_surroundings(streets, clean_dir))
    streets.insert(0, "id", np.arange(len(streets)))

    homes = con.execute(
        """
        SELECT h.street_key, h.saon, h.paon, h.postcode, h.outcode, h.property_type,
               h.tenure, h.new_build, h.price, h.sale_date, h.est_value, h.prev_price,
               h.prev_date, h.times_sold, h.lat, h.lon
        FROM homes h JOIN streets USING (street_key)
        """
    ).df()
    homes = homes.merge(streets[["street_key", "id"]], on="street_key").rename(
        columns={"id": "street_id"}
    )
    boroughs = con.execute(
        """
        SELECT b.la_code, b.borough,
               median(h.est_value) AS median_value,
               count(*) AS homes,
               median(h.annual_return) AS growth,
               r.rent_all, r.rent_1b, r.rent_2b, r.rent_3b, r.rent_4b,
               r.rent_d, r.rent_s, r.rent_t, r.rent_f, r.month AS rent_month
        FROM homes h JOIN boroughs b USING (la_code) LEFT JOIN rents r USING (la_code)
        GROUP BY ALL ORDER BY median_value DESC
        """
    ).df()
    meta = con.execute(
        """
        SELECT min(sale_date) AS sales_from, max(sale_date) AS sales_to,
               max(hpi_month) AS hpi_month, count(*) AS sales
        FROM sales_valued
        """
    ).df()
    crimes = pd.read_parquet(clean_dir / "crimes.parquet", columns=["month"])
    meta["crime_from"], meta["crime_to"] = crimes["month"].min(), crimes["month"].max()
    meta["homes"], meta["streets"] = len(homes), len(streets)
    return {"streets": streets, "homes": homes, "boroughs": boroughs, "meta": meta}
