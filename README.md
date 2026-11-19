Spatial variety best bet location mapping

# RTC VarSim

**Research code; v1.0.0 prepared, not yet tagged or published.** RTC VarSim compares environmental data with potato and sweetpotato variety criteria across Africa. The historical local preparation folder is named AFSA-VarScout-private. A source-only clone needs authorized local inputs before it can display research results.

Django research platform for potato and sweetpotato variety criteria across Africa. The main interface is `/demo/`; `/` retains the Rwanda pilot. Results are exploratory criteria checks, not validated crop suitability or yield predictions.

## Project method

- Temperature: CHELSA 1991–2020 monthly means, compared inclusively with catalogue limits for every calendar month touched by the upper-bound crop cycle, starting on day 1 of the planting month. Temperature shows the number of cycle months in range.
- Rainfall: sum of all twelve monthly normals, compared with the annual catalogue range. Cycle rainfall and its annual share are descriptive popup information.
- Soil pH: SoilGrids pH in water at 0–30 cm, thickness-weighted arithmetic mean of the 0–5, 5–15 and 15–30 cm layers (weights 5/30, 10/30 and 15/30).
- Summary: unweighted count of three satisfied criteria (0–3). Every cycle temperature month must be in range for that criterion to pass. Missing inputs make a cell not evaluable, never a failure. Sea and outside-Africa cells are transparent.

The sampled Africa display uses one native cell per 16 × 16 block (roughly 15 km at the equator). Monthly normals do not represent daily extremes. A single planting month is applied across Africa. The separate climate-similarity workflow uses its own coefficients and does not change the variety criteria.

## Install and test

Use Python 3.12 and a local virtual environment. Run the following from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

Core tests use synthetic inputs and temporary directories. Four legacy integration checks explicitly skip when the private local catalogue is absent; HTTP checks also skip if loopback is blocked. Passing software tests is not agronomic validation.

## Django configuration

`SECRET_KEY` reads the `DJANGO_SECRET_KEY` environment variable. If it is unset or empty, the application uses the explicitly marked `INSECURE-DEVELOPMENT-ONLY-DO-NOT-DEPLOY` fallback, only for local development. `DEBUG` is fixed to `False` by default. Hosts are restricted to localhost, 127.0.0.1 and Django's test host. These development settings do not constitute a production deployment configuration.

To supply a private key in the current PowerShell session, assign `$env:DJANGO_SECRET_KEY` locally before starting Django. Do not commit its value. No `.env` loader is installed: setting a value in a `.env` file alone will not load it. `.env` files and private-key files are ignored by Git.

## Internal variety catalogue: required and not distributed

The variety catalogue comes from the internal tolerance workbook supplied for this research (distinct from the RAB 2018 reference), with expert-provided potato and sweetpotato records. It is not supplied by the upstream AFSA repository or by the paper cited below. Obtain the authorized workbook, or the current authorized `catalogue.json`, directly from the project team. This repository contains neither the workbook nor its catalogue records.

Place the authorized, current JSON at **`data/catalogue.json`**, relative to the repository root. To import a compatible source workbook instead:

```powershell
New-Item -ItemType Directory -Force data/source | Out-Null
.\.venv\Scripts\python.exe -m pip install openpyxl
# Place the authorized workbook at data/source/varieties-internal.xlsx first.
.\.venv\Scripts\python.exe import_catalogue.py .\data\source\varieties-internal.xlsx
```

The importer expects the original `Sheet1` layout and column order, including `crop_name`, `variety_name`, `observation_count` and `Name of Expert`; it writes `data/catalogue.json` and preserves source references and a checksum. It is not a general-purpose importer for arbitrary spreadsheets. Prefer the current project JSON when later reviewed catalogue changes must be retained. The importer leaves the rainfall-period metadata unspecified; the active `/demo/` method compares annual rainfall as described above.

**The interactive platform does not work without the internal catalogue and the required `data/` inputs.** Django may start, and synthetic tests can run, but a fresh clone cannot serve the working research map. The legacy Rwanda pilot additionally needs its pilot configuration, harmonized rasters, and `assets/rwanda_layers.json` previews. Never commit or redistribute the internal workbook, generated catalogue, local data, or generated runs, even in a private repository.

## Regenerate the Africa data locally

These are manual preparation commands, not commands run automatically by Django. They download and generate large research datasets under the ignored `data/` directory and generated previews under `assets/`. Run them only in a prepared local data workspace. Existing outputs may be reused or overwritten by the relevant builders; retain any outputs you need before rebuilding. No research data were regenerated as part of preparing this repository.

### 1. Boundaries and CHELSA grid

Obtain the project's geoBoundaries CGAZ ADM0 GeoPackage (`globalADM0` table) from the [geoBoundaries CGAZ release](https://github.com/wmgeolab/geoBoundaries/tree/main/releaseData/CGAZ). Place it at `data/source/geoBoundariesCGAZ_ADM0.gpkg`. To use a different local location, set `AFSA_BOUNDARIES_PATH` to the GeoPackage path; both boundary scripts read this environment variable.

`prepare_africa_extent.py` checks CRS metadata and permits the missing-CRS correction only for the previously verified source checksum. A different release must pass its checks or undergo a separate provenance/CRS review; these commands are not guaranteed to accept arbitrary boundary files.

```powershell
New-Item -ItemType Directory -Force data/source, assets | Out-Null
# Place the required GeoPackage in data/source before continuing.
.\.venv\Scripts\python.exe prepare_africa_extent.py
.\.venv\Scripts\python.exe build_africa_basemap.py
.\.venv\Scripts\python.exe inventory_monthly_climate.py
.\.venv\Scripts\python.exe probe_africa_monthly.py
.\.venv\Scripts\python.exe plan_africa_tiles.py
```

The inventory reads the CHELSA v2.1 global monthly `tas` and `pr` object listing for 1991–2020. The probe records source units, conversion metadata and grid geometry, including `data/probe-tas-1991-01.json`. The tile planner needs that probe and `data/africa-extraction-mask.geojson`.

### 2. CHELSA 1991–2020 monthly normals and display grid

```powershell
# Inspect the queue without starting downloads.
.\.venv\Scripts\python.exe africa_climate_jobs.py
# Process at most two pending jobs in the foreground; repeat to resume.
.\.venv\Scripts\python.exe africa_climate_jobs.py --execute 2
```

Repeat bounded batches until all jobs are complete, or deliberately choose a larger `--execute` count. Do not run multiple workers for the same queue. The processor keeps annual extracts and resumable markers, checks source metadata, and requires at least 20 GiB of free disk before starting a job; the full workflow may need substantially more storage and time. The output normals average each calendar month across thirty years, with temperature in Celsius and precipitation in mm/month.

After every expected job is complete:

```powershell
.\.venv\Scripts\python.exe verify_climate_outputs.py
.\.venv\Scripts\python.exe climate_progress.py
.\.venv\Scripts\python.exe build_climate_catalogue.py
.\.venv\Scripts\python.exe build_demo_climate.py
```

The verifier checks completed outputs but does not by itself prove the queue is complete; check that every layer in `climate_progress.py` has zero pending, running and failed jobs. The display builder requires all tile/month markers and rasters. It derives the current job-directory signature from the tile plan, mask and inventory and writes `data/demo-climate/monthly.npz`. Do not alter these inputs midway through a queue: their content determines its identity. Moving existing data from another machine may also require updating absolute raster paths in local job markers.

### 3. SoilGrids pH at three depths

The downloader uses ISRIC SoilGrids WCS `phh2o` mean layers at their native 250 m resolution. It then area-averages each layer onto the CHELSA grid defined by `data/africa-tiles.json`.

```powershell
foreach ($depth in @('0-5', '5-15', '15-30')) {
    .\.venv\Scripts\python.exe scripts/soilgrids_ph_africa.py download --depth $depth
    if ($LASTEXITCODE -ne 0) { throw "SoilGrids download failed for depth $depth" }
    .\.venv\Scripts\python.exe scripts/soilgrids_ph_africa.py build --depth $depth
    if ($LASTEXITCODE -ne 0) { throw "SoilGrids reprojection failed for depth $depth" }
}
.\.venv\Scripts\python.exe scripts/soilgrids_ph_0_30_diagnostics.py
```

The depth-specific defaults are `data/soil-ph/`, `data/soil-ph-5-15/`, and `data/soil-ph-15-30/`. Keep these defaults when using the final diagnostic builder. It writes `data/soil-ph-0-30-diagnostic/ph_0-30cm_provisional_r<row>-c<col>.tif` and diagnostic reports. The active formula is `(5*pH_0-5 + 10*pH_5-15 + 15*pH_15-30)/30`; all three layers must have valid values. Its weighted hydrogen-ion calculation is a sensitivity diagnostic, not the active map layer.

Service availability and download duration depend on CHELSA and ISRIC. These instructions were checked against the scripts; the full continental regeneration was not rerun during repository preparation. Data rights and provenance must be handled separately from software licensing.

## Start the visible local server

After supplying the catalogue and completing the local data setup, run in your own PowerShell window:

```powershell
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8765 --noreload
```

Open http://127.0.0.1:8765/demo/ . Stop the foreground server with Ctrl+C.

## Upstream source, license and scientific reference

`upstream/similarity.py` and `upstream/utils.py` retain code from [AFSA-Maize-land-suitability-Tanzania](https://github.com/izuku-franck1555/AFSA-Maize-land-suitability-Tanzania), supplied through the WebAFSA source archive. Source-file and archive hashes are recorded in `PROVENANCE.json`. The retained upstream code is licensed under **MIT**, copyright © 2024 Tonle Franck; preserve the complete notice in `upstream/LICENSE`. The proposed root LICENSE uses MIT for the project software as well, subject to rights-holder approval before release. Dataset rights and confidentiality remain separate.

Scientific reference: Tonle, F.B.N., Tonnang, H.E.Z., Ndadji, M.M.Z., Tchendji, M.T., Nzeukou, A., and Niassy, S. (2025). *A novel integrated computational approach for agroecological similarity*. **Environmental Modelling & Software, 191**, 106494. [doi:10.1016/j.envsoft.2025.106494](https://doi.org/10.1016/j.envsoft.2025.106494)

The paper describes AFSA; it does not validate the present variety-criteria workflow. The article's license and the retained software's MIT license are distinct. Additional notices are in `THIRD_PARTY_NOTICES.md`; Leaflet's license is in `assets/leaflet/LICENSE`.

## Public repository and excluded data

The publication destination is the public [CIP Rwanda RTC-VarSim repository](https://github.com/International-Potato-Center-CIP-Rwanda/RTC-VarSim). This source-only release contains **no data/ directory and no exceptions** in .gitignore. It excludes the tolerance catalogue, RAB catalogue/overlay, unpublished trials, source inventories of varieties, validation CSVs, research PDFs (including Mwanga et al. 2009), raster data, environments, credentials and machine-specific paths. The public Rwanda-guide PDF and JSON are also excluded under this policy.

The existing initial commit is retained as the parent of the forthcoming code commit; the supervisor's description is preserved at the top of this README. Publication requires explicit approval of the final file manifest. No force push is used.

## Rwanda reference layer

platform_app/reference_catalogue.py composes an effective catalogue in memory; it never rewrites data/catalogue.json. Reviewed references take precedence only for their documented fields. Environmental ranges remain from the tolerance catalogue when available; qualitative altitude/adaptation descriptions are not converted into numerical climate or soil ranges.

The external public reference is Borus, D. et al. (2025), *Rwanda Potato Variety Description Guide*, CIP, [doi:10.4160/cip.2025.03.001](https://doi.org/10.4160/cip.2025.03.001), CC BY 4.0. The reference contains 19 potato descriptions. Neither its PDF nor its JSON extraction is distributed here. Obtain the guide from the cited source and the reviewed, page-referenced extraction from the project team. For an authorized local installation only, place the extraction at data/reference/rwanda_potato_guide_2025.json; keep all local inputs ignored.

The optional local guide matches reviewed aliases, retains prior values and introduces reference-only varieties with missing environmental ranges. It does not invent those ranges. The variety card displays field sources, approved synonyms and previous values. Synthetic tests exercise this logic without reproducing the catalogue or requiring its source files.

An authorized local data/reference/rab_sweetpotato_2018_internal.json can override documented sweetpotato fields. This internal input is never published. The loader expects source.label and records containing name, crop, cycle_days and resistances. A source-only clone omits both public-reference extraction and internal overlays, so its effective catalogue cannot be assumed to match the configured research installation. Existing result snapshots are not regenerated automatically when references change.

## Source register and reproducibility

| Input | Source and processing used here | Distribution in this repository |
|---|---|---|
| Monthly air temperature and precipitation | [CHELSA-monthly v2.1](https://www.chelsa-climate.org/datasets/chelsa_monthly), `tas` and `pr`, January 1991–December 2020. The scripts enumerate the original [CHELSA object store](https://os.unil.cloud.switch.ch/chelsa02/), validate each raster's scale, offset, units, grid and identity, and calculate each calendar-month mean over all 30 annual inputs. | Rasters, extracts, downloaded bytes and generated normals excluded because of size and local processing state. Rebuild using the commands above and retain source metadata. |
| Soil acidity | [ISRIC SoilGrids](https://isric.org/explore/soilgrids), mean pH in water at 0–5, 5–15 and 15–30 cm; [data access documentation](https://docs.isric.org/globaldata/soilgrids/SoilGrids_faqs_02.html). Native 250 m predictions are converted from pH-times-ten, area-averaged independently onto CHELSA, then combined by thickness. | Local rasters excluded. SoilGrids maps are CC BY 4.0; cite ISRIC and retain the source-depth provenance when redistributing derived data separately. |
| Rwanda potato descriptions | Borus et al. (2025), [Rwanda Potato Variety Description Guide](https://doi.org/10.4160/cip.2025.03.001). An external, reviewed JSON extraction records source pages and discrepancies for local use. | Neither the PDF nor the extraction is included. Obtain the public guide from its DOI and the reviewed extraction from the project team; preserve CC BY 4.0 attribution in any separately authorized redistribution. |
| Boundaries | [geoBoundaries CGAZ](https://www.geoboundaries.org/), CC BY 4.0; see THIRD_PARTY_NOTICES.md. Extraction-mask geometry and simplified display context are separate products. | Source GeoPackage, generated extraction mask and generated basemap excluded; source checksum and CRS checks are part of preparation. |
| Tolerance ranges | Authorized internal tolerance workbook and its imported JSON. The quoted institutional attributions are not independent verification. | Workbook and catalogue excluded for confidentiality; obtain them from the project team. |
| Reviewed internal references and field validation | Optional authorized RAB reference overlay; unpublished trial workbooks and local comparison tables. | Never included in the clean copy or repository. Their absence can change the effective cycle or resistance fields; a source-only clone must not be claimed to reproduce the fully configured research installation. |

For CHELSA methodology cite Karger et al. (2017), *Climatologies at high resolution for the earth's land surface areas*, Scientific Data 4, 170122, [doi:10.1038/sdata.2017.122](https://doi.org/10.1038/sdata.2017.122). The current provider page supplies a newer monthly-data citation, [doi:10.16904/envidat.686](https://doi.org/10.16904/envidat.686); preserve the metadata and rights for the exact v2.1 objects used, rather than assuming that a later product announcement describes an older local archive. The project's **1991–2020 normals are built by these scripts**, not obtained by substituting a different ready-made climatology period.

The public Rwanda JSON is not in this source-only release. There is no general automatic PDF-to-catalogue importer: the external structured extraction was reviewed manually against the guide. To update that local reference, retain page citations and source conflicts, review all records, and verify the associated PDF checksum outside the publication tree. The repository tests validate loader behavior using deliberately fabricated records; they do not certify an external guide transcription. Do not infer environmental ranges from altitude descriptions.

Reproducibility requires the same authorized catalogue and overlays, boundary source, source-object identities, tile plan, scale conversions and application version. Keep the local inventory, marker metadata, manifests and checksums beside the datasets; do not commit private paths or catalogue contents. Result files are snapshots. Rebuilding `monthly.npz`, importing a workbook or rerunning the pH builder is an explicit data-processing operation, never an installation or test prerequisite.

## Script and module directory

These entries describe the supported workflow, not a list of scripts to execute indiscriminately. In particular, `build_africa_basemap.py` and `plan_africa_tiles.py` perform preparation at module level: running or importing them can write generated outputs. Tests isolate their preparation fixtures. Do not import builders just to inspect their functions.

| Script | Role and main local inputs/outputs |
|---|---|
| `manage.py` | Django command entry point; `runserver` serves the local app and does not build climate inputs. |
| `import_catalogue.py` | Read an authorized workbook's fixed Sheet1 layout; validate ranges and identifiers; write `data/catalogue.json` with source checksum. Optional `openpyxl` dependency. |
| `prepare_africa_extent.py` | Read the geoBoundaries GeoPackage; validate CRS provenance; write `data/africa-extraction-mask.geojson` and provenance. |
| `build_africa_basemap.py` | Create simplified geographic context and labels under `assets/` from the boundary GeoPackage. This display basemap is not the extraction mask. |
| `inventory_monthly_climate.py` | Enumerate 1991–2020 CHELSA monthly `tas`/`pr` objects and identities into `data/africa-1991-2020-inventory.json`; no raster download at this step. |
| `probe_africa_monthly.py` | Inspect remote raster metadata through bounded range reads; write local probe records used to define the native grid and conversions. |
| `plan_africa_tiles.py` | Intersect the native grid with the African mask; write `data/africa-tiles.json` for 512-cell processing windows. |
| `extract_climate_tile.py` | Extract one variable/month/window over all 30 years, reuse matching annual caches and write a strict monthly normal plus valid-year counts. Standalone example: `--variable tas --month 1 --lon 30 --lat -2 --size 32`. |
| `africa_climate_jobs.py` | Plan by default; `--execute N` processes bounded resumable tile/month jobs, applies the land mask and records status. Never run duplicate workers on one queue. |
| `climate_progress.py` | Count markers for the current plan signature and write a progress report; completion counts alone are not output verification. |
| `verify_climate_outputs.py` | Inspect completed climate rasters, source metadata and masks and write a verification report. |
| `build_climate_catalogue.py` | Write a preparation index of current-plan markers and raster paths; it does not authorize a ready web dataset by itself. |
| `build_demo_climate.py` | Require every expected completed monthly tile; sample one native pixel per display block and write `data/demo-climate/monthly.npz`. |
| `bench_range_reader.py` | Benchmark HTTP range access on synthetic data; `--remote` explicitly uses actual remote inputs. Diagnostic only, not necessary to start Django. |
| `run_climate_background.py` | Optional Windows climate-processing supervisor with lock, log and STOP sentinel under `data/background/`; it launches a climate worker, not Django. Not needed for the documented foreground workflow and not run by release checks. Its completion target is currently fixed at 4,848 jobs: review that assumption before using it with a changed tile plan. |
| `scripts/soilgrids_ph_africa.py` | `download`, `build` or optional `compare-rwanda`, with `--depth`; resumable native WCS tiles, depth-specific CHELSA tiles and diagnostics. The Rwanda comparison additionally needs its local pilot pH raster. |
| `scripts/soilgrids_ph_0_30_diagnostics.py` | Combine all three existing depth layers into the active 0–30 cm pH tiles; additionally report a hydrogen-ion sensitivity comparison. Historical filenames contain `provisional`; this is not a change to the confirmed active 0–30 cm method. |
| `harmonize_layers.py` | Legacy Rwanda-pilot preparation: write aligned raster copies and a manifest from separately supplied pilot source layers. Not an Africa regeneration prerequisite. |
| `build_map_layers.py` | Legacy pilot: generate preview PNGs and `assets/rwanda_layers.json` from aligned pilot rasters and `data/pilot.json`. |
| `sync_to_clean_copy.ps1` | Copy only its reviewed allowlist from a separate original project; preserve README, ignore rules and adapted tests; report unlisted files; run tests, sensitive-information checks and Git diff summaries. No commit, push or server. |

| Python module | Responsibility |
|---|---|
| `climate_access.py` | Validated bounded HTTP range reads, connection reuse, transport counters and transient retry rules. |
| `climate_block_cache.py` | Checksummed persistent byte-block cache keyed by source identity and position, with bounded eviction. |
| `climate_normals.py` | Strict 30-year monthly accumulation; reject duplicate/incomplete annual inputs and retain nodata. |
| `platform_app/africa_demo.py` | Africa data loading, reference sampling, criteria/summary endpoints, result writing and clicked-cell inspection. |
| `platform_app/reference_catalogue.py` | Compose tolerance and reviewed public/internal references in memory, with field sources and previous values. |
| `platform_app/variety_screen.py` | Cycle-month selection, temperature fractions, annual rainfall check, three-criterion combination and equivalent-profile matching. |
| `platform_app/soil_ph.py` | Thickness-weighted 0–30 cm pH calculation requiring all three source layers. |
| `platform_app/monthly.py` | Separate selected-month climate-similarity calculation and month-interval expansion. |
| `platform_app/engine.py` | Static raster similarity used by the legacy Rwanda pilot; no seasonal rotation in this local engine. |
| `platform_app/computation.py` | Validate and execute a pilot computation and save its outputs/provenance. |
| `platform_app/setup.py` | Validate portable pilot analysis drafts against the local configuration and catalogue. |
| `platform_app/result_tools.py` | Result filtering and preview rendering, with explicit nodata and land/outside distinctions. |
| `platform_app/views.py` | Legacy pilot form/API handling, configuration, draft export and result inspection. |
| `platform_app/settings.py`, `urls.py`, `__init__.py` | Local configuration, request routes and Django application package. |
| `upstream/similarity.py`, `upstream/utils.py` | Retained AFSA implementation for provenance and algorithm comparison; original `afsa` package dependencies are not all bundled. These are not standalone commands to run for this Django app. |

The two original browser scripts are `assets/africa-demo.js` (Africa criteria, legends, variety cards and reference comparison) and `assets/app.js` (pilot form, setup drafts and result inspection). Their CSS lives beside them. `assets/leaflet/` is vendored Leaflet and retains its own license; generated previews do not belong in Git.

Tests are grouped by responsibility: `test_africa_jobs.py` (mask policy); `test_climate_cache.py`, `test_climate_network.py`, `range_server.py` (synthetic transport, bounded reads and cache failures); `test_climate_normals.py` (strict normals); `test_supervisor_stop.py` (isolated stop/recovery); `test_harmonization.py` (grid/resampling); `test_engine.py`, `test_computation.py`, `test_setup.py`, `test_monthly.py`, `test_result_tools.py` (calculation and API rules); `test_variety_screen.py`, `test_temperature_tab.py` (criteria, missing data and display dataset signature); `test_reference_catalogue.py`, `test_demo_retouches.py`, `test_ui_proposal.py` (reference precedence, field provenance and interface text). Synthetic transport tests may briefly start and stop their own ephemeral HTTP fixtures; they do not run the application server on port 8765.

## Updating the clean copy

Run this from the clean repository, substituting your local original-project and Python locations:

```powershell
.\sync_to_clean_copy.ps1 -SourcePath 'D:\research\AFSA-VarScout' -PythonPath 'D:\research\environment\Scripts\python.exe'
```

Review every reported new file before extending the allowlist. No file may be copied under data/; synchronization refuses a clean copy containing that directory. The script reports technical occurrences of `password`, `token` and `key`; an identifier such as a cache key is not automatically a credential. Actual addresses, personal paths, recognizable credentials and suspicious literal assignments are blocking alerts.

The new LICENSE, CHANGELOG and release documents belong to the clean copy. The current sync does not overwrite them, because they are not source allowlist entries. Documentation-only edits inside copied Python/JavaScript files **can be overwritten by a later sync**; review those diffs and reapply the reviewed documentation before the next release. Do not synchronize again after finalizing the release manifest without regenerating that manifest. No documentation changes made for this preparation have been applied back to the original research project.

## Limits and interpretation

This release implements descriptive range checks, not a calibrated yield model. Monthly means conceal daily extremes; annual rain conceals dry spells and seasonal distribution. The sampled display does not resolve individual fields, and published station coordinates do not establish the exact historical trial plot. The pH layer is a prediction and an arithmetic thickness-weighted aggregation, not a laboratory measurement. No uncertainty weighting, altitude adjustment or missing-data imputation is applied.

Tolerance ranges are not independently verified. Reviewed official references supersede only the fields they actually document; a public variety description does not supply missing numerical environmental ranges. Disease and insect resistance, yield descriptions and unpublished field observations are not additional Summary criteria. Small descriptive station comparisons are not statistical validation. The separate AFSA-inspired similarity preview is not a variety suitability score, and the retained code does not mean all methods in Tonle et al. are implemented or validated here.

## Proposed software license and v1.0.0

MIT is proposed for the RTC VarSim software because it preserves the permissions and notice obligations of the retained MIT upstream code. See [LICENSE](LICENSE), the unchanged [upstream license](upstream/LICENSE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). The collective copyright label must be confirmed by the actual rights holders before publication. This proposal grants no rights to internal research data, institutional names/logos or separately licensed datasets. The external public guide remains CC BY 4.0; it is not bundled. Leaflet remains BSD-2-Clause.

See [CHANGELOG.md](CHANGELOG.md) for the prepared changes, [RELEASE.md](RELEASE.md) for the pending initial-commit and annotated-tag procedure, and [RELEASE_MANIFEST.txt](RELEASE_MANIFEST.txt) for the exact prepared file list and checksums. The public destination is confirmed and its existing history has been fetched locally. Upload approval is still pending: no code commit, tag or release has been sent. The annotated tag must identify the reviewed code commit, after approval.
