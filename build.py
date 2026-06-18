#!/usr/bin/env python3
"""CLI entry point: build and export the fused African ethnographic dataset.

Examples:
    python build.py                              # default open sources -> ./out
    python build.py --out data --fmt gpkg
    python build.py --sources murdock_map greg geoepr
    python build.py --no-african-only            # keep the whole world
    python build.py --jp-api-key $JP_KEY --sources murdock_map glottolog joshua_project
"""
import argparse

from africa_ethno_fusion import DEFAULT_SOURCES, build, export


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sources", nargs="+", default=DEFAULT_SOURCES,
                   help=f"sources to fuse (default: {DEFAULT_SOURCES})")
    p.add_argument("--out", default="out", help="output directory (default: out)")
    p.add_argument("--fmt", default="all", choices=["all", "parquet", "gpkg", "csv"])
    p.add_argument("--no-african-only", dest="african_only", action="store_false",
                   help="keep all continents (default: Africa only)")
    p.add_argument("--no-fuzzy", dest="fuzzy", action="store_false",
                   help="skip fuzzy name crosswalk between polygon datasets")
    p.add_argument("--jp-api-key", default=None, help="Joshua Project API key (free)")
    p.add_argument("--jp-csv", default=None, help="local Joshua Project CSV instead of the API")
    args = p.parse_args()

    print(f"Building fused dataset from: {', '.join(args.sources)}")
    frames = build(
        args.sources,
        african_only=args.african_only,
        fuzzy_crosswalk=args.fuzzy,
        jp_api_key=args.jp_api_key,
        jp_csv=args.jp_csv,
    )
    export(frames, args.out, fmt=args.fmt)


if __name__ == "__main__":
    main()
