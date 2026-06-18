"""africa_ethno_fusion -- fuse African ethnographic datasets into one star schema.

Quick start:
    from africa_ethno_fusion import build, export
    frames = build()                 # open sources, Africa only
    export(frames, "out", fmt="all") # GeoParquet + GeoPackage + CSV
"""
from .fuse import DEFAULT_SOURCES, build, export
from .schema import GROUP_COLUMNS, LINK_COLUMNS, SOURCES, TRAIT_COLUMNS

__all__ = [
    "build",
    "export",
    "DEFAULT_SOURCES",
    "SOURCES",
    "GROUP_COLUMNS",
    "TRAIT_COLUMNS",
    "LINK_COLUMNS",
]
__version__ = "0.1.0"
