# Contributing

Contributions, issues, and dataset suggestions are welcome.

## Reporting issues / asking questions
Open a GitHub issue at https://github.com/marvinmouroum/africa-ethno-fusion/issues
with: what you ran, what you expected, and what happened (paste the console output).
For a data question, say which `--sources` and which group/region.

## Development setup
```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
pip install pytest
pytest                      # offline unit tests (no network/data download)
python build.py             # rebuild the fused dataset from source
python view.py docs/index.html   # rebuild the map
```

## Pull requests
- Keep the runtime **pure Python** and the license **MIT-compatible** (no GPL deps).
- Add a new source by writing a `load_<name>()` in `africa_ethno_fusion/sources.py`
  that returns a canonical `GROUP_COLUMNS` GeoDataFrame, register it in
  `fuse.py`'s dispatch and in `schema.SOURCES`, and document it in `PROVENANCE.md`.
- Run `pytest` and `python -m py_compile africa_ethno_fusion/*.py` before opening a PR.
- Be transparent about data provenance and licensing for any new source.

## Code of conduct
Be respectful and constructive. This project touches sensitive ethnographic data —
discuss its limitations honestly and avoid essentialising claims about groups.
