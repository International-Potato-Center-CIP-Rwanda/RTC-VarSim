"""Resumable SoilGrids pH depth-layer download and CHELSA-grid reprojection.

All WCS requests are made in the native SoilGrids Interrupted Goode Homolosine
projection at the source 250 m resolution. Reprojection is local and uses the
area-average resampler. Outputs stay under data/soil-ph/ until validated.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import rasterio
from rasterio import Affine
from rasterio.crs import CRS
from rasterio.warp import reproject, Resampling, transform_bounds

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = DATA / "soil-ph"
NATIVE = OUT / "native-250m"
CHELSA = OUT / "chelsa-tiles"
PLAN_PATH = DATA / "africa-tiles.json"
DEPTHS = {
    "0-5": ("phh2o_0-5cm_mean", "0-5cm"),
    "5-15": ("phh2o_5-15cm_mean", "5-15cm"),
    "15-30": ("phh2o_15-30cm_mean", "15-30cm"),
}
DEPTH = "0-5"
COVERAGE, DEPTH_LABEL = DEPTHS[DEPTH]
WCS = "https://maps.isric.org/mapserv"
WCS_MAP = "/map/phh2o.map"
NATIVE_CRS_ID = "http://www.opengis.net/def/crs/EPSG/0/152160"
NATIVE_CRS = CRS.from_string("+proj=igh +datum=WGS84 +units=m +no_defs +type=crs")
DEST_NODATA = -9999.0


def configure_depth(depth, output_root=None):
    """Select the SoilGrids depth, coverage identifier and default local directories for this preparation run."""
    global DEPTH, DEPTH_LABEL, COVERAGE, OUT, NATIVE, CHELSA
    DEPTH = depth
    COVERAGE, DEPTH_LABEL = DEPTHS[depth]
    OUT = Path(output_root) if output_root else (DATA / "soil-ph" if depth == "0-5" else DATA / f"soil-ph-{depth}")
    NATIVE = OUT / "native-250m"
    CHELSA = OUT / "chelsa-tiles"


def load_plan():
    """Read the existing Africa tile plan and reject unsupported CRS or an empty tile list."""
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    if plan.get("crs") != "EPSG:4326":
        raise RuntimeError("Expected the CHELSA grid to use EPSG:4326.")
    if not plan.get("tiles"):
        raise RuntimeError("The Africa tile plan is empty.")
    return plan


def grid_transform(plan):
    """Return the affine transform recorded in the CHELSA tile plan."""
    return Affine(*plan["transform"][:6])


def tile_projected_bounds(tile):
    """Transform the tile footprint into SoilGrids native projection bounds for the WCS request."""
    west, south, east, north = tile["bounds"]
    b = transform_bounds("EPSG:4326", NATIVE_CRS, west, south, east, north, densify_pts=41)
    if not all(math.isfinite(v) for v in b) or b[2] <= b[0] or b[3] <= b[1]:
        raise RuntimeError(f"Invalid native projected bounds for tile {tile['row']}-{tile['col']}.")
    # Avoid accidental giant requests caused by a projection seam or malformed bounds.
    if b[2] - b[0] > 1_000_000 or b[3] - b[1] > 1_000_000:
        raise RuntimeError(f"Projected tile extent is unexpectedly large: {b}.")
    return tuple(float(v) for v in b)


def tile_name(index, tile):
    """Build the stable local name for a native SoilGrids download tile."""
    return f"{index:03d}_r{tile['row']}-c{tile['col']}.tif"


def request_url(bounds):
    """Build the WCS request for the selected pH depth and projected bounds."""
    minx, miny, maxx, maxy = bounds
    params = [
        ("map", WCS_MAP), ("SERVICE", "WCS"), ("VERSION", "2.0.1"),
        ("REQUEST", "GetCoverage"), ("COVERAGEID", COVERAGE),
        ("FORMAT", "GEOTIFF_INT16"),
        ("SUBSET", f"X({minx:.6f},{maxx:.6f})"),
        ("SUBSET", f"Y({miny:.6f},{maxy:.6f})"),
        ("SUBSETTINGCRS", NATIVE_CRS_ID), ("OUTPUTCRS", NATIVE_CRS_ID),
    ]
    return WCS + "?" + urllib.parse.urlencode(params)


def sha256_file(path):
    """Stream a file checksum for download provenance and cache validation."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_native(path, expected_bounds=None):
    """Check the downloaded SoilGrids raster type, CRS, dimensions and optional expected footprint before reuse."""
    if not path.is_file() or path.stat().st_size < 512:
        raise RuntimeError("File is missing or too small to be a GeoTIFF.")
    with rasterio.open(path) as src:
        if src.count != 1 or src.dtypes[0] != "int16" or src.width < 1 or src.height < 1:
            raise RuntimeError("Unexpected SoilGrids raster shape or data type.")
        if "interrupted_goode_homolosine" not in src.crs.to_wkt().lower():
            raise RuntimeError("WCS output is not in native Interrupted Goode Homolosine.")
        if not (245 <= abs(src.res[0]) <= 255 and 245 <= abs(src.res[1]) <= 255):
            raise RuntimeError(f"Expected native 250 m pixels; received {src.res}.")
        if expected_bounds:
            tolerance = 275.0
            if any(abs(a - b) > tolerance for a, b in zip(src.bounds, expected_bounds)):
                raise RuntimeError(f"Returned WCS extent differs from the requested native extent: {src.bounds} vs {expected_bounds}.")
        # Force a real read so a broken TIFF is never marked complete.
        src.read(1, window=((0, min(src.height, 8)), (0, min(src.width, 8))))
        return {"width": src.width, "height": src.height, "bounds": list(src.bounds), "resolution": list(src.res), "dtype": src.dtypes[0], "nodata": src.nodata}


def read_manifest(path):
    """Read an existing depth-specific download manifest and reject a mismatched coverage or tile plan."""
    if not path.exists():
        return {"format_version": 1, "coverage": COVERAGE, "depth": DEPTH_LABEL, "source_resolution_m": 250, "native_crs": NATIVE_CRS_ID, "plan_sha256": sha256_file(PLAN_PATH), "completed": {}}
    obj = json.loads(path.read_text(encoding="utf-8"))
    if obj.get("coverage") != COVERAGE or obj.get("plan_sha256") != sha256_file(PLAN_PATH):
        raise RuntimeError("SoilGrids manifest does not match this coverage or Africa tile plan.")
    return obj


def write_manifest(path, obj):
    """Write the current download manifest through a temporary file and replace it atomically."""
    temp = path.with_suffix(path.suffix + ".part")
    temp.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    os.replace(temp, path)


def open_url_stream(url, destination, timeout=300):
    """Stream a WCS response to the local destination with the configured timeout."""
    req = urllib.request.Request(url, headers={"User-Agent": "RTC-VarSim/1.0 (SoilGrids regional extraction)"})
    digest = hashlib.sha256()
    total = 0
    with urllib.request.urlopen(req, timeout=timeout) as response, destination.open("wb") as f:
        status = getattr(response, "status", 200)
        if status != 200:
            raise RuntimeError(f"WCS returned HTTP {status}.")
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > 150_000_000:
                raise RuntimeError("A tile response exceeded the 150 MB safety limit.")
            digest.update(chunk)
            f.write(chunk)
    return total, digest.hexdigest()


def download(args):
    """Download or resume the selected depth tiles with bounded retries, validating each native raster and updating its manifest."""
    OUT.mkdir(parents=True, exist_ok=True)
    NATIVE.mkdir(parents=True, exist_ok=True)
    manifest_path = OUT / "download-manifest.json"
    manifest = read_manifest(manifest_path)
    plan = load_plan()
    indices = list(range(len(plan["tiles"])))
    if args.start_index:
        indices = [i for i in indices if i >= args.start_index]
    if args.limit:
        indices = indices[:args.limit]
    print(f"SoilGrids {COVERAGE}, native 250 m; {len(indices)} tile requests in this run.", flush=True)
    for i in indices:
        tile = plan["tiles"][i]
        name = tile_name(i, tile)
        dest = NATIVE / name
        part = dest.with_suffix(dest.suffix + ".part")
        bounds = tile_projected_bounds(tile)
        key = str(i)
        old = manifest["completed"].get(key)
        if old and dest.is_file() and dest.stat().st_size == old.get("bytes") and sha256_file(dest) == old.get("sha256"):
            try:
                validate_native(dest, bounds)
                print(f"[{i+1}/{len(plan['tiles'])}] already verified: {name}", flush=True)
                continue
            except Exception as exc:
                print(f"[{i+1}/{len(plan['tiles'])}] cached tile failed validation; retrying: {exc}", flush=True)
        if part.exists():
            part.unlink()
        url = request_url(bounds)
        last_error = None
        for attempt in range(1, args.retries + 1):
            started = time.monotonic()
            try:
                nbytes, digest = open_url_stream(url, part)
                geometry = validate_native(part, bounds)
                os.replace(part, dest)
                manifest["completed"][key] = {
                    "file": name, "bytes": nbytes, "sha256": digest,
                    "tile_row": tile["row"], "tile_col": tile["col"],
                    "requested_native_bounds": list(bounds), "raster": geometry,
                }
                write_manifest(manifest_path, manifest)
                elapsed = time.monotonic() - started
                print(f"[{i+1}/{len(plan['tiles'])}] saved {name} ({nbytes/1e6:.1f} MB, {elapsed:.1f}s)", flush=True)
                last_error = None
                break
            except Exception as exc:
                last_error = exc
                if part.exists():
                    part.unlink()
                delay = min(90, 2 ** min(attempt, 6))
                print(f"[{i+1}/{len(plan['tiles'])}] attempt {attempt}/{args.retries} failed: {exc}; retry in {delay}s", flush=True)
                if attempt < args.retries:
                    time.sleep(delay)
        if last_error is not None:
            raise RuntimeError(f"Tile {i} failed after {args.retries} attempts; completed tiles remain resumable.") from last_error
    complete = len(manifest["completed"])
    manifest["download_complete"] = complete == len(plan["tiles"])
    manifest["verified_tile_count"] = complete
    write_manifest(manifest_path, manifest)
    print(f"Verified {complete}/{len(plan['tiles'])} native tiles.", flush=True)


def source_physical_array(src):
    """Convert SoilGrids pH-times-ten values to physical pH, masking nodata, zero and invalid values."""
    raw = src.read(1, masked=True).filled(-32768).astype("int16", copy=False)
    # SoilGrids pH is stored as pH x 10. Zero and out-of-range codes are not soil pH.
    valid = (raw >= 10) & (raw <= 140)
    values = np.full(raw.shape, np.nan, dtype="float32")
    values[valid] = raw[valid].astype("float32") / 10.0
    return values


def reproject_one(source_path, destination_path, tile, plan):
    """Area-average one native pH tile onto its exact CHELSA target grid and write the depth-specific raster."""
    target = np.full((tile["height"], tile["width"]), DEST_NODATA, dtype="float32")
    global_transform = grid_transform(plan)
    dst_transform = global_transform * Affine.translation(tile["col"], tile["row"])
    with rasterio.open(source_path) as src:
        values = source_physical_array(src)
        reproject(
            values, target,
            src_transform=src.transform, src_crs=src.crs, src_nodata=np.nan,
            dst_transform=dst_transform, dst_crs="EPSG:4326", dst_nodata=DEST_NODATA,
            resampling=Resampling.average, init_dest_nodata=True,
        )
    profile = {
        "driver": "GTiff", "height": tile["height"], "width": tile["width"], "count": 1,
        "dtype": "float32", "crs": "EPSG:4326", "transform": dst_transform,
        "nodata": DEST_NODATA, "compress": "deflate", "predictor": 3,
    }
    temp = destination_path.with_suffix(destination_path.suffix + ".part")
    with rasterio.open(temp, "w", **profile) as dst:
        dst.write(target, 1)
        dst.update_tags(source=f"SoilGrids {COVERAGE}", depth=DEPTH_LABEL, native_resolution="250 m",
                        source_projection="Interrupted Goode Homolosine", resampling="average",
                        scale="source pH x 10 divided by 10", nodata_policy="missing and values outside pH 1-14 are not evaluable")
    validate_candidate(temp, tile, plan)
    os.replace(temp, destination_path)
    return {"file": destination_path.name, "bytes": destination_path.stat().st_size,
            "sha256": sha256_file(destination_path), "valid_cells": int(np.count_nonzero(target != DEST_NODATA))}


def validate_candidate(path, tile, plan):
    """Check a candidate projected tile against the planned shape, transform, CRS and valid physical pH range."""
    gt = grid_transform(plan) * Affine.translation(tile["col"], tile["row"])
    with rasterio.open(path) as src:
        if src.crs != CRS.from_epsg(4326) or src.width != tile["width"] or src.height != tile["height"]:
            raise RuntimeError(f"Candidate tile grid mismatch: {path.name}.")
        if not np.allclose(tuple(src.transform)[:6], tuple(gt)[:6], atol=1e-10):
            raise RuntimeError(f"Candidate tile transform mismatch: {path.name}.")
        src.read(1, window=((0, min(src.height, 8)), (0, min(src.width, 8))))


def build(args):
    """Reproject each validated native depth tile onto the CHELSA grid and report depth-layer validation results."""
    manifest_path = OUT / "download-manifest.json"
    manifest = read_manifest(manifest_path)
    plan = load_plan()
    if len(manifest["completed"]) != len(plan["tiles"]):
        raise RuntimeError("Reprojection is blocked until all native WCS tiles have been downloaded and verified.")
    CHELSA.mkdir(parents=True, exist_ok=True)
    build_path = OUT / "chelsa-build-manifest.json"
    if build_path.exists():
        build_manifest = json.loads(build_path.read_text(encoding="utf-8"))
        if build_manifest.get("plan_sha256") != sha256_file(PLAN_PATH):
            raise RuntimeError("CHELSA output manifest does not match the tile plan.")
    else:
        build_manifest = {"coverage": COVERAGE, "depth": DEPTH_LABEL, "scale": "pH x 10 / 10",
                          "resampling": "average", "plan_sha256": sha256_file(PLAN_PATH), "completed": {}}
    for i, tile in enumerate(plan["tiles"]):
        name = f"ph_{DEPTH_LABEL}_mean_r{tile['row']}-c{tile['col']}.tif"
        dest = CHELSA / name
        old = build_manifest["completed"].get(str(i))
        if old and dest.is_file() and dest.stat().st_size == old["bytes"] and sha256_file(dest) == old["sha256"]:
            validate_candidate(dest, tile, plan)
            print(f"[{i+1}/{len(plan['tiles'])}] candidate already verified: {name}", flush=True)
            continue
        native = NATIVE / tile_name(i, tile)
        validate_native(native, tile_projected_bounds(tile))
        record = reproject_one(native, dest, tile, plan)
        record.update({"tile_row": tile["row"], "tile_col": tile["col"]})
        build_manifest["completed"][str(i)] = record
        write_manifest(build_path, build_manifest)
        print(f"[{i+1}/{len(plan['tiles'])}] reprojected {name}; valid cells={record['valid_cells']}", flush=True)
    build_manifest["complete"] = len(build_manifest["completed"]) == len(plan["tiles"])
    write_manifest(build_path, build_manifest)
    print(f"Built {len(build_manifest['completed'])}/{len(plan['tiles'])} candidate CHELSA-grid tiles in {CHELSA}.", flush=True)


def compare_rwanda():
    """Compare raw-WCS reprojection to the existing Rwanda pH grid, without integrating either."""
    plan = load_plan()
    rwanda_path = DATA / "harmonized" / "Rwanda_ph_CHELSA_grid.tif"
    with rasterio.open(rwanda_path) as rwa:
        existing = rwa.read(1, masked=True).filled(np.nan).astype("float32")
        profile = rwa.profile.copy()
        dst_transform, dst_crs = rwa.transform, rwa.crs
        height, width = rwa.height, rwa.width
    candidate = np.full((height, width), DEST_NODATA, dtype="float32")
    overlaps = []
    with rasterio.open(rwanda_path) as rwa:
        rb = rwa.bounds
    for i, tile in enumerate(plan["tiles"]):
        w, s, e, n = tile["bounds"]
        if e <= rb.left or w >= rb.right or n <= rb.bottom or s >= rb.top:
            continue
        path = NATIVE / tile_name(i, tile)
        validate_native(path, tile_projected_bounds(tile))
        with rasterio.open(path) as src:
            values = source_physical_array(src)
            tmp = np.full((height, width), DEST_NODATA, dtype="float32")
            reproject(values, tmp, src_transform=src.transform, src_crs=src.crs, src_nodata=np.nan,
                      dst_transform=dst_transform, dst_crs=dst_crs, dst_nodata=DEST_NODATA,
                      resampling=Resampling.average, init_dest_nodata=True)
            valid = tmp != DEST_NODATA
            candidate[valid] = tmp[valid]
            overlaps.append(i)
    valid = np.isfinite(existing) & (candidate != DEST_NODATA)
    if not np.any(valid):
        raise RuntimeError("The Rwanda overlap contains no common valid pH cells.")
    diff = np.abs(candidate[valid] - existing[valid])
    result = {
        "overlap_source_tiles": overlaps,
        "existing_valid_cells": int(np.isfinite(existing).sum()),
        "common_valid_cells": int(valid.sum()),
        "mean_absolute_difference_pH": float(diff.mean()),
        "maximum_absolute_difference_pH": float(diff.max()),
        "p95_absolute_difference_pH": float(np.percentile(diff, 95)),
        "source_candidate_range_pH": [float(candidate[valid].min()), float(candidate[valid].max())],
        "existing_range_pH": [float(existing[valid].min()), float(existing[valid].max())],
        "resampling": "SoilGrids raw native 250 m to exact Rwanda target grid with Resampling.average",
        "integrated": False,
    }
    path = OUT / "rwanda-cross-check.json"
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)


def main():
    """Dispatch the explicitly requested download, build or Rwanda-comparison command for the selected depth."""
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("download", "build", "compare-rwanda"))
    parser.add_argument("--depth", choices=tuple(DEPTHS), default="0-5")
    parser.add_argument("--output-root", help="Optional isolated output directory for this depth layer.")
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--limit", type=int, default=0, help="Download only the first N planned tiles (diagnostic).")
    parser.add_argument("--start-index", type=int, default=0, help="Resume from a plan index (default checks all cached tiles).")
    args = parser.parse_args()
    configure_depth(args.depth, args.output_root)
    if args.command == "download": download(args)
    elif args.command == "build": build(args)
    else: compare_rwanda()

if __name__ == "__main__":
    main()
