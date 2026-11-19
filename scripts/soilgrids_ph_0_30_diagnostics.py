"""Build the provisional 0-30 cm SoilGrids pH layer and diagnostics.

The thickness-weighted arithmetic pH is the active application layer; this
script also records a weighted-H+ sensitivity comparison.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio import Affine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from platform_app.soil_ph import thickness_weighted_ph

DATA = ROOT / "data"
PLAN = json.loads((DATA / "africa-tiles.json").read_text(encoding="utf-8"))
LAYERS = {
    "0-5": DATA / "soil-ph" / "chelsa-tiles",
    "5-15": DATA / "soil-ph-5-15" / "chelsa-tiles",
    "15-30": DATA / "soil-ph-15-30" / "chelsa-tiles",
}
OUT = DATA / "soil-ph-0-30-diagnostic"
OUT.mkdir(parents=True, exist_ok=True)
NODATA = -9999.0


def tile_file(layer: str, row: int, col: int) -> Path:
    """Locate one depth-specific SoilGrids tile on the common CHELSA grid."""
    return LAYERS[layer] / f"ph_{layer}cm_mean_r{row}-c{col}.tif"


def main() -> None:
    """Build the thickness-weighted 0-30 cm pH tiles and record the hydrogen-ion sensitivity diagnostic; all three depths must be available."""
    composite_values: list[np.ndarray] = []
    differences: list[np.ndarray] = []
    hydrogen_differences: list[np.ndarray] = []
    changed = 0
    common = 0
    valid_comp_cells = 0
    layer_valid_counts = {layer: 0 for layer in LAYERS}
    missing_tile_counts = {layer: 0 for layer in LAYERS}
    total_land_cells = 0

    for index, tile in enumerate(PLAN["tiles"]):
        row, col = tile["row"], tile["col"]
        total_land_cells += int(tile.get("land_cells", 0))
        arrays = {}
        profile = None
        for layer in LAYERS:
            path = tile_file(layer, row, col)
            if not path.exists():
                missing_tile_counts[layer] += 1
                arrays[layer] = None
                continue
            with rasterio.open(path) as src:
                if profile is None:
                    profile = src.profile.copy()
                elif (src.shape != (profile["height"], profile["width"]) or src.transform != profile["transform"] or src.crs != profile["crs"]):
                    raise RuntimeError(f"Grid mismatch in {path}")
                a = src.read(1)
                arrays[layer] = np.where(np.isfinite(a) & (a != src.nodata) & (a >= 1.0) & (a <= 14.0), a, np.nan).astype("float32")
            layer_valid_counts[layer] += int(np.count_nonzero(np.isfinite(arrays[layer])))

        if profile is None:
            continue
        a0, a5, a15 = arrays["0-5"], arrays["5-15"], arrays["15-30"]
        common_mask = np.isfinite(a0) & np.isfinite(a5) & np.isfinite(a15) if a0 is not None and a5 is not None and a15 is not None else np.zeros((profile["height"], profile["width"]), dtype=bool)
        out = np.full(common_mask.shape, NODATA, dtype="float32")
        if np.any(common_mask):
            # Requested provisional thickness-weighted formula: 5, 10, and 15 cm.
            composite_grid = thickness_weighted_ph(a0, a5, a15)
            composite = composite_grid[common_mask]
            hydrogen_mean = -np.log10((5 * np.power(10.0, -a0[common_mask]) +
                                       10 * np.power(10.0, -a5[common_mask]) +
                                       15 * np.power(10.0, -a15[common_mask])) / 30)
            out[common_mask] = composite
            composite_values.append(composite.astype("float32", copy=False))
            diffs = np.abs(composite - a0[common_mask])
            differences.append(diffs.astype("float32", copy=False))
            hydrogen_differences.append(np.abs(composite - hydrogen_mean).astype("float32", copy=False))
            old_in_range = (a0[common_mask] >= 5.5) & (a0[common_mask] <= 7.0)
            new_in_range = (composite >= 5.5) & (composite <= 7.0)
            changed += int(np.count_nonzero(old_in_range != new_in_range))
            common += int(np.count_nonzero(common_mask))
            valid_comp_cells += int(np.count_nonzero(common_mask))

        prof = profile.copy()
        prof.update(dtype="float32", count=1, nodata=NODATA, compress="deflate", predictor=3)
        name = f"ph_0-30cm_provisional_r{row}-c{col}.tif"
        with rasterio.open(OUT / name, "w", **prof) as dst:
            dst.write(out, 1)
            dst.update_tags(source="SoilGrids pH water, 0-5/5-15/15-30 cm", depth="0-30 cm provisional",
                            formula="(5*pH_0-5 + 10*pH_5-15 + 15*pH_15-30)/30",
                            nodata_policy="evaluable only where all three source layers are valid",
                            resampling="source layers independently area-averaged to CHELSA grid")
        print(f"[{index+1}/{len(PLAN['tiles'])}] {name}: common valid={int(np.count_nonzero(common_mask))}", flush=True)

    vals = np.concatenate(composite_values) if composite_values else np.array([], dtype="float32")
    diffs = np.concatenate(differences) if differences else np.array([], dtype="float32")
    h_diffs = np.concatenate(hydrogen_differences) if hydrogen_differences else np.array([], dtype="float32")
    percentiles = {str(p): float(np.percentile(vals, p)) for p in (0.1, 1, 50, 99, 99.9)} if vals.size else {}
    result = {
        "status": "integrated_as_application_default",
        "formula": "(5*pH_0-5 + 10*pH_5-15 + 15*pH_15-30)/30",
        "formula_caveat": "Provisional thickness-weighted arithmetic mean of pH. Because pH is logarithmic, a weighted-H+ alternative is also calculated and reported for sensitivity.",
        "tile_count": len(PLAN["tiles"]),
        "missing_tile_counts": missing_tile_counts,
        "valid_cell_counts_by_layer": layer_valid_counts,
        "valid_cells_all_three_layers": int(valid_comp_cells),
        "full_tile_grid_cells": int(sum(int(t["height"]) * int(t["width"]) for t in PLAN["tiles"])),
        "minimum": float(vals.min()) if vals.size else None,
        "maximum": float(vals.max()) if vals.size else None,
        "percentiles_0_1_50_99_99_9": percentiles,
        "comparison_0_30_vs_0_5_common_cells": {
            "cell_count": int(common),
            "mean_absolute_difference_pH": float(diffs.mean()) if diffs.size else None,
            "p95_absolute_difference_pH": float(np.percentile(diffs, 95)) if diffs.size else None,
            "kabode_range": [5.5, 7.0],
            "cells_changing_in_range_class": int(changed),
            "share_of_full_valid_composite_grid_pct": 100 * changed / valid_comp_cells if valid_comp_cells else None,
        },
        "arithmetic_pH_vs_weighted_Hplus_method": {
            "alternative_formula": "-log10((5*10^-pH_0-5 + 10*10^-pH_5-15 + 15*10^-pH_15-30)/30)",
            "cell_count": int(h_diffs.size),
            "mean_absolute_difference_pH": float(h_diffs.mean()) if h_diffs.size else None,
            "p95_absolute_difference_pH": float(np.percentile(h_diffs, 95)) if h_diffs.size else None,
        },
        "output_directory": str(OUT),
    }
    (OUT / "diagnostics.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    lines = ["# SoilGrids pH 0–30 cm — integration diagnostics", "",
             "The provisional thickness-weighted arithmetic pH layer is now the application default. The original 0–5 cm source remains on disk and is not used by the application.", "",
             f"- Candidate grid cells valid in all three layers: {valid_comp_cells:,}",
             f"- Full tile grid size: {result['full_tile_grid_cells']:,} cells",
             f"- pH range: {result['minimum']:.3f}–{result['maximum']:.3f}" if vals.size else "- pH range: unavailable",
             f"- Percentiles (0.1/1/50/99/99.9): {', '.join(f'{percentiles[str(p)]:.3f}' for p in (0.1,1,50,99,99.9))}" if percentiles else "- Percentiles: unavailable",
             f"- Common cells vs 0–5 cm: {common:,}",
             f"- Mean absolute difference vs 0–5 cm: {result['comparison_0_30_vs_0_5_common_cells']['mean_absolute_difference_pH']:.4f} pH" if diffs.size else "- Mean absolute difference: unavailable",
             f"- 95th percentile absolute difference: {result['comparison_0_30_vs_0_5_common_cells']['p95_absolute_difference_pH']:.4f} pH" if diffs.size else "- 95th percentile absolute difference: unavailable",
             f"- Kabode 5.5–7.0 class changes: {changed:,}",
             f"- Class changes as a share of the full valid composite grid: {result['comparison_0_30_vs_0_5_common_cells']['share_of_full_valid_composite_grid_pct']:.3f}%" if valid_comp_cells else "- Class-change share: unavailable",
             f"- Arithmetic pH vs weighted H⁺ method: mean absolute difference {result['arithmetic_pH_vs_weighted_Hplus_method']['mean_absolute_difference_pH']:.5f}; 95th percentile {result['arithmetic_pH_vs_weighted_Hplus_method']['p95_absolute_difference_pH']:.5f} pH" if h_diffs.size else "- H⁺ alternative comparison: unavailable",
             "- Missing-data rule: composite is nodata unless all 0–5, 5–15 and 15–30 cm inputs are valid.",
             "- Method choice: thickness-weighted arithmetic mean of pH is retained; the weighted-H⁺ calculation is provided as a sensitivity comparison.", ""]
    (OUT / "audit-summary.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
