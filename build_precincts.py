#!/usr/bin/env python3
"""
Build rtd_data/precincts.geojson from source data files.

Inputs (all in project root):
  co_2024_gen_prec.zip         - precinct shapefile with 2024 election results
  co_pl2020_b.zip              - 2020 Census block geometries (PL 94-171 p1 shapefile)
  co_pl2020_block_official.zip - Official incarceration-adjusted block demographics (xlsx)
  co_cvap_2023_b.zip           - 2023 CVAP disaggregated to block level (CSV)
  rtd_data/rtd_boundary.geojson - RTD service area boundary

Output:
  rtd_data/precincts.geojson   - precinct polygons with demographics, CVAP, and vote data

Fields in output:
  colo_prec    - Colorado statewide precinct ID (was incorrectly named GEOID)
  countyfp     - County FIPS code
  county       - County name
  precinct     - County-level precinct number
  unique_id    - "County-:-Precinct" identifier
  total_pop    - Total population (incarceration-adjusted 2020 Census)
  nh_white     - Non-Hispanic white alone
  nh_black     - Non-Hispanic Black alone
  hispanic     - Hispanic or Latino
  nh_asian     - Non-Hispanic Asian alone
  nh_aian      - Non-Hispanic American Indian/Alaska Native alone
  nh_nhpi      - Non-Hispanic Native Hawaiian/Pacific Islander alone
  pct_*        - Percentages of total_pop for each group
  cvap_total   - Total citizen voting age population (2023 ACS)
  cvap_white   - CVAP Non-Hispanic white
  cvap_black   - CVAP Non-Hispanic Black
  cvap_hispanic- CVAP Hispanic
  cvap_asian   - CVAP Non-Hispanic Asian
  dem_votes    - 2024 presidential: Harris votes
  rep_votes    - 2024 presidential: Trump votes
  total_votes  - 2024 presidential: all candidates total
  pct_dem      - dem_votes / total_votes
  centroid_lon/lat - WGS84 centroid
  area_sqkm    - area in square kilometers
"""

import io
import sys
import tempfile
import zipfile
from pathlib import Path

import maup
import pandas as pd
import geopandas as gpd

# ── Paths ──────────────────────────────────────────────────────────────────────
PREC_ZIP  = Path("co_2024_gen_prec.zip")
BLOCK_ZIP = Path("co_pl2020_b.zip")
ADJ_ZIP   = Path("co_pl2020_block_official.zip")
CVAP_ZIP  = Path("co_cvap_2023_b.zip")
RTD_PATH  = Path("rtd_data/rtd_boundary.geojson")
OUT_PATH  = Path("rtd_data/precincts.geojson")

for p in [PREC_ZIP, BLOCK_ZIP, ADJ_ZIP, CVAP_ZIP, RTD_PATH]:
    if not p.exists():
        sys.exit(f"Missing required file: {p}")

# ── Step 1: Load RTD boundary ──────────────────────────────────────────────────
print("Loading RTD boundary …")
rtd = gpd.read_file(RTD_PATH).to_crs("EPSG:26913")
rtd_union = rtd.union_all()
print(f"  RTD area: {rtd_union.area / 1e6:.1f} sq km")

# ── Step 2: Load and filter precinct shapefile ─────────────────────────────────
print("Loading precinct shapefile …")
with zipfile.ZipFile(PREC_ZIP) as zf:
    with tempfile.TemporaryDirectory() as tmpdir:
        zf.extractall(tmpdir)
        shp = next(Path(tmpdir).rglob("*.shp"))
        precincts_raw = gpd.read_file(shp).to_crs("EPSG:26913")

print(f"  {len(precincts_raw)} total CO precincts")

# Filter to precincts that have meaningful overlap with the RTD boundary
# (overlap area > 10% of precinct area, to exclude mere boundary touches)
rtd_series = gpd.GeoSeries([rtd_union], crs="EPSG:26913")
intersection_area = precincts_raw.geometry.intersection(rtd_union).area
overlap_frac = intersection_area / precincts_raw.geometry.area
in_rtd = overlap_frac > 0.05
precincts = precincts_raw[in_rtd].copy().reset_index(drop=True)
print(f"  {len(precincts)} precincts within RTD boundary")

# ── Step 3: Load block geometries (p1 shapefile — geometry + GEOID20 only) ────
print("Loading block geometries (this may take a minute) …")
with zipfile.ZipFile(BLOCK_ZIP) as zf:
    with tempfile.TemporaryDirectory() as tmpdir:
        p1_files = [f for f in zf.namelist() if "p1_b" in f]
        zf.extractall(tmpdir, members=p1_files)
        shp = next(Path(tmpdir).rglob("co_pl2020_p1_b.shp"))
        blocks = gpd.read_file(shp, columns=["GEOID20"]).to_crs("EPSG:26913")

print(f"  {len(blocks)} total CO blocks")

# ── Step 4: Load official adjusted demographics from xlsx ──────────────────────
print("Loading official adjusted demographics …")
with zipfile.ZipFile(ADJ_ZIP) as zf:
    xlsx_bytes = zf.read("2020_Block_Adj_Final.xlsx")

adj = pd.read_excel(
    io.BytesIO(xlsx_bytes),
    sheet_name="BLOCK20_ADJ",
    dtype={"GEOID20": str},
    usecols=["GEOID20", "TOTALPOP_ADJ", "HISPANIC_ADJ", "NHWHITE_ADJ",
             "NHBLACK_ADJ", "NHAMERI_ADJ", "NHASIAN_ADJ", "NHPI_ADJ"],
)
adj = adj.rename(columns={
    "TOTALPOP_ADJ": "total_pop",
    "HISPANIC_ADJ": "hispanic",
    "NHWHITE_ADJ":  "nh_white",
    "NHBLACK_ADJ":  "nh_black",
    "NHAMERI_ADJ":  "nh_aian",
    "NHASIAN_ADJ":  "nh_asian",
    "NHPI_ADJ":     "nh_nhpi",
})
print(f"  {len(adj)} adjusted block records")

# ── Step 5: Load CVAP ──────────────────────────────────────────────────────────
print("Loading CVAP data …")
with zipfile.ZipFile(CVAP_ZIP) as zf:
    cvap_bytes = zf.read("co/co_cvap_2023_2020_b.csv")

cvap = pd.read_csv(
    io.BytesIO(cvap_bytes),
    dtype={"GEOID20": str},
    usecols=["GEOID20", "CVAP_TOT23", "CVAP_HSP23", "CVAP_WHT23",
             "CVAP_BLA23", "CVAP_ASI23"],
)
cvap = cvap.rename(columns={
    "CVAP_TOT23": "cvap_total",
    "CVAP_HSP23": "cvap_hispanic",
    "CVAP_WHT23": "cvap_white",
    "CVAP_BLA23": "cvap_black",
    "CVAP_ASI23": "cvap_asian",
})
print(f"  {len(cvap)} CVAP block records")

# ── Step 6: Join demographics and CVAP to blocks ──────────────────────────────
print("Joining demographics to blocks …")
demo_cols = ["total_pop", "hispanic", "nh_white", "nh_black",
             "nh_aian", "nh_asian", "nh_nhpi"]
cvap_cols = ["cvap_total", "cvap_hispanic", "cvap_white", "cvap_black", "cvap_asian"]

blocks = blocks.merge(adj[["GEOID20"] + demo_cols], on="GEOID20", how="left")
blocks = blocks.merge(cvap[["GEOID20"] + cvap_cols], on="GEOID20", how="left")

for col in demo_cols + cvap_cols:
    blocks[col] = pd.to_numeric(blocks[col], errors="coerce").fillna(0)

# ── Step 7: Use maup to assign blocks → precincts and aggregate ───────────────
print("Assigning blocks to precincts (maup) …")
assignment = maup.assign(blocks, precincts)

unassigned = assignment.isna().sum()
if unassigned:
    print(f"  Warning: {unassigned} blocks not assigned to any precinct")

print("Aggregating demographics to precincts …")
all_demo = demo_cols + cvap_cols
precincts[all_demo] = blocks[all_demo].groupby(assignment).sum().reindex(precincts.index, fill_value=0)

# ── Step 8: Add vote data from precinct shapefile ──────────────────────────────
print("Adding vote data …")
pre_cols = [c for c in precincts.columns if c.startswith("G24PRE")]
for col in pre_cols:
    precincts[col] = pd.to_numeric(precincts[col], errors="coerce").fillna(0)

precincts["dem_votes"]   = precincts["G24PREDHAR"].astype(int)
precincts["rep_votes"]   = precincts["G24PRERTRU"].astype(int)
precincts["total_votes"] = precincts[pre_cols].sum(axis=1).astype(int)
precincts["pct_dem"] = (
    precincts["dem_votes"] / precincts["total_votes"]
).where(precincts["total_votes"] > 0, 0).round(6)

# ── Step 9: Derived percentage fields ─────────────────────────────────────────
for grp, col in [("white", "nh_white"), ("black", "nh_black"),
                 ("hispanic", "hispanic"), ("asian", "nh_asian")]:
    precincts[f"pct_{grp}"] = (
        precincts[col] / precincts["total_pop"]
    ).where(precincts["total_pop"] > 0, 0).round(4)

# ── Step 10: Centroid and area ─────────────────────────────────────────────────
# Compute centroid in projected CRS (UTM), then convert coords to WGS84
centroids_utm = precincts.geometry.centroid
centroids_wgs = gpd.GeoSeries(centroids_utm, crs="EPSG:26913").to_crs("EPSG:4326")
precincts["centroid_lon"] = centroids_wgs.x.round(6)
precincts["centroid_lat"] = centroids_wgs.y.round(6)
precincts["area_sqkm"]   = (precincts.geometry.area / 1e6).round(4)

# ── Step 11: Rename and select output columns ──────────────────────────────────
precincts = precincts.rename(columns={
    "COLO_PREC": "colo_prec",
    "COUNTYFP":  "countyfp",
    "County":    "county",
    "PRECINCT":  "precinct",
    "UNIQUE_ID": "unique_id",
})

out_cols = [
    "colo_prec", "countyfp", "county", "precinct", "unique_id",
    "total_pop", "nh_white", "nh_black", "hispanic", "nh_asian", "nh_aian", "nh_nhpi",
    "pct_white", "pct_black", "pct_hispanic", "pct_asian",
    "cvap_total", "cvap_white", "cvap_black", "cvap_hispanic", "cvap_asian",
    "centroid_lon", "centroid_lat", "area_sqkm",
    "dem_votes", "rep_votes", "total_votes", "pct_dem",
    "geometry",
]
out_cols = [c for c in out_cols if c in precincts.columns or c == "geometry"]
precincts = precincts[out_cols].to_crs("EPSG:4326")

# ── Step 12: Write output ──────────────────────────────────────────────────────
print(f"Writing {OUT_PATH} …")
precincts.to_file(OUT_PATH, driver="GeoJSON")

print(f"\nDone. {len(precincts)} precincts written.")
zero_pop = (precincts["total_pop"] == 0).sum()
print(f"  Zero-population precincts: {zero_pop}")
print(f"  Total population: {precincts['total_pop'].sum():,.0f}")
print(f"  Population range: {precincts['total_pop'].min():.0f} – {precincts['total_pop'].max():.0f}")
