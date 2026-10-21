"""`propfinder fetch | build | sample`.

fetch   download every source and write clean tables to data/clean
build   turn the clean tables into the website in site/
sample  write synthetic clean tables, to work on the app without downloading anything
"""

from __future__ import annotations

import argparse
import logging
import sys

from propfinder import config

SOURCES = ("prices", "postcodes", "hpi", "rents", "crime", "schools", "osm")


def fetch(names: list[str]) -> None:
    from propfinder.sources import crime, hpi, osm, postcodes, prices, rents, schools

    raw, clean = config.RAW_DIR, config.CLEAN_DIR
    steps = {
        "prices": lambda: prices.clean(prices.fetch(raw), clean),
        "postcodes": lambda: postcodes.clean(postcodes.fetch(raw), clean),
        "hpi": lambda: hpi.clean(hpi.fetch(raw), clean),
        "rents": lambda: rents.clean(rents.fetch(raw), clean),
        "crime": lambda: crime.clean(crime.fetch(raw), clean),
        "schools": lambda: schools.clean(schools.fetch(raw), clean),
        "osm": lambda: osm.clean(osm.fetch(raw), clean),
    }
    for name in names:
        logging.info("fetching %s", name)
        steps[name]()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="propfinder", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("fetch", help="download the sources")
    f.add_argument("sources", nargs="*", help=f"any of: {', '.join(SOURCES)} (default: all)")
    sub.add_parser("build", help="build the website from the clean tables")
    sub.add_parser("sample", help="write synthetic clean tables")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.command == "fetch":
        unknown = set(args.sources) - set(SOURCES)
        if unknown:
            parser.error(f"unknown source(s): {', '.join(sorted(unknown))}")
        fetch(args.sources or list(SOURCES))
    elif args.command == "build":
        from propfinder.build import build
        from propfinder.export import export

        export(build(config.CLEAN_DIR), config.WEB_DIR, config.SITE_DIR)
    elif args.command == "sample":
        from propfinder.sample import write_sample

        write_sample(config.CLEAN_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
