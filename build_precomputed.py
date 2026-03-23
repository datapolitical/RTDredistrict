#!/usr/bin/env python3
"""
Build rtd_data/precomputed.json from source GeoJSON files.

Inputs:
  rtd_data/precincts.geojson       - precinct polygons with demographics and CVAP (built by build_precincts.py)
  rtd_data/municipalities.geojson  - municipality polygons for muniId assignment
  rtd_data/rtd_boundary.geojson    - RTD service area boundary for clipping
  DirectorDistricts.geojson        - current 15-director district map

Output:
  rtd_data/precomputed.json        - precincts, adjacency, groups, current district stats

CRS: all spatial ops in UTM Zone 13N (EPSG:26913); lon/lat stored in WGS84.
Adjacency: 50 m buffer to handle county-boundary slivers; isolated precincts
           connected via nearest-centroid bridge links.
"""

import json
import sys
from pathlib import Path
from collections import defaultdict

try:
    import numpy as np
    from pyproj import Transformer
    from shapely.geometry import shape, mapping
    from shapely.ops import transform as shp_transform
    from shapely.strtree import STRtree
except ImportError as e:
    sys.exit(f"Missing dependency: {e}\nRun: pip install shapely pyproj numpy")

PRECINCTS_PATH       = Path("rtd_data/precincts.geojson")
MUNIS_PATH           = Path("rtd_data/municipalities.geojson")
RTD_PATH             = Path("rtd_data/rtd_boundary.geojson")
DIRECTOR_DISTS_PATH  = Path("DirectorDistricts.geojson")
OUTPUT_PATH          = Path("rtd_data/precomputed.json")
BUFFER_M             = 50.0   # metres for adjacency detection

# ── CRS transformers ──────────────────────────────────────────────────────────
wgs84_to_utm  = Transformer.from_crs("EPSG:4326", "EPSG:26913", always_xy=True)
utm_to_wgs84  = Transformer.from_crs("EPSG:26913", "EPSG:4326", always_xy=True)

def to_utm(geom):
    return shp_transform(wgs84_to_utm.transform, geom)

# ── Load RTD boundary ─────────────────────────────────────────────────────────
print("Loading RTD boundary …")
with open(RTD_PATH) as f:
    rtd_fc = json.load(f)

rtd_union = None
for feat in rtd_fc["features"]:
    g = to_utm(shape(feat["geometry"]).buffer(0))
    rtd_union = g if rtd_union is None else rtd_union.union(g)
print(f"  RTD boundary area: {rtd_union.area / 1e6:.1f} sq km")

# ── Load precincts ────────────────────────────────────────────────────────────
print("Loading precincts …")
with open(PRECINCTS_PATH) as f:
    prec_fc = json.load(f)

features = prec_fc["features"]
n = len(features)
print(f"  {n} precincts found")

# Build UTM geometries, clip to RTD boundary, compute centroids
utm_geoms   = []
centroids_x = []
centroids_y = []
lons        = []
lats        = []

outside_count = 0
for feat in features:
    g = to_utm(shape(feat["geometry"]).buffer(0))
    clipped = g.intersection(rtd_union)
    if clipped.is_empty:
        clipped = g
    elif g.area > 0 and (g.area - clipped.area) / g.area > 0.01:
        outside_count += 1
    utm_geoms.append(clipped)
    cx, cy = clipped.centroid.x, clipped.centroid.y
    centroids_x.append(cx)
    centroids_y.append(cy)
    lon, lat = utm_to_wgs84.transform(cx, cy)
    lons.append(round(lon, 6))
    lats.append(round(lat, 6))

if outside_count:
    print(f"  Clipped {outside_count} precincts to RTD boundary")

# ── Load municipalities and assign muniId ────────────────────────────────────
print("Loading municipalities …")
with open(MUNIS_PATH) as f:
    muni_fc = json.load(f)

muni_geoms = []
muni_ids   = {}   # PLACEFP -> integer id (1-based; 0 = unincorporated)
muni_id_counter = 1

for feat in muni_fc["features"]:
    placefp = feat["properties"].get("PLACEFP", "")
    if placefp not in muni_ids:
        muni_ids[placefp] = muni_id_counter
        muni_id_counter += 1
    muni_geoms.append((to_utm(shape(feat["geometry"])), muni_ids[placefp]))

muni_tree = STRtree([g for g, _ in muni_geoms])

print("Assigning muniIds …")
muni_id_list = []
for i, g in enumerate(utm_geoms):
    centroid = g.centroid
    hits = muni_tree.query(centroid)
    assigned = 0
    for j in hits:
        mg, mid = muni_geoms[j]
        if mg.contains(centroid):
            assigned = mid
            break
    muni_id_list.append(assigned)

# ── Build adjacency via buffered intersection ────────────────────────────────
print("Building adjacency list (50 m buffer) …")
buffered = [g.buffer(BUFFER_M) for g in utm_geoms]
tree = STRtree(buffered)

adj = [set() for _ in range(n)]
for i, buf in enumerate(buffered):
    candidates = tree.query(buf)
    for j in candidates:
        if j <= i:
            continue
        if buf.intersects(buffered[j]):
            adj[i].add(j)
            adj[j].add(i)
    if (i + 1) % 200 == 0:
        print(f"  {i+1}/{n} …")

# Save geographic adjacency (real shared-border edges only, no bridges)
geo_adj = [set(s) for s in adj]

# ── Connect isolated components via nearest-centroid bridges ─────────────────
print("Checking connectivity …")
cx = np.array(centroids_x)
cy = np.array(centroids_y)

def find_components(adj_sets, n):
    visited = [-1] * n
    comp = 0
    for start in range(n):
        if visited[start] != -1:
            continue
        stack = [start]
        while stack:
            node = stack.pop()
            if visited[node] != -1:
                continue
            visited[node] = comp
            stack.extend(adj_sets[node] - {node})
        comp += 1
    return visited, comp

visited, num_comp = find_components(adj, n)
print(f"  {num_comp} component(s) before bridging")

if num_comp > 1:
    comp_members = defaultdict(list)
    for i, c in enumerate(visited):
        comp_members[c].append(i)

    main_comp = max(comp_members, key=lambda c: len(comp_members[c]))

    for comp_id, members in comp_members.items():
        if comp_id == main_comp:
            continue
        best_i, best_j, best_d = -1, -1, float("inf")
        for i in members:
            mask = np.array([visited[k] != comp_id for k in range(n)])
            dx = cx[mask] - cx[i]
            dy = cy[mask] - cy[i]
            dists = np.sqrt(dx*dx + dy*dy)
            j_local = np.argmin(dists)
            j_global = np.where(mask)[0][j_local]
            d = dists[j_local]
            if d < best_d:
                best_d = d
                best_i, best_j = i, j_global
        adj[best_i].add(best_j)
        adj[best_j].add(best_i)
        print(f"  Bridge: precinct {best_i} <-> {best_j} ({best_d:.0f} m)")

    visited, num_comp = find_components(adj, n)
    print(f"  {num_comp} component(s) after bridging")

# ── Assemble precinct records ─────────────────────────────────────────────────
print("Assembling output …")
precincts_out = []
for i, feat in enumerate(features):
    p = feat["properties"]
    precincts_out.append({
        "idx":           i,
        "colo_prec":     str(p.get("colo_prec", "")),
        "countyfp":      str(p.get("countyfp", "")),
        "county":        str(p.get("county", "")),
        "precinct":      str(p.get("precinct", "")),
        "unique_id":     str(p.get("unique_id", "")),
        "x":             round(centroids_x[i], 1),
        "y":             round(centroids_y[i], 1),
        "lon":           lons[i],
        "lat":           lats[i],
        "pop":           int(p.get("total_pop", 0)),
        "nh_white":      int(p.get("nh_white", 0)),
        "nh_black":      int(p.get("nh_black", 0)),
        "hispanic":      int(p.get("hispanic", 0)),
        "nh_asian":      int(p.get("nh_asian", 0)),
        "nh_aian":       int(p.get("nh_aian", 0)),
        "nh_nhpi":       int(p.get("nh_nhpi", 0)),
        "pct_white":     round(float(p.get("pct_white",    0)), 4),
        "pct_black":     round(float(p.get("pct_black",    0)), 4),
        "pct_hispanic":  round(float(p.get("pct_hispanic", 0)), 4),
        "pct_asian":     round(float(p.get("pct_asian",    0)), 4),
        "cvap_total":    round(float(p.get("cvap_total",    0)), 2),
        "cvap_white":    round(float(p.get("cvap_white",    0)), 2),
        "cvap_black":    round(float(p.get("cvap_black",    0)), 2),
        "cvap_hispanic": round(float(p.get("cvap_hispanic", 0)), 2),
        "cvap_asian":    round(float(p.get("cvap_asian",    0)), 2),
        "muniId":        muni_id_list[i],
        "hasGeom":       True,
    })

# ── muniGroups and countyGroups ───────────────────────────────────────────────
muni_buckets   = defaultdict(list)
county_buckets = defaultdict(list)
for i, p in enumerate(precincts_out):
    muni_buckets[p["muniId"]].append(i)
    county_buckets[p["countyfp"]].append(i)

muni_groups_out   = list(muni_buckets.values())
county_groups_out = list(county_buckets.values())

# ── Current director district stats ──────────────────────────────────────────
print("Computing current district stats …")
current_dist_stats = {}

if DIRECTOR_DISTS_PATH.exists():
    with open(DIRECTOR_DISTS_PATH) as f:
        dir_fc = json.load(f)

    dir_geoms  = []
    dir_labels = []
    for feat in dir_fc["features"]:
        g = to_utm(shape(feat["geometry"]).buffer(0))
        dir_geoms.append(g)
        dir_labels.append(feat["properties"].get("BND", str(len(dir_labels))))

    dir_tree = STRtree(dir_geoms)

    # Assign each precinct to a director district by centroid containment
    precinct_dir = [-1] * n
    for i, g in enumerate(utm_geoms):
        centroid = g.centroid
        hits = dir_tree.query(centroid)
        for j in hits:
            if dir_geoms[j].contains(centroid):
                precinct_dir[i] = j
                break

    # Aggregate stats per director district
    for d_idx, label in enumerate(dir_labels):
        members = [i for i in range(n) if precinct_dir[i] == d_idx]
        pop      = sum(precincts_out[i]["pop"]      for i in members)
        nh_black = sum(precincts_out[i]["nh_black"] for i in members)
        hispanic = sum(precincts_out[i]["hispanic"] for i in members)
        nh_asian = sum(precincts_out[i]["nh_asian"] for i in members)
        nh_white = sum(precincts_out[i]["nh_white"] for i in members)
        current_dist_stats[label] = {
            "pop":         pop,
            "nh_white":    nh_white,
            "nh_black":    nh_black,
            "hispanic":    hispanic,
            "nh_asian":    nh_asian,
            "pct_minority": round((nh_black + hispanic + nh_asian) / pop, 4) if pop > 0 else 0,
        }
    print(f"  {len(current_dist_stats)} director districts processed")
else:
    print(f"  {DIRECTOR_DISTS_PATH} not found, skipping currentDistrictStats")

# ── Write output ──────────────────────────────────────────────────────────────
output = {
    "precincts":           precincts_out,
    "adjacency":           [sorted(int(x) for x in s) for s in adj],
    "geoAdjacency":        [sorted(int(x) for x in s) for s in geo_adj],
    "muniGroups":          muni_groups_out,
    "countyGroups":        county_groups_out,
    "currentDistrictStats": current_dist_stats,
}

with open(OUTPUT_PATH, "w") as f:
    json.dump(output, f, separators=(",", ":"))

print(f"\nWrote {OUTPUT_PATH}  ({OUTPUT_PATH.stat().st_size // 1024} KB)")
print("Done.")
