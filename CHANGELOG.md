# RTC VarSim — Changelog

## Unreleased

- Correct the published release status and remove the local preparation-folder reference from documentation. The v1.0.0 tag remains unchanged.

## v1.0.0 — 2026-11-19

- Africa-wide potato and sweetpotato exploratory criteria: cycle temperatures, annual rainfall, thickness-weighted SoilGrids pH 0–30 cm, and unweighted Summary (0–3).
- Separate temperature month-count, rainfall and pH legends; explicit non-evaluable land cells and clicked-cell environmental details.
- Support for an external reviewed Rwanda potato reference layer, field-level sources, previous values, approved synonyms and reference-only entries without invented climate ranges; reference files are not bundled.
- Resumable CHELSA 1991–2020 preparation and bounded transport/cache validation; foreground server instructions and protected clean-copy synchronization.
- Complete installation, source, regeneration, script and limitation documentation; module/function docstrings and interface comments without executable changes.
- Proposed MIT software license with retained upstream/Leaflet notices and citation of the separately licensed, unbundled Rwanda guide.

All data/ contents (including public guide files), private catalogues, internal RAB references, unpublished trials, validation tables, raster datasets, environments, secrets and generated runs are not part of this release. A fresh clone requires authorized local inputs for operational maps.

- Public distribution preserves the existing initial commit and README description, excludes every data/ path, and uses fabricated reference fixtures in tests.
